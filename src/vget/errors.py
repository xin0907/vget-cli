"""Domain errors raised by vget."""


class VgetError(Exception):
    """Base error with a message suitable for CLI users."""


class UnsupportedUrlError(VgetError):
    """No extractor can handle the supplied URL."""


class ExtractionError(VgetError):
    """A supported page did not expose a usable media source."""


class AccessBlockedError(ExtractionError):
    """The origin or CDN returned an anti-bot/interstitial response."""


class DownloadError(VgetError):
    """The selected media source could not be downloaded completely."""


class UnsupportedEncryptionError(DownloadError):
    """The HLS stream uses an unsupported encryption/DRM method."""
