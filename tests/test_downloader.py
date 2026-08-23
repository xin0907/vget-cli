import tempfile
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from vget.download.common import Progress, output_path, sanitize_filename
from vget.download.direct import DirectDownloader
from vget.download.hls import (
    HLSDownloader,
    SegmentSpec,
    parse_byte_range,
    select_variant,
    strip_supjav_fake_header,
)
from vget.models import DownloadOptions, MediaSource


class FakeResponse:
    def __init__(self, content, status=200, headers=None):
        self.content = content
        self.status_code = status
        self.headers = headers or {}
        self.text = content.decode("utf-8", errors="replace")
        self.url = "https://cdn.example/resource"

    def iter_content(self, chunk_size=256 * 1024):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]

    def close(self):
        pass


class FakeClient:
    def __init__(self, values):
        self.values = values

    def get(self, url, **kwargs):
        return self.values[url]


class RangeClient:
    def __init__(self, data):
        self.data = data

    def get(self, url, **kwargs):
        raw_range = kwargs.get("headers", {}).get("Range")
        if raw_range:
            start_text, end_text = raw_range.removeprefix("bytes=").split("-", 1)
            start = int(start_text)
            end = int(end_text) if end_text else len(self.data) - 1
            return FakeResponse(
                self.data[start : end + 1],
                status=206,
                headers={"content-range": f"bytes {start}-{end}/{len(self.data)}"},
            )
        return FakeResponse(self.data, headers={"content-length": str(len(self.data))})


class DownloaderTests(unittest.TestCase):
    def test_progress_bar_represents_total_segments(self):
        self.assertEqual(Progress.bar(5, 10, width=10), "[#####-----]")
        self.assertEqual(Progress.bar(10, 10, width=10), "[##########]")

    def test_filename_is_windows_safe(self):
        self.assertEqual(sanitize_filename("A:B/C?*"), "A：B／C？＊")
        self.assertEqual(sanitize_filename("CON"), "_CON")

    def test_output_template(self):
        with tempfile.TemporaryDirectory() as directory:
            source = MediaSource("p", "m", "direct", "Title", "id1", "site")
            options = DownloadOptions(output_dir=directory, name_template="{site}-{id}.{ext}")
            self.assertEqual(output_path(source, options).name, "site-id1.mp4")

    def test_byte_range_implicit_offset(self):
        first, next_offset = parse_byte_range("100@20", None)
        second, end_offset = parse_byte_range("50", next_offset)
        self.assertEqual((first.start, first.end), (20, 119))
        self.assertEqual((second.start, second.end, end_offset), (120, 169, 170))

    def test_variant_quality_cap(self):
        def variant(height, bandwidth):
            info = types.SimpleNamespace(resolution=(1280, height), bandwidth=bandwidth)
            return types.SimpleNamespace(stream_info=info, uri=f"{height}.m3u8")

        variants = [variant(360, 1), variant(720, 2), variant(1080, 3)]
        self.assertEqual(select_variant(variants, "720").uri, "720.m3u8")
        self.assertEqual(select_variant(variants, "highest").uri, "1080.m3u8")
        self.assertEqual(select_variant(variants, "lowest").uri, "360.m3u8")

    def test_aes128_segment_with_implicit_iv(self):
        key = b"0123456789abcdef"
        sequence = 9
        plaintext = b"\x47" + b"x" * 187
        encrypted = AES.new(key, AES.MODE_CBC, sequence.to_bytes(16, "big")).encrypt(
            pad(plaintext, 16)
        )
        client = FakeClient(
            {
                "https://cdn.example/seg.ts": FakeResponse(encrypted),
                "https://cdn.example/key": FakeResponse(key),
            }
        )
        options = DownloadOptions(output_dir=".", retries=0)
        downloader = HLSDownloader(client, options)
        source = MediaSource("p", "m", "hls", "Title", "id", "site")
        spec = SegmentSpec(
            0,
            sequence,
            "https://cdn.example/seg.ts",
            None,
            "AES-128",
            "https://cdn.example/key",
            None,
            None,
        )
        self.assertEqual(downloader._download_segment(source, spec), plaintext)

    def test_supjav_fake_png_header(self):
        packet = b"\x47" + b"x" * 187
        data = b"fake-png" + packet * 5
        self.assertEqual(strip_supjav_fake_header(data), packet * 5)

    def test_direct_parallel_range_download(self):
        data = bytes(range(256)) * 4097
        with tempfile.TemporaryDirectory() as directory:
            options = DownloadOptions(
                output_dir=directory,
                workers=4,
                retries=0,
                name_template="result.{ext}",
            )
            source = MediaSource(
                "https://example/page",
                "https://cdn.example/video.mp4",
                "direct",
                "Title",
                "id",
                "test",
            )
            destination = output_path(source, options)
            with redirect_stdout(StringIO()):
                DirectDownloader(RangeClient(data), options).download(source, destination)
            self.assertEqual(destination.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
