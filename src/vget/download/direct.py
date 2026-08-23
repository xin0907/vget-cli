"""Resumable direct-file downloader.

The Range-download design was adapted and modified from ALOS/UAV Downloader
(Apache-2.0). See NOTICE.
"""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import threading
import time
from contextlib import suppress
from pathlib import Path

from vget.constants import (
    BYTES_PER_KIBIBYTE,
    FILE_COPY_BUFFER_BYTES,
    HTTP_OK,
    HTTP_PARTIAL_CONTENT,
    HTTP_RANGE_HEADER,
    HTTP_RANGE_UNIT,
    MAX_RETRY_DELAY_SECONDS,
    TEMPORARY_MP4_SUFFIX,
)
from vget.errors import DownloadError
from vget.http import HttpClient
from vget.models import DownloadOptions, MediaSource

from .common import (
    Progress,
    ensure_parent,
    parse_content_range,
    part_root,
    remove_empty_parent,
    split_ranges,
)

CONTENT_LENGTH_HEADER = "content-length"
CONTENT_RANGE_HEADER = "content-range"
DIRECT_DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_SIZE_BYTES = 256 * BYTES_PER_KIBIBYTE
MAX_PARALLEL_RANGES = 4
MIN_PARALLEL_DOWNLOAD_BYTES = FILE_COPY_BUFFER_BYTES
RANGE_PROBE_TIMEOUT_SECONDS = 45
RANGE_PART_NAME = "range-{index:02d}.part"
SERIAL_PART_NAME = "direct-serial.part"
STAGING_FILE_NAME = "direct-complete.bin"


def range_part_path(parts: Path, index: int) -> Path:
    return parts / RANGE_PART_NAME.format(index=index)


