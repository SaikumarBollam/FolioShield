"""
Declarative request-schema validation for the FolioShield API (Phase 3 P2).

Each endpoint declares its body fields once; the same declarations drive
runtime validation (400 with field-level detail) and the generated
OpenAPI document (docs/api/openapi.yaml via data/generate_openapi.py),
so the published contract cannot drift from the enforced one.

Field spec: (name, kind, required, max_length)
  kind: "string" | "number" | "integer" | "boolean" | "object" | "array" | "any"
Unknown fields are allowed (additive evolution) but flagged in the
validation result for logging; missing/wrong-typed required fields fail.
"""

from typing import Any, Dict, List, Optional, Tuple

FieldSpec = Tuple[str, str, bool, Optional[int]]


def field(name: str, kind: str = "string", required: bool = False,
          max_length: Optional[int] = None) -> FieldSpec:
    return (name, kind, required, max_length)


# Legacy dispute endpoints (core/api.py POST routes).
LEGACY_SCHEMAS: Dict[str, List[FieldSpec]] = {
    "/api/v1/reconcile": [
        field("notice", "object", required=True), field("folio", "object", required=True),
        field("supporting_docs", "object"),
    ],
    "/api/v1/rebuttal/draft": [
        field("notice", "object", required=True), field("folio", "object", required=True),
        field("supporting_docs", "object"), field("custom_notes", "string", max_length=10000),
    ],
    "/api/v1/packet/generate": [
        field("notice", "object", required=True), field("folio", "object", required=True),
        field("rebuttal_text", "string", required=True, max_length=200000),
        field("supporting_docs", "object"), field("policy_text", "string", max_length=100000),
        field("approval", "object"),
    ],
    "/api/v1/submission/bundle": [
        field("notice", "object", required=True), field("folio", "object", required=True),
        field("packet_base64", "string", required=True, max_length=30000000),
        field("exhibits", "object"), field("supporting_docs", "object"),
        field("portal_id", "string", max_length=64),
    ],
    "/api/v1/submission/register": [
        field("case_id", "string", required=True, max_length=128),
        field("portal_id", "string", max_length=64), field("bundle_sha256", "string", max_length=128),
        field("confirmation_reference", "string", max_length=256),
        field("submitted_by", "string", max_length=256), field("submitted_at", "string", max_length=64),
        field("status", "string", max_length=64), field("notes", "string", max_length=5000),
    ],
    "/api/v1/submission/outcome": [
        field("case_id", "string", required=True, max_length=128),
        field("decision", "string", required=True, max_length=64),
        field("amount_recovered", "number"), field("decided_at", "string", max_length=64),
        field("next_stage", "string", max_length=64), field("notes", "string", max_length=5000),
    ],
    "/api/v1/dispute/approve": [
        field("notice", "object", required=True), field("folio", "object", required=True),
        field("rebuttal_text", "string", required=True, max_length=200000),
        field("approved_by", "string", required=True, max_length=256),
        field("supporting_docs", "object"), field("policy_text", "string", max_length=100000),
        field("custom_notes", "string", max_length=10000),
    ],
    "/api/v1/dispute/process": [
        field("notice", "any", required=True), field("folio", "any", required=True),
        field("supporting_docs", "object"), field("custom_notes", "string", max_length=10000),
        field("policy_text", "string", max_length=100000),
        field("reviewer_name", "string", max_length=256),
    ],
}

# Enterprise integration endpoints (subset validated at the API boundary;
# the service enforces scopes/tenancy separately).
INTEGRATION_SCHEMAS: Dict[str, List[FieldSpec]] = {
    "POST /api/v1/integrations/cases": [
        field("case_id", "string", max_length=128), field("external_case_id", "string", max_length=256),
        field("external_system", "string", max_length=128), field("external_folio_id", "string", max_length=256),
        field("external_transaction_id", "string", max_length=256), field("property_id", "string", max_length=128),
        field("notice", "object"), field("folio", "object"),
    ],
    "POST /api/v1/integrations/cases/{case_id}/documents": [
        field("document_type", "string", required=True, max_length=64),
        field("filename", "string", required=True, max_length=512),
        field("media_type", "string", max_length=128),
        field("content_base64", "string", required=True, max_length=30000000),
        field("evidence_doc_type", "string", max_length=128),
    ],
    "POST /api/v1/integrations/webhooks": [
        field("url", "string", required=True, max_length=2048),
        field("event_types", "array"), field("secret", "string", max_length=512),
        field("description", "string", max_length=512),
    ],
}


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "any":
        return True
    if kind == "string":
        return isinstance(value, str)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    return False


def validate_body(body: Dict[str, Any], schema: List[FieldSpec]) -> Dict[str, Any]:
    """Validates a request body. Returns {ok, errors: [{field, message}], unknown_fields}."""
    errors: List[Dict[str, str]] = []
    known = {spec[0] for spec in schema}
    for name, kind, required, max_length in schema:
        value = body.get(name)
        if value is None:
            if required:
                errors.append({"field": name, "message": f"'{name}' is required"})
            continue
        if not _type_ok(value, kind):
            errors.append({"field": name, "message": f"'{name}' must be of type {kind}"})
            continue
        if max_length is not None and isinstance(value, str) and len(value) > max_length:
            errors.append({"field": name, "message": f"'{name}' exceeds the maximum length of {max_length}"})
    return {"ok": not errors, "errors": errors,
            "unknown_fields": sorted(set(body.keys()) - known)}


def schema_for_legacy(path: str) -> Optional[List[FieldSpec]]:
    return LEGACY_SCHEMAS.get(path)


def schema_for_integration(method: str, parts: List[str]) -> Optional[List[FieldSpec]]:
    """Matches integration routes with {case_id} placeholders."""
    if method != "POST":
        return None
    if parts == ["api", "v1", "integrations", "cases"]:
        return INTEGRATION_SCHEMAS["POST /api/v1/integrations/cases"]
    if len(parts) == 6 and parts[:4] == ["api", "v1", "integrations", "cases"] and parts[5] == "documents":
        return INTEGRATION_SCHEMAS["POST /api/v1/integrations/cases/{case_id}/documents"]
    if parts == ["api", "v1", "integrations", "webhooks"]:
        return INTEGRATION_SCHEMAS["POST /api/v1/integrations/webhooks"]
    return None
