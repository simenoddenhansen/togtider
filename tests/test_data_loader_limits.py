import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch


APP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app")
sys.path.insert(0, APP_DIR)

import data_loader


class _FakeResponse:
    def __init__(self, payload, content_length=None):
        self.payload = payload
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.read_size = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size):
        self.read_size = size
        return self.payload[:size]


class DataLoaderLimitsTest(unittest.TestCase):
    def test_download_range_allows_configured_limit(self):
        start, end = data_loader.validate_download_range(
            date(2026, 9, 1),
            date(2026, 9, 8),
        )

        self.assertEqual(start, date(2026, 9, 1))
        self.assertEqual(end, date(2026, 9, 8))

    def test_download_range_rejects_longer_period(self):
        with self.assertRaisesRegex(ValueError, "7 dager"):
            data_loader.validate_download_range(
                date(2026, 9, 1),
                date(2026, 9, 9),
            )

    def test_archive_index_rejects_non_date_entries(self):
        payload = json.dumps({"days": ["../../secrets"]}).encode("utf-8")

        with self.assertRaisesRegex(ValueError, "ugyldig dato"):
            data_loader._parse_archive_index(payload)

    @patch("data_loader.st.warning")
    @patch("data_loader.urlopen")
    def test_http_fetch_rejects_large_content_length(self, mock_urlopen, _warning):
        response = _FakeResponse(b"small", content_length=11)
        mock_urlopen.return_value = response

        payload = data_loader._http_get_bytes("https://example.test/file", 10)

        self.assertIsNone(payload)
        self.assertIsNone(response.read_size)

    @patch("data_loader.st.warning")
    @patch("data_loader.urlopen")
    def test_http_fetch_reads_only_one_byte_past_limit(self, mock_urlopen, _warning):
        response = _FakeResponse(b"12345")
        mock_urlopen.return_value = response

        payload = data_loader._http_get_bytes("https://example.test/file", 4)

        self.assertIsNone(payload)
        self.assertEqual(response.read_size, 5)


if __name__ == "__main__":
    unittest.main()
