"""Best-effort extractor for media URLs exposed in ordinary HTML."""

from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from vget.constants import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    HTTP_OK,
    HTTP_SCHEMES,
    M3U8_SUFFIX,
    MP4_SUFFIX,
)
from vget.errors import AccessBlockedError, ExtractionError, UnsupportedUrlError
from vget.http import HttpClient
from vget.models import MediaSource, Quality

from .base import (
    Extractor,
    absolute_media_matches,
    choose_by_quality,
    is_blocked,
    media_height,
    origin,
    page_title,
    response_url,
    status_code,
    thumbnail,
)


class GenericPageExtractor(Extractor):
    site = "generic"

    @classmethod
    def supports(cls, url: str) -> bool:
        return urlsplit(url).scheme.lower() in HTTP_SCHEMES

    def extract(self, url: str, client: HttpClient, quality: Quality) -> MediaSource:
        response = client.get(
            url,
            headers={"Referer": origin(url) + "/"},
            timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        if is_blocked(response):
            raise AccessBlockedError("网页返回了 Cloudflare/反机器人拦截页")
        if status_code(response) != HTTP_OK:
            raise ExtractionError(f"网页请求失败 (HTTP {status_code(response)})")
        actual = response_url(response, url)
        soup = BeautifulSoup(response.content, "html.parser")
        candidates: list[tuple[str, int | None, str]] = []
        for element in soup.select("video[src], source[src], a[href]"):
            raw = element.get("src") or element.get("href")
            media_url = urljoin(actual, str(raw or ""))
            path = urlsplit(media_url).path.lower()
            if path.endswith(M3U8_SUFFIX):
                candidates.append((media_url, media_height(str(element)), "hls"))
            elif path.endswith(MP4_SUFFIX):
                candidates.append((media_url, media_height(str(element)), "direct"))
        for media_url in absolute_media_matches(response.text, "m3u8"):
            candidates.append((media_url, media_height(media_url), "hls"))
        for media_url in absolute_media_matches(response.text, "mp4"):
            candidates.append((media_url, media_height(media_url), "direct"))
        unique = {item[0]: item for item in candidates}
        items = list(unique.values())
        if not items:
            raise UnsupportedUrlError("该网页不是已适配站点，且 HTML 中没有找到 MP4/M3U8 地址")
        chosen_url = choose_by_quality([(item[0], item[1]) for item in items], quality)
        chosen = next(item for item in items if item[0] == chosen_url)
        slug = urlsplit(actual).path.rstrip("/").rsplit("/", 1)[-1] or "video"
        return MediaSource(
            page_url=url,
            media_url=chosen[0],
            kind=chosen[2],  # type: ignore[arg-type]
            title=page_title(soup) or slug,
            media_id=slug,
            site=self.site,
            thumbnail_url=thumbnail(soup, actual),
            headers={"Referer": actual, "Origin": origin(actual)},
        )
