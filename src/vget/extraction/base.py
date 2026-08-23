"""Shared contracts and parsing helpers for site extractors.

Portions adapted and modified from ALOS/UAV Downloader (Apache-2.0). See NOTICE.
"""

from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from vget.constants import DEFAULT_REQUEST_TIMEOUT_SECONDS, RESOLUTION_QUALITIES
from vget.errors import AccessBlockedError, ExtractionError
from vget.http import HttpClient
from vget.models import MediaSource, Quality

MIRRORS = {
    "jable": ("jable.tv", "fs1.app"),
    "missav": ("missav.ai", "missav.ws", "missav123.com", "missav.live"),
    "supjav": ("supjav.com",),
}
BLOCKED_HTTP_STATUSES = frozenset({403, 429, 503})
BLOCK_PAGE_SCAN_BYTES = 20_000
CLOUDFLARE_MITIGATION_HEADER = "cf-mitigated"
CLOUDFLARE_MITIGATION_VALUE = "challenge"
CLOUDFLARE_MARKERS = (
    b"just a moment",
    b"attention required",
    b"cf-browser-verification",
    b"cf_chl_",
    b"cf-chl-",
)
MAX_PACKED_KEY_COUNT = 200_000
MAX_PACKER_BASE = 36
MIRROR_REQUEST_ATTEMPTS = 2
MIN_PACKER_BASE = 2
PACKER_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


class Extractor(ABC):
    site = "unknown"

    @classmethod
    @abstractmethod
    def supports(cls, url: str) -> bool: ...

    @abstractmethod
    def extract(self, url: str, client: HttpClient, quality: Quality) -> MediaSource: ...


def status_code(response: object) -> int:
    return int(getattr(response, "status_code", 0) or 0)


def response_url(response: object, fallback: str) -> str:
    return str(getattr(response, "url", "") or fallback)


def is_blocked(response: object) -> bool:
    if status_code(response) in BLOCKED_HTTP_STATUSES:
        return True
    headers = getattr(response, "headers", {}) or {}
    if CLOUDFLARE_MITIGATION_VALUE in str(headers.get(CLOUDFLARE_MITIGATION_HEADER, "")).lower():
        return True
    body = getattr(response, "content", b"") or b""
    if isinstance(body, str):
        body = body.encode("utf-8", errors="ignore")
    head = body[:BLOCK_PAGE_SCAN_BYTES].lower()
    return any(marker in head for marker in CLOUDFLARE_MARKERS)


def origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def _swap_host(url: str, host: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme or "https", host, parsed.path, parsed.query, parsed.fragment))


def fetch_with_mirrors(
    client: HttpClient,
    url: str,
    site_key: str,
    validate: Callable[[object], bool],
    *,
    timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    headers_factory: Callable[[str], dict[str, str]] | None = None,
):
    """Fetch from an allowlisted mirror and reject redirects outside that list."""

    allowed = MIRRORS[site_key]
    original = (urlsplit(url).hostname or "").lower()
    hosts = [original, *(host for host in allowed if host != original)]
    saw_real_response = False
    for host in hosts:
        if host not in allowed:
            continue
        target = _swap_host(url, host)
        headers = dict(headers_factory(host) or {}) if headers_factory else {}
        response = None
        for _ in range(MIRROR_REQUEST_ATTEMPTS):
            try:
                response = client.get(target, headers=headers, timeout=timeout)
                break
            except Exception:
                response = None
        if response is None or is_blocked(response):
            continue
        final_host = (urlsplit(response_url(response, target)).hostname or "").lower()
        if final_host not in allowed:
            continue
        saw_real_response = True
        try:
            if validate(response):
                return response, host
        except Exception:
            continue
    if saw_real_response:
        raise ExtractionError("页面中没有找到可用视频，网站结构可能已经变化")
    raise AccessBlockedError(
        "页面被 Cloudflare/来源站阻止，请更换网络、代理或提供有效 Cookie 后重试"
    )


def clean_text(value: object) -> str:
    return " ".join(html.unescape(str(value or "")).replace("\xa0", " ").split())


def meta_content(soup: BeautifulSoup, property_name: str) -> str | None:
    element = soup.select_one(f'meta[property="{property_name}"][content]')
    return clean_text(element.get("content")) if element else None


def page_title(soup: BeautifulSoup) -> str:
    title = meta_content(soup, "og:title")
    if title:
        return title
    heading = soup.find("h1")
    if heading:
        title = clean_text(heading.get_text(" ", strip=True))
        if title:
            return title
    return clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")


def thumbnail(soup: BeautifulSoup, base_url: str) -> str | None:
    raw = meta_content(soup, "og:image")
    return urljoin(base_url, raw) if raw else None


def absolute_media_matches(text: str, extension: str) -> list[str]:
    normalized = html.unescape(text).replace("\\/", "/")
    pattern = rf'https?://[^\s\'"<>\\]+?\.{re.escape(extension)}(?:\?[^\s\'"<>\\]*)?'
    found: list[str] = []
    for match in re.findall(pattern, normalized, flags=re.I):
        value = match.rstrip("),;]")
        if value not in found:
            found.append(value)
    return found


def media_height(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{3,4})\s*p(?!\w)", value, re.I)
    return int(match.group(1)) if match else None


def choose_by_quality(items: list[tuple[str, int | None]], quality: Quality) -> str | None:
    if not items:
        return None
    known = [item for item in items if item[1] is not None]
    if quality == "lowest":
        return min(known, key=lambda item: item[1] or 0)[0] if known else items[0][0]
    if quality in RESOLUTION_QUALITIES:
        if not known:
            return items[0][0]
        limit = int(quality)
        at_or_below = [item for item in known if (item[1] or 0) <= limit]
        if at_or_below:
            return max(at_or_below, key=lambda item: item[1] or 0)[0]
        return min(known, key=lambda item: item[1] or 0)[0]
    return max(known, key=lambda item: item[1] or 0)[0] if known else items[0][0]


def unpack_packed_script(script_text: str) -> str | None:
    """Decode the bounded Dean Edwards p,a,c,k,e,d form used by supported sites."""

    match = re.search(
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('(.*?)',\s*(\d+),\s*(\d+),\s*'([^']*)'\s*\.split\('\|'\)",
        script_text,
        re.DOTALL,
    )
    if not match:
        return None
    packed = match.group(1)
    base = int(match.group(2))
    count = int(match.group(3))
    keys = match.group(4).split("|")
    if not MIN_PACKER_BASE <= base <= MAX_PACKER_BASE or not 0 <= count <= MAX_PACKED_KEY_COUNT:
        return None

    def to_base(number: int) -> str:
        if number == 0:
            return "0"
        result = ""
        while number:
            result = PACKER_DIGITS[number % base] + result
            number //= base
        return result

    lookup = {
        to_base(index): keys[index] if index < len(keys) and keys[index] else to_base(index)
        for index in range(count)
    }
    return re.sub(r"\b(\w+)\b", lambda item: lookup.get(item.group(0), item.group(0)), packed)
