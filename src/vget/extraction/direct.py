"""Extractor for direct MP4 and M3U8 URLs."""

from urllib.parse import unquote, urlsplit

from vget.constants import M3U8_SUFFIX, MP4_SUFFIX
from vget.http import HttpClient
from vget.models import MediaSource, Quality

from .base import Extractor


class DirectMediaExtractor(Extractor):
    site = "direct"

    @classmethod
    def supports(cls, url: str) -> bool:
        return urlsplit(url).path.lower().endswith((M3U8_SUFFIX, MP4_SUFFIX))

    def extract(self, url: str, client: HttpClient, quality: Quality) -> MediaSource:
        path = urlsplit(url).path
        filename = unquote(path.rsplit("/", 1)[-1]) or "video"
        stem = filename.rsplit(".", 1)[0] or "video"
        return MediaSource(
            page_url=url,
            media_url=url,
            kind="hls" if path.lower().endswith(M3U8_SUFFIX) else "direct",
            title=stem,
            media_id=stem,
            site=self.site,
        )
