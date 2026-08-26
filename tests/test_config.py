import tempfile
import unittest
from pathlib import Path

from vget.config import ConfigError, load_env_defaults, read_env_file


class ConfigTests(unittest.TestCase):
    def test_reads_supported_dotenv_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# local settings\n"
                "export VGET_PROXY=socks5h://127.0.0.1:10808\n"
                "VGET_QUALITY='720p'\n"
                "UNRELATED=value\n",
                encoding="utf-8",
            )
            self.assertEqual(
                read_env_file(path),
                {
                    "VGET_PROXY": "socks5h://127.0.0.1:10808",
                    "VGET_QUALITY": "720p",
                },
            )

    def test_process_environment_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("VGET_QUALITY=best\n", encoding="utf-8")
            values = load_env_defaults(path, {"VGET_QUALITY": "480p"})
            self.assertEqual(values["VGET_QUALITY"], "480p")

    def test_rejects_malformed_dotenv_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("VGET_PROXY\n", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "等号"):
                read_env_file(path)


if __name__ == "__main__":
    unittest.main()
