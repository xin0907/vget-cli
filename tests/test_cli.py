import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vget.arguments import QUALITY_MAP, build_parser, clean_urls, collect_urls, validate_args
from vget.config import (
    ENV_OUTPUT_DIR,
    ENV_PROXY,
    ENV_QUALITY,
    ENV_RETRIES,
    ENV_WORKERS,
    ConfigError,
)
from vget.constants import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROXY_URL,
    DEFAULT_QUALITY,
    DEFAULT_RETRIES,
    DEFAULT_WORKERS,
)

MISSING_ENV_FILE = Path(__file__).with_name(".missing.env")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser(env_file=MISSING_ENV_FILE, environ={})

    def test_common_defaults(self):
        args = self.parser.parse_args(["https://example.com/v"])
        self.assertEqual(args.proxy, DEFAULT_PROXY_URL)
        self.assertEqual(args.quality, DEFAULT_QUALITY)
        self.assertEqual(args.output, Path(DEFAULT_OUTPUT_DIR))
        self.assertEqual(args.retries, DEFAULT_RETRIES)
        self.assertEqual(args.workers, DEFAULT_WORKERS)

    def test_environment_defaults_and_cli_override(self):
        env = {
            ENV_OUTPUT_DIR: "custom-downloads",
            ENV_PROXY: "http://127.0.0.1:7890",
            ENV_QUALITY: "720p",
            ENV_RETRIES: "2",
            ENV_WORKERS: "6",
        }
        parser = build_parser(env_file=MISSING_ENV_FILE, environ=env)
        defaults = parser.parse_args(["https://example.com/v"])
        overridden = parser.parse_args(
            [
                "--proxy",
                "socks5h://127.0.0.1:10809",
                "-q",
                "1080p",
                "-o",
                "cli-downloads",
                "-w",
                "7",
                "--retries",
                "3",
                "https://example.com/v",
            ]
        )
        self.assertEqual(defaults.output, Path("custom-downloads"))
        self.assertEqual(defaults.proxy, "http://127.0.0.1:7890")
        self.assertEqual(defaults.quality, "720p")
        self.assertEqual(defaults.retries, 2)
        self.assertEqual(defaults.workers, 6)
        self.assertEqual(overridden.proxy, "socks5h://127.0.0.1:10809")
        self.assertEqual(overridden.quality, "1080p")
        self.assertEqual(overridden.output, Path("cli-downloads"))
        self.assertEqual(overridden.retries, 3)
        self.assertEqual(overridden.workers, 7)

    def test_empty_proxy_configuration_disables_proxy(self):
        parser = build_parser(env_file=MISSING_ENV_FILE, environ={ENV_PROXY: ""})
        args = parser.parse_args(["https://example.com/v"])
        validate_args(args)
        self.assertEqual(args.proxy, "")

    def test_rejects_invalid_environment_defaults(self):
        invalid_values = (
            (ENV_QUALITY, "4k"),
            (ENV_RETRIES, "-1"),
            (ENV_WORKERS, "many"),
        )
        for key, value in invalid_values:
            with self.subTest(key=key), self.assertRaises(ConfigError):
                build_parser(env_file=MISSING_ENV_FILE, environ={key: value})

    def test_clean_urls_ignores_comments_and_duplicates(self):
        values = ["", "# comment", " https://example.com/a ", "https://example.com/a"]
        self.assertEqual(clean_urls(values), ["https://example.com/a"])

    def test_clean_urls_rejects_non_http_url(self):
        with self.assertRaisesRegex(ValueError, "HTTP"):
            clean_urls(["file:///secret.mp4"])

    def test_clean_urls_accepts_copied_markdown_link(self):
        markdown = "[https://example.com/video](https://example.com/video)"
        self.assertEqual(clean_urls([markdown]), ["https://example.com/video"])

    def test_validate_args_unwraps_markdown_proxy(self):
        args = self.parser.parse_args(
            ["--proxy", "[http://127.0.0.1:10808](http://127.0.0.1:10808)", "https://example.com/v"]
        )
        validate_args(args)
        self.assertEqual(args.proxy, "http://127.0.0.1:10808")

    def test_input_file_supports_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "urls.txt"
            path.write_text("\ufeff# 视频\nhttps://example.com/v\n", encoding="utf-8")
            args = self.parser.parse_args(["-i", str(path)])
            with patch("sys.stdin.isatty", return_value=True):
                self.assertEqual(collect_urls(args), ["https://example.com/v"])

    def test_reads_piped_stdin(self):
        args = self.parser.parse_args([])
        stdin = io.StringIO("https://example.com/from-stdin\n")
        with patch("sys.stdin", stdin):
            self.assertEqual(collect_urls(args), ["https://example.com/from-stdin"])

    def test_quality_alias(self):
        self.assertEqual(QUALITY_MAP["best"], "highest")
        self.assertEqual(QUALITY_MAP["1080p"], "1080")

    def test_rejects_too_many_workers(self):
        args = self.parser.parse_args(["--workers", "17", "https://example.com/v"])
        with self.assertRaisesRegex(ValueError, "16"):
            validate_args(args)

    def test_rejects_unknown_template_field(self):
        args = self.parser.parse_args(["-n", "{unknown}.mp4", "https://example.com/v"])
        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_args(args)


if __name__ == "__main__":
    unittest.main()
