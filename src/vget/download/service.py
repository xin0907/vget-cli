"""High-level download orchestration."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from vget.constants import DEFAULT_REQUEST_TIMEOUT_SECONDS, HTTP_OK
from vget.http import HttpClient
from vget.models import DownloadOptions, MediaSource

from .common import output_path
from .direct import DirectDownloader
from .hls import HLSDownloader

THUMBNAIL_SUFFIX = ".jpg"
THUMBNAIL_TEMPORARY_SUFFIX = ".jpg.part"


def download_thumbnail(client: HttpClient, source: MediaSource, destination: Path) -> Path | None:
    if not source.thumbnail_url:
        return None
    target = destination.with_suffix(THUMBNAIL_SUFFIX)
    if target.exists():
        return target
    try:
        response = client.get(
            source.thumbnail_url,
            headers=source.headers,
            timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        if int(getattr(response, "status_code", 0) or 0) != HTTP_OK:
            return None
        data = bytes(getattr(response, "content", b"") or b"")
        if not data:
            return None
        temporary = target.with_suffix(THUMBNAIL_TEMPORARY_SUFFIX)
        temporary.write_bytes(data)
        os.replace(temporary, target)
        return target
    except Exception:
        return None


def _with_referer(source: MediaSource, referer: str | None) -> MediaSource:
    if not referer:
        return source
    return replace(source, headers={**source.headers, "Referer": referer})


def download_media(client: HttpClient, source: MediaSource, options: DownloadOptions) -> Path:
    destination = output_path(source, options)
    effective_source = _with_referer(source, options.referer)
    try:
        if effective_source.kind == "hls":
            result = HLSDownloader(client, options).download(effective_source, destination)
        else:
            result = DirectDownloader(client, options).download(effective_source, destination)
    except Exception as first_error:
        if not effective_source.fallback:
            raise
        print(f"主来源失败，尝试备用直链：{first_error}")
        fallback = _with_referer(effective_source.fallback, options.referer)
        result = DirectDownloader(client, options).download(fallback, destination)
    if options.download_thumbnail:
        download_thumbnail(client, source, result)
    return result
