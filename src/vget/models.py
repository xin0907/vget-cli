from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .constants import DEFAULT_NAME_TEMPLATE, DEFAULT_RETRIES, DEFAULT_WORKERS

MediaKind = Literal["hls", "direct"]
Quality = Literal["highest", "1080", "720", "480", "360", "lowest"]


@dataclass(slots=True)
class MediaSource:
    """A fully resolved media source returned by a site extractor."""

    page_url: str
    media_url: str
    kind: MediaKind
    title: str
    media_id: str
    site: str
    thumbnail_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    segment_transform: str | None = None
    fallback: MediaSource | None = None

    def public_info(self) -> dict[str, object]:
        result: dict[str, object] = {
            "site": self.site,
            "id": self.media_id,
            "title": self.title,
            "type": self.kind,
            "page_url": self.page_url,
            "media_url": self.media_url,
            "thumbnail_url": self.thumbnail_url,
        }
        if self.fallback:
            result["fallback"] = {
                "type": self.fallback.kind,
                "media_url": self.fallback.media_url,
            }
        return result


@dataclass(slots=True, frozen=True)
class DownloadOptions:
    output_dir: str
    quality: Quality = "highest"
    workers: int = DEFAULT_WORKERS
    retries: int = DEFAULT_RETRIES
    overwrite: bool = False
    keep_parts: bool = False
    download_thumbnail: bool = False
    name_template: str = DEFAULT_NAME_TEMPLATE
    referer: str | None = None
    verbose: bool = False
