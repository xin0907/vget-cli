"""Command-line task orchestration."""

from __future__ import annotations

import json
import os
import sys
import traceback
from argparse import Namespace
from collections.abc import Sequence
from contextlib import suppress
from importlib.metadata import PackageNotFoundError, version

from .arguments import QUALITY_MAP, collect_urls, parse_args, validate_args

DISTRIBUTION_NAME = "vget-cli"
EXIT_INTERRUPTED = 130
EXIT_OK = 0
EXIT_TASK_FAILED = 1
EXIT_USAGE_ERROR = 2
UNKNOWN_VERSION = "0+unknown"


def package_version() -> str:
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return UNKNOWN_VERSION


def run(args: Namespace) -> int:
    try:
        validate_args(args)
        urls = collect_urls(args)
        if not urls:
            raise ValueError("请提供至少一个 URL，或使用 --input-file")
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    try:
        from .download import download_media
        from .errors import VgetError
        from .extraction import extract_media
        from .http import HttpClient
        from .models import DownloadOptions
    except ImportError as exc:
        print(
            f"错误：缺少运行依赖（{exc}）。请先运行：python -m pip install -e .",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR

    options = DownloadOptions(
        output_dir=str(args.output),
        quality=QUALITY_MAP[args.quality],
        workers=args.workers,
        retries=args.retries,
        overwrite=args.overwrite,
        keep_parts=args.keep_parts,
        download_thumbnail=args.thumbnail,
        name_template=args.name_template,
        referer=args.referer,
        verbose=args.verbose,
    )
    failures = 0
    try:
        cookie_file = args.cookies.expanduser().resolve() if args.cookies else None
        with HttpClient(
            proxy=args.proxy,
            cookie_file=cookie_file,
            user_agent=args.user_agent,
        ) as client:
            if args.verbose:
                print(f"网络后端：{client.backend}")
            for index, url in enumerate(urls, start=1):
                if len(urls) > 1:
                    print(f"\n[{index}/{len(urls)}] {url}")
                try:
                    source = extract_media(url, client, options.quality)
                    if args.info:
                        print(json.dumps(source.public_info(), ensure_ascii=False, indent=2))
                    else:
                        print(f"解析：{source.site} | {source.title} | {source.kind.upper()}")
                        download_media(client, source, options)
                except VgetError as exc:
                    failures += 1
                    print(f"失败：{url}\n  {exc}", file=sys.stderr)
                    if args.verbose:
                        traceback.print_exc()
                except Exception as exc:
                    failures += 1
                    print(f"失败：{url}\n  未预期错误：{exc}", file=sys.stderr)
                    if args.verbose:
                        traceback.print_exc()
    except KeyboardInterrupt:
        print("\n已取消；保留的分片可在下次运行相同命令时续传。", file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        return EXIT_USAGE_ERROR
    return EXIT_TASK_FAILED if failures else EXIT_OK


def _configure_console() -> None:
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        with suppress(AttributeError, OSError):
            stream.reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    _configure_console()
    return run(parse_args(argv, package_version()))
