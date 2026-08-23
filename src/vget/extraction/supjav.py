"""SupJav extractor.

Parsing rules are derived from ALOS/UAV Downloader (Apache-2.0), commit
d6fda487ddc5967dfd32dcca8b89966e277a398f. See NOTICE and LICENSE.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from vget.constants import SEGMENT_TRANSFORM_SUPJAV_FAKE_PNG
from vget.errors import AccessBlockedError, ExtractionError
from vget.http import HttpClient
from vget.models import MediaSource, Quality

from .base import (
    Extractor,
    absolute_media_matches,
    fetch_with_mirrors,
    is_blocked,
    origin,
    page_title,
    response_url,
    thumbnail,
    unpack_packed_script,
)

SUPREMEJAV = "https://lk1.supremejav.com/supjav.php?c={}"
SUPJAV_HOME = "https://supjav.com/"
SUPJAV_SOURCE_TIMEOUT_SECONDS = 25
SERVER_FST = "FST"
SERVER_STREAMTAPE = "ST"
SERVER_TV = "TV"


def server_links(markup: str) -> dict[str, str]:
    soup = BeautifulSoup(markup, "html.parser")
    result: dict[str, str] = {}
    for anchor in soup.select("a.btn-server[data-link]"):
        name = anchor.get_text(strip=True).upper()
        value = str(anchor.get("data-link") or "")
        if name and value and name not in result:
            result[name] = value
    return result


def streamtape_direct_url(markup: str) -> str | None:
    match = re.search(
        r"getElementById\(\s*['\"]robotlink['\"]\s*\)\.innerHTML\s*=\s*"
        r"['\"]([^'\"]*)['\"]\s*\+\s*(?:['\"]{2}\s*\+\s*)?"
        r"\(\s*['\"]([^'\"]*)['\"]\s*\)((?:\.substring\(\s*\d+\s*\))+)",
        markup,
    )
    if not match:
        return None
    prefix, suffix, operations = match.groups()
    for offset in re.findall(r"substring\(\s*(\d+)\s*\)", operations):
        suffix = suffix[int(offset) :]
    link = (prefix + suffix).lstrip("/")
    return "https://" + link if "get_video" in link else None


def packed_m3u8(markup: str) -> str | None:
    for script in re.findall(r"<script[^>]*>(.*?)</script>", markup, re.DOTALL | re.I):
        if "eval(function" not in script or "m3u8" not in script:
            continue
        unpacked = unpack_packed_script(script)
        streams = absolute_media_matches(unpacked or "", "m3u8")
        if streams:
            return streams[0]
    return None


class SupJavExtractor(Extractor):
    site = "supjav"
    _pattern = re.compile(r"https://(?:www\.)?supjav\.com/(?:(?:zh|ja)/)?(\d+)\.html", re.I)

    @classmethod
    def supports(cls, url: str) -> bool:
        return bool(cls._pattern.fullmatch(url))

    def extract(self, url: str, client: HttpClient, quality: Quality) -> MediaSource:
        match = self._pattern.fullmatch(url)
        assert match
        response, _ = fetch_with_mirrors(
            client,
            url,
            "supjav",
            lambda item: "data-link" in item.text,
        )
        actual_url = response_url(response, url)
        soup = BeautifulSoup(response.content, "html.parser")
        servers = server_links(response.text)
        if not servers:
            raise ExtractionError("SupJav 页面没有可用服务器来源")

        hls_url, hls_headers = self._hls_source(client, servers)
        direct_url, direct_referer = self._direct_source(client, servers)
        if not hls_url and not direct_url:
            hls_url = self._tv_source(client, servers)
        if not hls_url and not direct_url:
            raise ExtractionError("SupJav 当前没有可用的 FST、Streamtape 或 TV 下载来源")

        title = page_title(soup) or match.group(1)
        common = {
            "page_url": url,
            "title": title,
            "media_id": match.group(1),
            "site": self.site,
            "thumbnail_url": thumbnail(soup, actual_url),
        }
        fallback = None
        if direct_url:
            fallback = MediaSource(
                media_url=direct_url,
                kind="direct",
                headers={"Referer": direct_referer},
                **common,
            )
        if hls_url:
            return MediaSource(
                media_url=hls_url,
                kind="hls",
                headers=hls_headers,
                segment_transform=SEGMENT_TRANSFORM_SUPJAV_FAKE_PNG,
                fallback=fallback,
                **common,
            )
        assert fallback
        return fallback

    @staticmethod
    def _hls_source(
        client: HttpClient, servers: dict[str, str]
    ) -> tuple[str | None, dict[str, str]]:
        headers = {"Referer": SUPJAV_HOME}
        if SERVER_FST not in servers:
            return None, headers
        try:
            response = client.get(
                SUPREMEJAV.format(servers[SERVER_FST][::-1]),
                headers=headers,
                timeout=SUPJAV_SOURCE_TIMEOUT_SECONDS,
            )
            if is_blocked(response):
                return None, headers
            media_url = packed_m3u8(response.text)
            if not media_url:
                return None, headers
            actual = response_url(response, SUPJAV_HOME)
            headers = {"Referer": actual}
            if origin(actual):
                headers["Origin"] = origin(actual)
            return media_url, headers
        except Exception:
            return None, headers

    @staticmethod
    def _direct_source(client: HttpClient, servers: dict[str, str]) -> tuple[str | None, str]:
        referer = SUPJAV_HOME
        if SERVER_STREAMTAPE not in servers:
            return None, referer
        try:
            response = client.get(
                SUPREMEJAV.format(servers[SERVER_STREAMTAPE][::-1]),
                headers={"Referer": referer},
                timeout=SUPJAV_SOURCE_TIMEOUT_SECONDS,
            )
            if is_blocked(response):
                return None, referer
            return streamtape_direct_url(response.text), response_url(response, referer)
        except Exception:
            return None, referer

    @staticmethod
    def _tv_source(client: HttpClient, servers: dict[str, str]) -> str | None:
        if SERVER_TV not in servers:
            return None
        try:
            response = client.get(
                SUPREMEJAV.format(servers[SERVER_TV][::-1]),
                headers={"Referer": SUPJAV_HOME},
                timeout=SUPJAV_SOURCE_TIMEOUT_SECONDS,
            )
            if is_blocked(response):
                raise AccessBlockedError("SupJav TV 来源被阻止")
            streams = absolute_media_matches(response.text.replace("\\/", "/"), "m3u8")
            return streams[0] if streams else None
        except AccessBlockedError:
            raise
        except Exception:
            return None
