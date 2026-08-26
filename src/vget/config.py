"""Load local vget defaults from environment variables and a .env file."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

DEFAULT_ENV_FILE = Path(".env")
ENV_OUTPUT_DIR = "VGET_OUTPUT_DIR"
ENV_PROXY = "VGET_PROXY"
ENV_QUALITY = "VGET_QUALITY"
ENV_RETRIES = "VGET_RETRIES"
ENV_WORKERS = "VGET_WORKERS"
SUPPORTED_ENV_KEYS = frozenset(
    {
        ENV_OUTPUT_DIR,
        ENV_PROXY,
        ENV_QUALITY,
        ENV_RETRIES,
        ENV_WORKERS,
    }
)
QUOTE_CHARS = frozenset({"'", '"'})


class ConfigError(ValueError):
    """Raised when the local .env file cannot be parsed."""


def read_env_file(path: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}：{exc}") from exc

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator:
            raise ConfigError(f"{path}:{line_number} 缺少等号")
        if key not in SUPPORTED_ENV_KEYS:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in QUOTE_CHARS:
            value = value[1:-1]
        values[key] = value
    return values


def load_env_defaults(
    path: Path = DEFAULT_ENV_FILE,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    values = read_env_file(path)
    process_env = os.environ if environ is None else environ
    for key in SUPPORTED_ENV_KEYS:
        if key in process_env:
            values[key] = process_env[key]
    return values
