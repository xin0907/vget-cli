"""Extractor registry and public dispatch function."""

from urllib.parse import urlsplit

from vget.constants import HTTP_SCHEMES
from vget.errors import UnsupportedUrlError
from vget.http import HttpClient
from vget.models import MediaSource, Quality

from .base import Extractor
from .direct import DirectMediaExtractor
from .generic import GenericPageExtractor
from .hanime1 import Hanime1Extractor
from .jable import JableExtractor
from .missav import MissAVExtractor
from .supjav import SupJavExtractor

EXTRACTORS: tuple[type[Extractor], ...] = (
    DirectMediaExtractor,
    JableExtractor,
    MissAVExtractor,
    SupJavExtractor,
    Hanime1Extractor,
    GenericPageExtractor,
)


def extract_media(url: str, client: HttpClient, quality: Quality) -> MediaSource:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in HTTP_SCHEMES or not parsed.netloc:
        raise UnsupportedUrlError("只接受有效的 HTTP(S) URL")
    for extractor_type in EXTRACTORS:
        if extractor_type.supports(url):
            return extractor_type().extract(url, client, quality)
    raise UnsupportedUrlError("没有适用于该 URL 的解析器")