class DirectDownloader:
    def __init__(self, client: HttpClient, options: DownloadOptions) -> None:
        self.client = client
        self.options = options

    def download(self, source: MediaSource, destination: Path) -> Path:
        ensure_parent(destination)
        if destination.exists() and not self.options.overwrite:
            print(f"已存在，跳过：{destination.name}")
            return destination
        parts = part_root(destination)
        parts.mkdir(parents=True, exist_ok=True)
        progress = Progress("下载")

        total = self._probe_range(source)
        published = False
        try:
            if total and self.options.workers > 1 and total >= MIN_PARALLEL_DOWNLOAD_BYTES:
                try:
                    staging = self._parallel(source, parts, total, progress)
                except Exception as exc:
                    if self.options.verbose:
                        print(f"\n并行分段不可用，改为单连接续传：{exc}")
                    staging = self._serial(source, parts, progress)
            else:
                staging = self._serial(source, parts, progress)
            Progress.finish()
            temporary = destination.with_name(destination.name + TEMPORARY_MP4_SUFFIX)
            shutil.copyfile(staging, temporary)
            if temporary.stat().st_size <= 0:
                raise DownloadError("下载结果为空")
            os.replace(temporary, destination)
            published = True
            print(f"完成：{destination}")
            return destination
        finally:
            if published and not self.options.keep_parts:
                shutil.rmtree(parts, ignore_errors=True)
                remove_empty_parent(parts.parent)

    def _probe_range(self, source: MediaSource) -> int | None:
        response = None
        try:
            response = self.client.get(
                source.media_url,
                headers={**source.headers, HTTP_RANGE_HEADER: f"{HTTP_RANGE_UNIT}=0-0"},
                timeout=RANGE_PROBE_TIMEOUT_SECONDS,
                stream=True,
            )
            parsed = parse_content_range(getattr(response, "headers", {}).get(CONTENT_RANGE_HEADER))
            if (
                getattr(response, "status_code", 0) == HTTP_PARTIAL_CONTENT
                and parsed
                and parsed[:2] == (0, 0)
            ):
                return parsed[2]
            return None
        except Exception:
            return None
        finally:
            if response is not None:
                with suppress(Exception):
                    response.close()

    def _parallel(self, source: MediaSource, parts: Path, total: int, progress: Progress) -> Path:
        ranges = split_ranges(total, min(self.options.workers, MAX_PARALLEL_RANGES))
        progress_lock = threading.Lock()
        current = sum(
            min(range_part_path(parts, index).stat().st_size, end - start + 1)
            if range_part_path(parts, index).exists()
            else 0
            for index, (start, end) in enumerate(ranges)
        )
        progress.bytes(current, total)

        def fetch(index_and_bounds: tuple[int, tuple[int, int]]) -> None:
            nonlocal current
            index, (start, end) = index_and_bounds
            path = range_part_path(parts, index)
            expected = end - start + 1
            existing = path.stat().st_size if path.exists() else 0
            if existing > expected:
                path.unlink()
                existing = 0
            if existing == expected:
                return
            attempts = 0
            while existing < expected:
                cursor = start + existing
                response = None
                try:
                    response = self.client.get(
                        source.media_url,
                        headers={
                            **source.headers,
                            HTTP_RANGE_HEADER: f"{HTTP_RANGE_UNIT}={cursor}-{end}",
                        },
                        timeout=DIRECT_DOWNLOAD_TIMEOUT_SECONDS,
                        stream=True,
                    )
                    parsed = parse_content_range(
                        getattr(response, "headers", {}).get(CONTENT_RANGE_HEADER)
                    )
                    if getattr(response, "status_code", 0) != HTTP_PARTIAL_CONTENT or parsed != (
                        cursor,
                        end,
                        total,
                    ):
                        raise DownloadError("服务器没有正确响应 HTTP Range 请求")
                    with path.open("ab") as handle:
                        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE_BYTES):
                            if not chunk:
                                continue
                            if existing + len(chunk) > expected:
                                raise DownloadError("服务器返回的分段长度超出预期")
                            handle.write(chunk)
                            existing += len(chunk)
                            with progress_lock:
                                current += len(chunk)
                                progress.bytes(current, total)
                    if existing < expected:
                        raise DownloadError("HTTP Range 连接提前结束")
                except Exception:
                    attempts += 1
                    if attempts > self.options.retries:
                        raise
                    time.sleep(min(attempts, MAX_RETRY_DELAY_SECONDS))
                finally:
                    if response is not None:
                        with suppress(Exception):
                            response.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ranges)) as executor:
            futures = [executor.submit(fetch, item) for item in enumerate(ranges)]
            for future in concurrent.futures.as_completed(futures):
                future.result()

        staging = parts / STAGING_FILE_NAME
        with staging.open("wb") as output:
            for index, (start, end) in enumerate(ranges):
                part = range_part_path(parts, index)
                if not part.exists() or part.stat().st_size != end - start + 1:
                    raise DownloadError("并行下载分段不完整")
                with part.open("rb") as source_file:
                    shutil.copyfileobj(source_file, output, FILE_COPY_BUFFER_BYTES)
        if staging.stat().st_size != total:
            raise DownloadError("合并后的直接下载文件长度不正确")
        return staging

    def _serial(self, source: MediaSource, parts: Path, progress: Progress) -> Path:
        staging = parts / SERIAL_PART_NAME
        attempts = 0
        while True:
            done = staging.stat().st_size if staging.exists() else 0
            headers = dict(source.headers)
            if done:
                headers[HTTP_RANGE_HEADER] = f"{HTTP_RANGE_UNIT}={done}-"
            response = None
            try:
                response = self.client.get(
                    source.media_url,
                    headers=headers,
                    timeout=DIRECT_DOWNLOAD_TIMEOUT_SECONDS,
                    stream=True,
                )
                status = int(getattr(response, "status_code", 0) or 0)
                parsed = parse_content_range(
                    getattr(response, "headers", {}).get(CONTENT_RANGE_HEADER)
                )
                if done and status == HTTP_PARTIAL_CONTENT and parsed and parsed[0] == done:
                    total = parsed[2]
                    mode = "ab"
                elif status == HTTP_OK:
                    done = 0
                    mode = "wb"
                    try:
                        total = int(
                            getattr(response, "headers", {}).get(CONTENT_LENGTH_HEADER) or 0
                        )
                    except (TypeError, ValueError):
                        total = 0
                elif status == HTTP_PARTIAL_CONTENT and parsed:
                    done = parsed[0]
                    total = parsed[2]
                    mode = "ab" if done else "wb"
                else:
                    raise DownloadError(f"直接下载失败 (HTTP {status})")
                received = 0
                with staging.open(mode) as output:
                    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE_BYTES):
                        if not chunk:
                            continue
                        output.write(chunk)
                        received += len(chunk)
                        done += len(chunk)
                        progress.bytes(done, total or None)
                if total and done < total:
                    raise DownloadError("连接提前结束")
                if done <= 0 or (not total and received <= 0):
                    raise DownloadError("服务器没有返回媒体内容")
                return staging
            except Exception:
                attempts += 1
                if attempts > self.options.retries:
                    raise
                time.sleep(min(attempts, MAX_RETRY_DELAY_SECONDS))
            finally:
                if response is not None:
                    with suppress(Exception):
                        response.close()
