"""Hanime1 signed-MP4 extractor adapted and modified from ALOS/UAV Downloader.

Licensed under Apache-2.0. See NOTICE.
"""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from vget.constants import DEFAULT_REQUEST_TIMEOUT_SECONDS, HTTP_OK, MP4_SUFFIX
from vget.errors import AccessBlockedError, ExtractionError
from vget.http import HttpClient
from vget.models import MediaSource, Quality

from .base import (
    Extractor,
    absolute_media_matches,
    choose_by_quality,
    is_blocked,
    media_height,
    page_title,
    status_code,
    thumbnail,
)

HANIME1_HOME = "https://hanime1.me/"
HANIME1_DOWNLOAD_URL = "https://hanime1.me/download?v={}"
HANIME1_HOSTS = frozenset({"hanime1.me", "www.hanime1.me"})


def hanime_sources(soup: BeautifulSoup) -> list[tuple[str, int | None]]:
    result: list[tuple[str, int | None]] = []
    seen: set[str] = set()

    def add(raw: object, label: str = "") -> None:
        url = html.unescape(str(raw or "").strip()).replace("\\/", "/")
        parsed = urlsplit(url)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or not parsed.path.lower().endswith(MP4_SUFFIX)
        ):
            return
        if url not in seen:
            seen.add(url)
            result.append((url, media_height(f"{label} {url}")))

    for element in soup.select("source[src], a[data-url], a[href]"):
        add(
            element.get("src") or element.get("data-url") or element.get("href"),
            element.get_text(" ", strip=True),
        )
    for url in absolute_media_matches(str(soup), "mp4"):
        add(url)
    return result


class Hanime1Extractor(Extractor):
    site = "hanime1"

    @classmethod
    def supports(cls, url: str) -> bool:
        parsed = urlsplit(url)
        values = parse_qs(parsed.query).get("v", [])
        return (
            (parsed.hostname or "").lower() in HANIME1_HOSTS
            and parsed.path == "/watch"
            and len(values) == 1
            and values[0].isdigit()
        )

    def extract(self, url: str, client: HttpClient, quality: Quality) -> MediaSource:
        video_id = parse_qs(urlsplit(url).query)["v"][0]
        home = client.get(
            HANIME1_HOME,
            headers={"Referer": HANIME1_HOME},
            timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        if is_blocked(home):
            raise AccessBlockedError("Hanime1 首页被 Cloudflare 阻止")
        if status_code(home) != HTTP_OK:
            raise ExtractionError(f"Hanime1 初始化失败 (HTTP {status_code(home)})")
        response = client.get(
            url,
            headers={"Referer": HANIME1_HOME},
            timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        if is_blocked(response):
            raise AccessBlockedError("Hanime1 视频页被 Cloudflare 阻止")
        if status_code(response) != HTTP_OK:
            raise ExtractionError(f"Hanime1 视频页读取失败 (HTTP {status_code(response)})")
        soup = BeautifulSoup(response.content, "html.parser")
        sources = hanime_sources(soup)
        if not sources:
            download_url = HANIME1_DOWNLOAD_URL.format(video_id)
            extra = client.get(
                download_url,
                headers={"Referer": url},
                timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            )
            if status_code(extra) == HTTP_OK and not is_blocked(extra):
                sources = hanime_sources(BeautifulSoup(extra.content, "html.parser"))
        selected = choose_by_quality(sources, quality)
        if not selected:
            raise ExtractionError("Hanime1 当前没有可用的签名 MP4 来源")
        title = re.sub(r"\s+-\s+Hanime1\.me\s*$", "", page_title(soup), flags=re.I)
        if not title:
            raise ExtractionError("Hanime1 页面标题解析失败")
        return MediaSource(
            page_url=url,
            media_url=selected,
            kind="direct",
            title=title,
            media_id=video_id,
            site=self.site,
            thumbnail_url=thumbnail(soup, url),
            headers={"Referer": url},
        )
