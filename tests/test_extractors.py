import unittest

from vget.extraction.direct import DirectMediaExtractor
from vget.extraction.hanime1 import Hanime1Extractor
from vget.extraction.jable import JableExtractor
from vget.extraction.missav import MissAVExtractor
from vget.extraction.supjav import streamtape_direct_url


class FakeResponse:
    def __init__(self, url, body, status=200, headers=None):
        self.url = url
        self.content = body.encode() if isinstance(body, str) else body
        self.text = self.content.decode("utf-8", errors="replace")
        self.status_code = status
        self.headers = headers or {}


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.cookies = []

    def get(self, url, **kwargs):
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    def set_cookie(self, name, value, *, domain):
        self.cookies.append((name, value, domain))


class ExtractorTests(unittest.TestCase):
    def test_direct_media_url(self):
        source = DirectMediaExtractor().extract(
            "https://cdn.example/video.m3u8?token=1", FakeClient({}), "highest"
        )
        self.assertEqual(source.kind, "hls")
        self.assertEqual(source.media_id, "video")

    def test_jable_page(self):
        url = "https://jable.tv/videos/abc-123/"
        body = """
            <html><head>
            <meta property="og:title" content="Example title">
            <meta property="og:image" content="https://img.example/cover.jpg">
            </head><script>const src='https://cdn.example/master.m3u8?x=1';</script></html>
        """
        source = JableExtractor().extract(
            url, FakeClient({url: FakeResponse(url, body)}), "highest"
        )
        self.assertEqual(source.title, "Example title")
        self.assertEqual(source.media_url, "https://cdn.example/master.m3u8?x=1")
        self.assertEqual(source.media_id, "abc-123")
        self.assertEqual(source.headers["Origin"], "https://jable.tv")

    def test_missav_url_gate_rejects_category(self):
        self.assertTrue(MissAVExtractor.supports("https://missav.ai/sone-543"))
        self.assertFalse(MissAVExtractor.supports("https://missav.ai/dm278/chinese-subtitle"))

    def test_streamtape_live_url(self):
        markup = """
          <script>
          document.getElementById('robotlink').innerHTML =
            'streamtape.com/get_video?id=' + ('xxxTOKEN').substring(3);
          </script>
        """
        self.assertEqual(
            streamtape_direct_url(markup),
            "https://streamtape.com/get_video?id=TOKEN",
        )

    def test_hanime_selects_quality_cap(self):
        home = "https://hanime1.me/"
        url = "https://hanime1.me/watch?v=123"
        body = """
          <html><head><meta property="og:title" content="Demo - Hanime1.me"></head>
          <video><source src="https://cdn.example/video-720p.mp4"></video>
          <a href="https://cdn.example/video-1080p.mp4">1080p</a></html>
        """
        client = FakeClient(
            {
                home: FakeResponse(home, "<html>ok</html>"),
                url: FakeResponse(url, body),
            }
        )
        source = Hanime1Extractor().extract(url, client, "720")
        self.assertEqual(source.media_url, "https://cdn.example/video-720p.mp4")
        self.assertEqual(source.title, "Demo")


if __name__ == "__main__":
    unittest.main()
