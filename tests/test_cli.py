import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vget.arguments import QUALITY_MAP, build_parser, clean_urls, collect_urls, validate_args


class CliTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

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
