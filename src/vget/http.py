from __future__ import annotations

import http.cookiejar
from contextlib import suppress
from pathlib import Path
from typing import Any

import requests

from .constants import DEFAULT_REQUEST_TIMEOUT_SECONDS, HTTP_URL_PREFIXES

CONNECTION_POOL_SIZE = 32
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MAX_CONNECTION_POOL_SIZE = 64
TLS_IMPERSONATION = "chrome"


class HttpClient:
    """Small response-compatible wrapper around curl_cffi/requests.

    curl_cffi is preferred because the supported sites commonly expect a
    browser-like TLS fingerprint. Requests remains a functional fallback for
    direct MP4/M3U8 URLs and less restrictive pages.
    """

    def __init__(
        self,
        *,
        proxy: str | None = None,
        cookie_file: Path | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.proxy = proxy
        self.default_headers = {"User-Agent": user_agent or DEFAULT_USER_AGENT}
        self.backend = "requests"
        try:
            from curl_cffi import requests as cffi_requests

            self.session: Any = cffi_requests.Session(impersonate=TLS_IMPERSONATION)
            self.backend = "curl_cffi"
        except Exception:
            self.session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=CONNECTION_POOL_SIZE,
                pool_maxsize=MAX_CONNECTION_POOL_SIZE,
                max_retries=0,
            )
            for prefix in HTTP_URL_PREFIXES:
                self.session.mount(prefix, adapter)
        if cookie_file:
            self.load_cookies(cookie_file)

    def load_cookies(self, path: Path) -> None:
        jar = http.cookiejar.MozillaCookieJar(str(path))
        jar.load(ignore_discard=True, ignore_expires=True)
        for cookie in jar:
            kwargs: dict[str, Any] = {"path": cookie.path or "/"}
            if cookie.domain:
                kwargs["domain"] = cookie.domain
            self.session.cookies.set(cookie.name, cookie.value, **kwargs)

    def set_cookie(self, name: str, value: str, *, domain: str) -> None:
        with suppress(Exception):
            self.session.cookies.set(name, value, domain=domain, path="/")

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        stream: bool = False,
        allow_redirects: bool = True,
    ) -> Any:
        merged_headers = {**self.default_headers, **(headers or {})}
        kwargs: dict[str, Any] = {
            "headers": merged_headers,
            "timeout": timeout,
            "stream": stream,
            "allow_redirects": allow_redirects,
        }
        if self.proxy:
            kwargs["proxies"] = {
                "http": self.proxy,
                "https": self.proxy,
                "all": self.proxy,
            }
        return self.session.get(url, **kwargs)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
