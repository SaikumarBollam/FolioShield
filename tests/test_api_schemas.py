"""Tests: API schemas, OpenAPI drift, dependency parity (Phase 3 P2)."""

import re
import unittest
from pathlib import Path

from core.api_schemas import (LEGACY_SCHEMAS, schema_for_integration,
                              schema_for_legacy, validate_body)

ROOT = Path(__file__).resolve().parent.parent


class TestApiSchemas(unittest.TestCase):
    def test_valid_body_passes(self):
        result = validate_body({"notice": {}, "folio": {}}, LEGACY_SCHEMAS["/api/v1/reconcile"])
        self.assertTrue(result["ok"])

    def test_missing_required_field(self):
        result = validate_body({"folio": {}}, LEGACY_SCHEMAS["/api/v1/reconcile"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["field"], "notice")

    def test_wrong_type_and_oversized(self):
        result = validate_body({"notice": "not-an-object", "folio": {}},
                               LEGACY_SCHEMAS["/api/v1/reconcile"])
        self.assertFalse(result["ok"])
        result = validate_body({"case_id": "x" * 200, "decision": "won"},
                               LEGACY_SCHEMAS["/api/v1/submission/outcome"])
        self.assertFalse(result["ok"])

    def test_unknown_fields_reported_not_rejected(self):
        result = validate_body({"notice": {}, "folio": {}, "future_field": 1},
                               LEGACY_SCHEMAS["/api/v1/reconcile"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["unknown_fields"], ["future_field"])

    def test_integration_route_matching(self):
        self.assertIsNotNone(schema_for_integration("POST", ["api", "v1", "integrations", "cases"]))
        self.assertIsNotNone(schema_for_integration(
            "POST", ["api", "v1", "integrations", "cases", "C-1", "documents"]))
        self.assertIsNone(schema_for_integration("GET", ["api", "v1", "integrations", "cases"]))
        self.assertIsNone(schema_for_legacy("/api/v1/unknown"))


class TestOpenApiDrift(unittest.TestCase):
    def test_committed_openapi_matches_generator(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("gen_openapi", ROOT / "data" / "generate_openapi.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        committed = (ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8")
        self.assertEqual(committed, module.generate_openapi(),
                         "docs/api/openapi.yaml is stale — run: python data/generate_openapi.py")

    def test_openapi_covers_all_legacy_routes(self):
        text = (ROOT / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8")
        for path in LEGACY_SCHEMAS:
            self.assertIn(f"  {path}:", text)


class TestDependencyParity(unittest.TestCase):
    def test_requirements_matches_pyproject(self):
        requirements = {
            re.split(r"[<>=!~ \[]", line.strip(), 1)[0].lower()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        declared = set()
        in_deps = False
        for line in pyproject.splitlines():
            if line.strip() == "dependencies = [":
                in_deps = True
                continue
            if in_deps:
                if line.strip() == "]":
                    break
                match = re.search(r'"([^"]+)"', line)
                if match:
                    declared.add(re.split(r"[<>=!~ \[]", match.group(1), 1)[0].lower())
        self.assertEqual(requirements, declared)


if __name__ == "__main__":
    unittest.main()
