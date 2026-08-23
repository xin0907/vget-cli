"""Shared filesystem, progress, and process helpers for downloaders.

Portions adapted and modified from ALOS/UAV Downloader (Apache-2.0). See NOTICE.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import shutil
import threading
import time
from contextlib import suppress
from pathlib import Path

from vget.constants import BYTES_PER_KIBIBYTE, HTTP_RANGE_UNIT, MP4_SUFFIX
from vget.errors import DownloadError
from vget.models import DownloadOptions, MediaSource

_WINDOWS_FILENAME_TRANSLATION = str.maketrans(
    {
        "<": "＜",
        ">": "＞",
        ":": "：",
        '"': "＂",
        "/": "／",
        "\\": "＼",
        "|": "｜",
        "?": "？",
        "*": "＊",
    }
)
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
DEFAULT_PROGRESS_BAR_WIDTH = 24
FILENAME_PREFIX_BUDGET_BYTES = 210
HUMAN_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")
MAX_FILENAME_BYTES = 220
MIN_ELAPSED_SECONDS = 0.001
PARTS_DIRECTORY_NAME = ".vget-parts"
PART_PATH_STEM_LENGTH = 50
PATH_DIGEST_LENGTH = 12
PROGRESS_REFRESH_INTERVAL_SECONDS = 0.12
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60
WINDOWS_NO_WINDOW_FLAG = 0x08000000


def sanitize_filename(value: object) -> str:
    name = html.unescape(str(value or ""))
    name = re.sub(r"[\x00-\x1f\x7f]", " ", name)
    name = name.translate(_WINDOWS_FILENAME_TRANSLATION).strip()
    trailing = len(name) - len(name.rstrip("."))
    if trailing:
        name = name[:-trailing] + "．" * trailing
    stem = name.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        name = "_" + name
    return name or "video"


def output_path(source: MediaSource, options: DownloadOptions) -> Path:
    values = {
        "title": sanitize_filename(source.title),
        "id": sanitize_filename(source.media_id),
        "site": sanitize_filename(source.site),
        "ext": MP4_SUFFIX.removeprefix("."),
    }
    try:
        rendered = options.name_template.format(**values)
    except (KeyError, ValueError) as exc:
        raise DownloadError(f"文件名模板无效：{exc}") from exc
    filename = sanitize_filename(rendered)
    if not filename.lower().endswith(MP4_SUFFIX):
        filename += MP4_SUFFIX
    if len(filename.encode("utf-8")) > MAX_FILENAME_BYTES:
        suffix = f" [{values['id']}]{MP4_SUFFIX}"
        limit = max(1, FILENAME_PREFIX_BUDGET_BYTES - len(suffix.encode("utf-8")))
        prefix = filename.encode("utf-8")[:limit].decode("utf-8", errors="ignore").rstrip()
        filename = prefix + suffix
    return Path(options.output_dir).expanduser().resolve() / filename


def human_bytes(value: float) -> str:
    size = float(value)
    for unit in HUMAN_SIZE_UNITS:
        if size < BYTES_PER_KIBIBYTE or unit == HUMAN_SIZE_UNITS[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= BYTES_PER_KIBIBYTE
    return f"{size:.1f} TB"


class Progress:
    """Thread-safe single-line progress output."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self._last_print = 0.0
        self._initial_segments: int | None = None
        self._initial_bytes = 0

    @staticmethod
    def bar(done: int, total: int, width: int = DEFAULT_PROGRESS_BAR_WIDTH) -> str:
        ratio = min(1.0, max(0.0, done / total)) if total else 0.0
        filled = min(width, int(ratio * width))
        return "[" + "#" * filled + "-" * (width - filled) + "]"

    @staticmethod
    def duration(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, SECONDS_PER_HOUR)
        minutes, seconds = divmod(remainder, SECONDS_PER_MINUTE)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def bytes(self, done: int, total: int | None) -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._last_print < PROGRESS_REFRESH_INTERVAL_SECONDS and (
                not total or done < total
            ):
                return
            self._last_print = now
            speed = done / max(now - self.started, MIN_ELAPSED_SECONDS)
            if total:
                percent = min(100.0, done * 100 / total)
                status = f"{percent:6.2f}%  {human_bytes(done)}/{human_bytes(total)}"
            else:
                status = human_bytes(done)
            print(f"\r{self.label}: {status}  {human_bytes(speed)}/s", end="", flush=True)

    def segments(self, done: int, total: int, downloaded_bytes: int) -> None:
        with self._lock:
            now = time.monotonic()
            if self._initial_segments is None:
                self._initial_segments = done
                self._initial_bytes = downloaded_bytes
                self.started = now
            if now - self._last_print < PROGRESS_REFRESH_INTERVAL_SECONDS and done < total:
                return
            self._last_print = now
            elapsed = max(now - self.started, MIN_ELAPSED_SECONDS)
            session_segments = max(0, done - self._initial_segments)
            speed = max(0, downloaded_bytes - self._initial_bytes) / elapsed
            segment_rate = session_segments / elapsed
            percent = min(100.0, done * 100 / total) if total else 0.0
            eta = self.duration((total - done) / segment_rate) if segment_rate > 0 else "--:--"
            print(
                f"\r{self.label}: {self.bar(done, total)} {percent:5.1f}%  "
                f"{done}/{total} 分片  {human_bytes(speed)}/s  剩余 {eta}",
                end="",
                flush=True,
            )

    @staticmethod
    def finish() -> None:
        print()


def locate_ffmpeg() -> str | None:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        candidate = imageio_ffmpeg.get_ffmpeg_exe()
        return candidate if candidate and Path(candidate).is_file() else None
    except Exception:
        return None


def no_window_kwargs() -> dict[str, int]:
    return {"creationflags": WINDOWS_NO_WINDOW_FLAG} if os.name == "nt" else {}


def part_root(destination: Path) -> Path:
    digest = hashlib.sha256(str(destination).encode("utf-8")).hexdigest()[:PATH_DIGEST_LENGTH]
    return (
        destination.parent
        / PARTS_DIRECTORY_NAME
        / f"{sanitize_filename(destination.stem)[:PART_PATH_STEM_LENGTH]}-{digest}"
    )


def ensure_parent(destination: Path) -> None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DownloadError(f"无法创建保存目录 {destination.parent}：{exc}") from exc


def remove_empty_parent(path: Path) -> None:
    with suppress(OSError):
        path.rmdir()


def parse_content_range(value: object) -> tuple[int, int, int] | None:
    match = re.fullmatch(rf"{HTTP_RANGE_UNIT}\s+(\d+)-(\d+)/(\d+)", str(value or "").strip(), re.I)
    if not match:
        return None
    start, end, total = (int(part) for part in match.groups())
    if start > end or end >= total:
        return None
    return start, end, total


def split_ranges(total: int, workers: int) -> list[tuple[int, int]]:
    workers = min(max(1, workers), total)
    chunk, remainder = divmod(total, workers)
    result: list[tuple[int, int]] = []
    start = 0
    for index in range(workers):
        size = chunk + (1 if index < remainder else 0)
        end = start + size - 1
        result.append((start, end))
        start = end + 1
    return result
