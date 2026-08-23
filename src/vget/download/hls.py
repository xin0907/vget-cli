"""Concurrent, resumable HLS downloader and MP4 remuxer.

The design is derived from ALOS/UAV Downloader (Apache-2.0), commit
d6fda487ddc5967dfd32dcca8b89966e277a398f. See NOTICE and LICENSE.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import m3u8
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from vget.constants import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    FILE_COPY_BUFFER_BYTES,
    HTTP_OK,
    HTTP_PARTIAL_CONTENT,
    HTTP_RANGE_HEADER,
    HTTP_RANGE_UNIT,
    MAX_RETRY_DELAY_SECONDS,
    RESOLUTION_QUALITIES,
    SEGMENT_TRANSFORM_SUPJAV_FAKE_PNG,
    TEMPORARY_MP4_SUFFIX,
)
from vget.errors import DownloadError, UnsupportedEncryptionError
from vget.http import HttpClient
from vget.models import DownloadOptions, MediaSource, Quality

from .common import (
    Progress,
    ensure_parent,
    locate_ffmpeg,
    no_window_kwargs,
    part_root,
    remove_empty_parent,
)

FFMPEG_ERROR_TAIL_CHARACTERS = 1200
FFMPEG_TIMEOUT_SECONDS = 3600
HLS_RESOURCE_TIMEOUT_SECONDS = 45
HLS_KEY_METHOD_AES_128 = "AES-128"
HLS_KEY_METHOD_NONE = "NONE"
MANIFEST_HEADER = "#EXTM3U"
MAX_MANIFEST_DEPTH = 5
MERGED_MEDIA_FILE_NAME = "merged-media.bin"
MPEG_TS_PACKET_SIZE_BYTES = 188
MPEG_TS_SYNC_BYTE = 0x47
MPEG_TS_VALIDATION_PACKET_COUNT = 5
PLAN_FINGERPRINT_LENGTH = 16
RESOLUTION_DIMENSION_COUNT = 2
SEGMENT_FILE_NAME = "{index:06d}.segment"
SEGMENT_TEMPORARY_SUFFIX = ".tmp"
SUPJAV_HEADER_SCAN_LIMIT_BYTES = 8000


def segment_path(parts: Path, index: int) -> Path:
    return parts / SEGMENT_FILE_NAME.format(index=index)


@dataclass(slots=True, frozen=True)
class ByteRange:
    start: int
    end: int


@dataclass(slots=True, frozen=True)
class InitSpec:
    url: str
    byte_range: ByteRange | None = None


@dataclass(slots=True, frozen=True)
class SegmentSpec:
    index: int
    sequence: int
    url: str
    byte_range: ByteRange | None
    key_method: str | None
    key_url: str | None
    key_iv: str | None
    init: InitSpec | None


def parse_byte_range(
    value: object, previous_end: int | None
) -> tuple[ByteRange | None, int | None]:
    if not value:
        return None, previous_end
    match = re.fullmatch(r"(\d+)(?:@(\d+))?", str(value).strip())
    if not match:
        raise DownloadError(f"无效的 HLS BYTERANGE：{value}")
    length = int(match.group(1))
    start = int(match.group(2)) if match.group(2) is not None else (previous_end or 0)
    result = ByteRange(start, start + length - 1)
    return result, result.end + 1


def _variant_details(playlist: object) -> tuple[int | None, int]:
    info = getattr(playlist, "stream_info", None)
    resolution = getattr(info, "resolution", None) if info else None
    height = None
    if isinstance(resolution, (tuple, list)) and len(resolution) == RESOLUTION_DIMENSION_COUNT:
        with suppress(TypeError, ValueError):
            height = int(resolution[1])
    try:
        bandwidth = int(getattr(info, "bandwidth", 0) or 0) if info else 0
    except (TypeError, ValueError):
        bandwidth = 0
    return height, bandwidth


def select_variant(playlists: list[object], quality: Quality):
    items = [(item, *_variant_details(item)) for item in playlists]
    if not items:
        return None
    known = [item for item in items if item[1] is not None]
    if quality == "lowest":
        if known:
            return min(known, key=lambda item: (item[1], item[2]))[0]
        return min(items, key=lambda item: item[2])[0]
    if quality in RESOLUTION_QUALITIES:
        if not known:
            return max(items, key=lambda item: item[2])[0]
        target = int(quality)
        at_or_below = [item for item in known if (item[1] or 0) <= target]
        if at_or_below:
            return max(at_or_below, key=lambda item: (item[1], item[2]))[0]
        return min(known, key=lambda item: (item[1], -item[2]))[0]
    if known:
        return max(known, key=lambda item: (item[1], item[2]))[0]
    return max(items, key=lambda item: item[2])[0]


def strip_supjav_fake_header(data: bytes) -> bytes:
    sync_byte = bytes((MPEG_TS_SYNC_BYTE,))
    if data[:1] == sync_byte:
        return data
    validation_span = MPEG_TS_PACKET_SIZE_BYTES * (MPEG_TS_VALIDATION_PACKET_COUNT - 1)
    limit = min(len(data) - validation_span - 1, SUPJAV_HEADER_SCAN_LIMIT_BYTES)
    cursor = 0
    while 0 <= cursor <= limit:
        found = data.find(sync_byte, cursor)
        if found < 0 or found > limit:
            break
        if all(
            data[found + MPEG_TS_PACKET_SIZE_BYTES * offset] == MPEG_TS_SYNC_BYTE
            for offset in range(MPEG_TS_VALIDATION_PACKET_COUNT)
        ):
            return data[found:]
        cursor = found + 1
    return b""


class HLSDownloader:
    def __init__(self, client: HttpClient, options: DownloadOptions) -> None:
        self.client = client
        self.options = options
        self._key_cache: dict[str, bytes] = {}
        self._key_lock = threading.Lock()

    def download(self, source: MediaSource, destination: Path) -> Path:
        ensure_parent(destination)
        if destination.exists() and not self.options.overwrite:
            print(f"已存在，跳过：{destination.name}")
            return destination
        media_url, manifest = self._resolve_media_playlist(source)
        specs = self._segment_specs(media_url, manifest)
        fingerprint = self._fingerprint(specs)
        parts = part_root(destination) / fingerprint
        parts.mkdir(parents=True, exist_ok=True)
        completed = {
            item.index
            for item in specs
            if segment_path(parts, item.index).is_file()
            and segment_path(parts, item.index).stat().st_size > 0
        }
        downloaded_bytes = sum(segment_path(parts, index).stat().st_size for index in completed)
        progress = Progress("HLS 下载")
        progress.segments(len(completed), len(specs), downloaded_bytes)
        state_lock = threading.Lock()

        def fetch(spec: SegmentSpec) -> None:
            nonlocal downloaded_bytes
            target = segment_path(parts, spec.index)
            if spec.index in completed:
                return
            data = self._download_segment(source, spec)
            temporary = target.with_suffix(SEGMENT_TEMPORARY_SUFFIX)
            temporary.write_bytes(data)
            os.replace(temporary, target)
            with state_lock:
                completed.add(spec.index)
                downloaded_bytes += len(data)
                progress.segments(len(completed), len(specs), downloaded_bytes)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.options.workers) as executor:
            futures = [
                executor.submit(fetch, spec) for spec in specs if spec.index not in completed
            ]
            for future in concurrent.futures.as_completed(futures):
                future.result()
        Progress.finish()
        if len(completed) != len(specs):
            raise DownloadError(f"HLS 下载不完整：{len(completed)}/{len(specs)}")

        published = False
        try:
            print("正在合并并生成 MP4...")
            merged = self._merge_segments(source, specs, parts)
            self._remux(merged, destination)
            published = True
            print(f"完成：{destination}")
            return destination
        finally:
            if published and not self.options.keep_parts:
                root = part_root(destination)
                shutil.rmtree(root, ignore_errors=True)
                remove_empty_parent(root.parent)

    @staticmethod
    def _fingerprint(specs: list[SegmentSpec]) -> str:
        plan = [
            {
                "url": item.url,
                "range": (
                    (item.byte_range.start, item.byte_range.end) if item.byte_range else None
                ),
                "key": item.key_url,
                "iv": item.key_iv,
            }
            for item in specs
        ]
        return hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest()[
            :PLAN_FINGERPRINT_LENGTH
        ]

    def _load_manifest(self, url: str, headers: dict[str, str]):
        response = self.client.get(
            url,
            headers=headers,
            timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        status = int(getattr(response, "status_code", 0) or 0)
        text = str(getattr(response, "text", "") or "")
        if status != HTTP_OK:
            raise DownloadError(f"M3U8 请求失败 (HTTP {status})：{url}")
        if MANIFEST_HEADER not in text:
            raise DownloadError("来源返回的不是有效 M3U8，可能已过期或被拦截")
        actual = str(getattr(response, "url", "") or url)
        return actual, m3u8.loads(text, uri=actual)

    def _resolve_media_playlist(self, source: MediaSource):
        current = source.media_url
        for _ in range(MAX_MANIFEST_DEPTH):
            actual, manifest = self._load_manifest(current, source.headers)
            playlists = list(getattr(manifest, "playlists", []) or [])
            if not playlists:
                return actual, manifest
            selected = select_variant(playlists, self.options.quality)
            if selected is None:
                raise DownloadError("主播放列表没有可用画质")
            current = urljoin(actual, selected.uri)
        raise DownloadError("M3U8 主播放列表嵌套层数异常")

    def _segment_specs(self, media_url: str, manifest) -> list[SegmentSpec]:
        specs: list[SegmentSpec] = []
        previous_range_end: int | None = None
        previous_init_end: int | None = None
        base_sequence = int(getattr(manifest, "media_sequence", 0) or 0)
        for index, segment in enumerate(manifest.segments):
            byte_range, previous_range_end = parse_byte_range(
                getattr(segment, "byterange", None), previous_range_end
            )
            key = getattr(segment, "key", None)
            method = str(getattr(key, "method", "") or "").upper() or None
            if method == HLS_KEY_METHOD_NONE:
                method = None
            if method and method != HLS_KEY_METHOD_AES_128:
                raise UnsupportedEncryptionError(
                    f"HLS 使用不支持的加密方式 {method}；vget 不绕过 DRM/SAMPLE-AES"
                )
            key_uri = getattr(key, "uri", None) if key else None
            key_url = urljoin(media_url, key_uri) if key_uri else None
            init = None
            init_section = getattr(segment, "init_section", None)
            if init_section and getattr(init_section, "uri", None):
                init_range, previous_init_end = parse_byte_range(
                    getattr(init_section, "byterange", None), previous_init_end
                )
                init = InitSpec(urljoin(media_url, init_section.uri), init_range)
            specs.append(
                SegmentSpec(
                    index=index,
                    sequence=base_sequence + index,
                    url=urljoin(media_url, segment.uri),
                    byte_range=byte_range,
                    key_method=method,
                    key_url=key_url,
                    key_iv=getattr(key, "iv", None) if key else None,
                    init=init,
                )
            )
        if not specs:
            raise DownloadError("媒体播放列表不包含任何分片")
        return specs

    def _request_bytes(
        self,
        url: str,
        headers: dict[str, str],
        byte_range: ByteRange | None = None,
    ) -> bytes:
        request_headers = dict(headers)
        if byte_range:
            request_headers[HTTP_RANGE_HEADER] = (
                f"{HTTP_RANGE_UNIT}={byte_range.start}-{byte_range.end}"
            )
        last_error: Exception | None = None
        for attempt in range(self.options.retries + 1):
            try:
                response = self.client.get(
                    url,
                    headers=request_headers,
                    timeout=HLS_RESOURCE_TIMEOUT_SECONDS,
                )
                status = int(getattr(response, "status_code", 0) or 0)
                if byte_range and status != HTTP_PARTIAL_CONTENT:
                    raise DownloadError(f"HLS 分片未正确响应 BYTERANGE (HTTP {status})")
                if not byte_range and status != HTTP_OK:
                    raise DownloadError(f"HLS 资源请求失败 (HTTP {status})")
                data = bytes(getattr(response, "content", b"") or b"")
                if not data:
                    raise DownloadError("HLS 资源内容为空")
                if byte_range and len(data) != byte_range.end - byte_range.start + 1:
                    raise DownloadError("HLS BYTERANGE 返回长度不正确")
                return data
            except Exception as exc:
                last_error = exc
                if attempt < self.options.retries:
                    time.sleep(min(attempt + 1, MAX_RETRY_DELAY_SECONDS))
        raise DownloadError(f"HLS 资源多次重试仍失败：{url} ({last_error})")

    def _key(self, source: MediaSource, url: str) -> bytes:
        with self._key_lock:
            cached = self._key_cache.get(url)
        if cached is not None:
            return cached
        key = self._request_bytes(url, source.headers)
        if len(key) != AES.block_size:
            raise DownloadError(f"AES-128 密钥长度错误：{len(key)} bytes")
        with self._key_lock:
            self._key_cache[url] = key
        return key

    def _download_segment(self, source: MediaSource, spec: SegmentSpec) -> bytes:
        data = self._request_bytes(spec.url, source.headers, spec.byte_range)
        if source.segment_transform == SEGMENT_TRANSFORM_SUPJAV_FAKE_PNG:
            data = strip_supjav_fake_header(data)
            if not data:
                raise DownloadError(f"SupJav 分片 {spec.index} 的伪装头无法识别")
        if spec.key_method == HLS_KEY_METHOD_AES_128:
            if not spec.key_url:
                raise DownloadError("AES-128 分片缺少密钥 URL")
            if len(data) % AES.block_size:
                raise DownloadError(f"加密分片 {spec.index} 长度不是 AES block 的整数倍")
            iv = self._iv(spec.key_iv, spec.sequence)
            data = AES.new(self._key(source, spec.key_url), AES.MODE_CBC, iv).decrypt(data)
            with suppress(ValueError):
                data = unpad(data, AES.block_size)
        if not data:
            raise DownloadError(f"分片 {spec.index} 解码后为空")
        return data

    @staticmethod
    def _iv(raw: str | None, sequence: int) -> bytes:
        if not raw:
            return sequence.to_bytes(AES.block_size, "big")
        cleaned = str(raw).strip().lower()
        if cleaned.startswith("0x"):
            cleaned = cleaned[2:]
        try:
            value = bytes.fromhex(cleaned.zfill(AES.block_size * 2))
        except ValueError as exc:
            raise DownloadError(f"无效的 HLS AES IV：{raw}") from exc
        if len(value) != AES.block_size:
            raise DownloadError(f"HLS AES IV 必须是 {AES.block_size} bytes：{raw}")
        return value

    def _merge_segments(self, source: MediaSource, specs: list[SegmentSpec], parts: Path) -> Path:
        merged = parts / MERGED_MEDIA_FILE_NAME
        init_cache: dict[InitSpec, bytes] = {}
        last_init: InitSpec | None = None
        with merged.open("wb") as output:
            for spec in specs:
                if spec.init and spec.init != last_init:
                    init_data = init_cache.get(spec.init)
                    if init_data is None:
                        init_data = self._request_bytes(
                            spec.init.url, source.headers, spec.init.byte_range
                        )
                        init_cache[spec.init] = init_data
                    output.write(init_data)
                    last_init = spec.init
                current_segment = segment_path(parts, spec.index)
                if not current_segment.is_file():
                    raise DownloadError(f"合并时缺少分片 {spec.index}")
                with current_segment.open("rb") as segment_file:
                    shutil.copyfileobj(segment_file, output, FILE_COPY_BUFFER_BYTES)
        if merged.stat().st_size <= 0:
            raise DownloadError("合并后的媒体文件为空")
        return merged

    def _remux(self, merged: Path, destination: Path) -> None:
        ffmpeg = locate_ffmpeg()
        if not ffmpeg:
            raise DownloadError("找不到 FFmpeg，无法把 HLS 分片封装为 MP4")
        temporary = destination.with_name(destination.name + TEMPORARY_MP4_SUFFIX)
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        command = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "+genpts",
            "-i",
            str(merged),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            "-f",
            "mp4",
            str(temporary),
        ]
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            **no_window_kwargs(),
        )
        if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 0:
            message = result.stderr.decode("utf-8", errors="replace")[
                -FFMPEG_ERROR_TAIL_CHARACTERS:
            ]
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise DownloadError(f"FFmpeg 封装失败：{message.strip()}")
        os.replace(temporary, destination)
