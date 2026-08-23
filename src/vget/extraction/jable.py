"""JableTV extractor adapted and modified from ALOS/UAV Downloader.

Licensed under Apache-2.0. See NOTICE.
"""

import re

from bs4 import BeautifulSoup

from vget.constants import M3U8_SUFFIX
from vget.errors import ExtractionError
from vget.http import HttpClient
from vget.models import MediaSource, Quality

from .base import (
    Extractor,
    absolute_media_matches,
    fetch_with_mirrors,
    origin,
    page_title,
    response_url,
    thumbnail,
)

LANGUAGE_COOKIE_DOMAINS = (".jable.tv", ".fs1.app")


class JableExtractor(Extractor):
    site = "jable"
    _pattern = re.compile(r"https://(?:www\.)?(?:jable\.tv|fs1\.app)/videos/([^/?#]+)/?", re.I)

    @classmethod
    def supports(cls, url: str) -> bool:
        return bool(cls._pattern.fullmatch(url))

    def extract(self, url: str, client: HttpClient, quality: Quality) -> MediaSource:
        match = self._pattern.fullmatch(url)
        assert match
        for domain in LANGUAGE_COOKIE_DOMAINS:
            client.set_cookie("kt_rt_lang", "", domain=domain)
        response, _ = fetch_with_mirrors(
            client,
            url,
            "jable",
            lambda item: "og:title" in item.text and M3U8_SUFFIX in item.text,
        )
        actual_url = response_url(response, url)
        soup = BeautifulSoup(response.content, "html.parser")
        streams = absolute_media_matches(response.text, "m3u8")
        if not streams:
            raise ExtractionError("Jable 页面没有暴露 M3U8 地址")
        title = page_title(soup)
        if not title:
            raise ExtractionError("Jable 页面标题解析失败")
        return MediaSource(
            page_url=url,
            media_url=streams[0],
            kind="hls",
            title=title,
            media_id=match.group(1),
            site=self.site,
            thumbnail_url=thumbnail(soup, actual_url),
            headers={"Referer": actual_url, "Origin": origin(actual_url)},
        )
