"""
Tests for structured logging, PII masking, and correlation tracking.
"""

import json
import logging
import unittest

from core.logging_config import JSONLogFormatter, SensitiveDataFilter, configure_logging


class TestStructuredLogging(unittest.TestCase):
    def test_sensitive_data_filter_redacts_card_and_tokens(self):
        f = SensitiveDataFilter()
        rec1 = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Customer card is 4111 2222 3333 4444 for folio 100", args=(), exc_info=None
        )
        f.filter(rec1)
        self.assertNotIn("4111 2222 3333 4444", rec1.msg)
        self.assertIn("[REDACTED_PAN]", rec1.msg)

        rec2 = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Received request with Authorization: Bearer secret-token-xyz123", args=(), exc_info=None
        )
        f.filter(rec2)
        self.assertNotIn("secret-token-xyz123", rec2.msg)
        self.assertIn("[REDACTED_TOKEN]", rec2.msg)

    def test_json_formatter_produces_valid_json(self):
        formatter = JSONLogFormatter()
        rec = logging.LogRecord(
            name="folioshield.api", level=logging.INFO, pathname="api.py", lineno=10,
            msg="Dispute processed successfully", args=(), exc_info=None
        )
        rec.request_id = "req-12345"  # type: ignore[attr-defined]

        output = formatter.format(rec)
        data = json.loads(output)
        self.assertEqual(data["level"], "INFO")
        self.assertEqual(data["logger"], "folioshield.api")
        self.assertEqual(data["message"], "Dispute processed successfully")
        self.assertEqual(data["request_id"], "req-12345")
        self.assertIn("timestamp", data)

    def test_configure_logging_integration(self):
        configure_logging(level="DEBUG", json_format=True)
        root = logging.getLogger()
        self.assertEqual(root.level, logging.DEBUG)
        self.assertTrue(any(isinstance(f, SensitiveDataFilter) for h in root.handlers for f in h.filters))


if __name__ == "__main__":
    unittest.main()
