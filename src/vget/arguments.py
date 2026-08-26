"""CLI argument definitions and input validation."""

from __future__ import annotations

import argparse
import re
import string
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from .config import (
    DEFAULT_ENV_FILE,
    ENV_OUTPUT_DIR,
    ENV_PROXY,
    ENV_QUALITY,
    ENV_RETRIES,
    ENV_WORKERS,
    ConfigError,
    load_env_defaults,
)
from .constants import (
    DEFAULT_NAME_TEMPLATE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROXY_URL,
    DEFAULT_QUALITY,
    DEFAULT_RETRIES,
    DEFAULT_WORKERS,
    HTTP_URL_PREFIXES,
    MAX_WORKERS,
)

ALLOWED_TEMPLATE_FIELDS = {"title", "id", "site", "ext"}
PROXY_URL_PREFIXES = (*HTTP_URL_PREFIXES, "socks4://", "socks5://", "socks5h://")
QUALITY_MAP = {
    "best": "highest",
    "highest": "highest",
    "1080p": "1080",
    "720p": "720",
    "480p": "480",
    "360p": "360",
    "lowest": "lowest",
}
MARKDOWN_LINK_RE = re.compile(r"^\[[^\]]*\]\((https?://[^\s)]+)\)$", re.IGNORECASE)


def unwrap_markdown_link(value: str) -> str:
    value = value.strip()
    match = MARKDOWN_LINK_RE.fullmatch(value)
    return match.group(1) if match else value


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是整数") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("必须大于 0")
    return number


def non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是整数") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("不能小于 0")
    return number


def configured_int(
    values: Mapping[str, str],
    key: str,
    fallback: int,
    converter: Callable[[str], int],
) -> int:
    raw_value = values.get(key)
    if raw_value is None:
        return fallback
    try:
        return converter(raw_value)
    except argparse.ArgumentTypeError as exc:
        raise ConfigError(f"{key}：{exc}") from exc


def build_parser(
    version: str = "unknown",
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    environ: Mapping[str, str] | None = None,
) -> argparse.ArgumentParser:
    env_defaults = load_env_defaults(env_file, environ)
    default_quality = env_defaults.get(ENV_QUALITY, DEFAULT_QUALITY)
    if default_quality not in QUALITY_MAP:
        choices = "、".join(QUALITY_MAP)
        raise ConfigError(f"{ENV_QUALITY} 必须是以下值之一：{choices}")
    default_output = Path(env_defaults.get(ENV_OUTPUT_DIR, DEFAULT_OUTPUT_DIR))
    default_proxy = env_defaults.get(ENV_PROXY, DEFAULT_PROXY_URL)
    default_workers = configured_int(
        env_defaults,
        ENV_WORKERS,
        DEFAULT_WORKERS,
        positive_int,
    )
    default_retries = configured_int(
        env_defaults,
        ENV_RETRIES,
        DEFAULT_RETRIES,
        non_negative_int,
    )
    parser = argparse.ArgumentParser(
        prog="vget",
        description="JableTV、MissAV、SupJav、Hanime1 及 MP4/M3U8 的纯 CLI 下载器。",
        epilog="请只下载你有权保存的内容；vget 不绕过 DRM 或付费限制。",
    )
    parser.add_argument("urls", nargs="*", metavar="URL", help="一个或多个网页/媒体 URL")
    parser.add_argument(
        "-i",
        "--input-file",
        type=Path,
        metavar="FILE",
        help="批量地址文件，每行一个 URL；忽略空行和 # 注释",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_output,
        metavar="DIR",
        help=f"保存目录（默认：{default_output}）",
    )
    parser.add_argument(
        "-q",
        "--quality",
        choices=tuple(QUALITY_MAP),
        default=default_quality,
        help=f"画质偏好或上限（默认：{default_quality}）",
    )
    parser.add_argument(
        "-n",
        "--name-template",
        default=DEFAULT_NAME_TEMPLATE,
        metavar="TEMPLATE",
        help="文件名模板，可用 {title}、{id}、{site}、{ext}",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=positive_int,
        default=default_workers,
        metavar="N",
        help=f"每个视频的并发分片数，最高 {MAX_WORKERS}（默认：{default_workers}）",
    )
    parser.add_argument(
        "--retries",
        type=non_negative_int,
        default=default_retries,
        metavar="N",
        help=f"每个请求的重试次数（默认：{default_retries}）",
    )
    parser.add_argument(
        "--proxy",
        default=default_proxy,
        metavar="URL",
        help=f"HTTP、HTTPS 或 SOCKS 代理（默认：{default_proxy or '不使用'}）",
    )
    parser.add_argument("--cookies", type=Path, metavar="FILE", help="Netscape 格式 Cookie 文件")
    parser.add_argument("--user-agent", metavar="TEXT", help="自定义 User-Agent")
    parser.add_argument("--referer", metavar="URL", help="覆盖媒体请求的 Referer")
    parser.add_argument("--thumbnail", action="store_true", help="同时保存封面图片")
    parser.add_argument("--overwrite", action="store_true", help="覆盖同名成品")
    parser.add_argument("--keep-parts", action="store_true", help="成功后保留分片和临时文件")
    parser.add_argument("--info", action="store_true", help="只解析并输出媒体信息，不下载")
    parser.add_argument("--verbose", action="store_true", help="显示详细错误和网络后端")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version}")
    return parser


def clean_urls(values: Iterable[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = unwrap_markdown_link(value)
        if not url or url.startswith("#") or url in seen:
            continue
        if not url.lower().startswith(HTTP_URL_PREFIXES):
            raise ValueError(f"不是有效的 HTTP(S) URL：{url}")
        seen.add(url)
        urls.append(url)
    return urls


def read_url_file(path: Path) -> list[str]:
    try:
        return clean_urls(path.read_text(encoding="utf-8-sig").splitlines())
    except OSError as exc:
        raise ValueError(f"无法读取地址文件 {path}：{exc}") from exc


def collect_urls(args: argparse.Namespace) -> list[str]:
    values = list(args.urls)
    if args.input_file:
        values.extend(read_url_file(args.input_file))
    if not values and not sys.stdin.isatty():
        values.extend(sys.stdin.read().splitlines())
    return clean_urls(values)


def validate_args(args: argparse.Namespace) -> None:
    if args.quality not in QUALITY_MAP:
        raise ValueError(f"画质配置无效：{args.quality}")
    if args.workers > MAX_WORKERS:
        raise ValueError(f"--workers 最高为 {MAX_WORKERS}")
    if args.cookies and not args.cookies.expanduser().is_file():
        raise ValueError(f"Cookie 文件不存在：{args.cookies}")
    if args.proxy:
        args.proxy = unwrap_markdown_link(args.proxy)
        if not args.proxy.lower().startswith(PROXY_URL_PREFIXES):
            raise ValueError(f"代理地址格式无效：{args.proxy}")
    output = args.output.expanduser()
    if output.drive and not Path(output.anchor).exists():
        raise ValueError(f"输出磁盘不存在：{output.drive}（请改用现有磁盘，例如 E:/Videos）")
    for _, field_name, _, _ in string.Formatter().parse(args.name_template):
        if field_name and field_name not in ALLOWED_TEMPLATE_FIELDS:
            raise ValueError(f"文件名模板包含未知字段 {{{field_name}}}")


def parse_args(argv: Sequence[str] | None, version: str) -> argparse.Namespace:
    try:
        return build_parser(version).parse_args(argv)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
