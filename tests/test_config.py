"""Tests: centralized configuration (Phase 3 P2)."""

import os
import unittest
from unittest import mock

from core.config import get_settings


class TestCentralizedConfig(unittest.TestCase):
    def test_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = get_settings()
            self.assertEqual(cfg.api_port, 8000)
            self.assertEqual(cfg.api_max_body_mb, 15)
            self.assertIn("http://localhost:8501", cfg.api_cors_origins)
            self.assertEqual(cfg.integration_root, "data/integrations")
            self.assertEqual(cfg.webhook_resume_seconds, 0)
            self.assertIsNone(cfg.webhook_secret_key)
            self.assertIsNone(cfg.audit_hmac_key)
            self.assertIsNone(cfg.api_key)
            self.assertIsNone(cfg.database_url)
            self.assertIsNone(cfg.s3_endpoint_url)

    def test_overrides(self):
        env = {
            "API_PORT": "9001", "FOLIOSHIELD_API_MAX_BODY_MB": "25",
            "FOLIOSHIELD_API_CORS_ORIGINS": "https://hotel.example, https://pms.example",
            "FOLIOSHIELD_INTEGRATION_ROOT": "/srv/folioshield/integrations",
            "FOLIOSHIELD_WEBHOOK_RESUME_SECONDS": "60",
            "FOLIOSHIELD_WEBHOOK_SECRET_KEY": "test-key",
            "AUDIT_HMAC_KEY": "hmac-key",
            "FOLIOSHIELD_API_KEY": "api-key-123",
            "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
            "S3_ENDPOINT_URL": "http://minio:9000",
            "S3_BUCKET_NAME": "test-bucket",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = get_settings()
            self.assertEqual(cfg.api_port, 9001)
            self.assertEqual(cfg.api_max_body_mb, 25)
            self.assertEqual(cfg.api_cors_origins, ("https://hotel.example", "https://pms.example"))
            self.assertEqual(cfg.integration_root, "/srv/folioshield/integrations")
            self.assertEqual(cfg.webhook_resume_seconds, 60)
            self.assertEqual(cfg.webhook_secret_key, "test-key")
            self.assertEqual(cfg.audit_hmac_key, "hmac-key")
            self.assertEqual(cfg.api_key, "api-key-123")
            self.assertEqual(cfg.database_url, "postgresql://test:test@localhost:5432/test")
            self.assertEqual(cfg.s3_endpoint_url, "http://minio:9000")
            self.assertEqual(cfg.s3_bucket_name, "test-bucket")

    def test_malformed_values_fall_back(self):
        env = {"API_PORT": "not-a-port", "FOLIOSHIELD_API_MAX_BODY_MB": "huge",
               "FOLIOSHIELD_WEBHOOK_RESUME_SECONDS": "-5", "MAX_UPLOAD_SIZE_MB": "abc"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = get_settings()
            self.assertEqual(cfg.api_port, 8000)
            self.assertEqual(cfg.api_max_body_mb, 15)
            self.assertEqual(cfg.webhook_resume_seconds, 0)
            self.assertEqual(cfg.max_upload_size_mb, 10)

    def test_production_fails_closed_without_key(self):
        with mock.patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=True):
            cfg = get_settings()
            self.assertTrue(cfg.is_production)
            self.assertFalse(cfg.api_allow_legacy_unauthenticated)
        with mock.patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=True):
            cfg = get_settings()
            self.assertTrue(cfg.api_allow_legacy_unauthenticated)


if __name__ == "__main__":
    unittest.main()
