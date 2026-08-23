"""MissAV extractor adapted and modified from ALOS/UAV Downloader.

Licensed under Apache-2.0. See NOTICE.
"""

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from vget.errors import ExtractionError
from vget.http import HttpClient
from vget.models import MediaSource, Quality

from .base import (
    MIRRORS,
    Extractor,
    absolute_media_matches,
    fetch_with_mirrors,
    page_title,
    response_url,
    thumbnail,
    unpack_packed_script,
)


class MissAVExtractor(Extractor):
    site = "missav"
    _hosts = frozenset(MIRRORS["missav"])

    @classmethod
    def supports(cls, url: str) -> bool:
        parsed = urlsplit(url)
        if (parsed.hostname or "").lower() not in cls._hosts:
            return False
        slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        return bool(slug and re.search(r"\d", slug) and not slug.lower().startswith("dm"))

    def extract(self, url: str, client: HttpClient, quality: Quality) -> MediaSource:
        slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]

        def headers_for(host: str) -> dict[str, str]:
            return {"Referer": f"https://{host}/", "Origin": f"https://{host}"}

        response, host = fetch_with_mirrors(
            client,
            url,
            "missav",
            lambda item: (
                "og:title" in item.text and ("m3u8" in item.text or "eval(function" in item.text)
            ),
            headers_factory=headers_for,
        )
        soup = BeautifulSoup(response.content, "html.parser")
        media_url = self._media_url(response.text)
        if not media_url:
            raise ExtractionError("MissAV 页面没有找到可用 M3U8 地址")
        title = page_title(soup)
        if not title:
            raise ExtractionError("MissAV 页面标题解析失败")
        return MediaSource(
            page_url=url,
            media_url=media_url,
            kind="hls",
            title=title,
            media_id=slug,
            site=self.site,
            thumbnail_url=thumbnail(soup, response_url(response, url)),
            headers=headers_for(host),
        )

    @staticmethod
    def _media_url(markup: str) -> str | None:
        for script in re.findall(r"<script[^>]*>(.*?)</script>", markup, re.DOTALL | re.I):
            if "eval(function" not in script or "m3u8" not in script:
                continue
            unpacked = unpack_packed_script(script)
            if not unpacked:
                continue
            preferred = re.search(
                r"source\s*=\s*[\\']*(https?://[^'\\;\s]+\.m3u8[^'\\;\s]*)",
                unpacked,
            )
            candidates = absolute_media_matches(unpacked, "m3u8")
            selected = preferred.group(1) if preferred else (candidates[0] if candidates else None)
            if selected:
                return selected
        candidates = absolute_media_matches(markup, "m3u8")
        return candidates[0] if candidates else None
