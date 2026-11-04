"""
Generates docs/api/openapi.yaml from core/api_schemas.py + the endpoint
inventory in core/api.py. Run directly to regenerate; a test asserts the
committed file matches this output (drift guard).

    python data/generate_openapi.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.api_schemas import INTEGRATION_SCHEMAS, LEGACY_SCHEMAS

LEGACY_GET = {"/health": "Liveness probe (minimal public payload).",
              "/api/v1/health": "Liveness probe (minimal public payload)."}

INTEGRATION_GET = {
    "/api/v1/integrations/cases": "List tenant cases.",
    "/api/v1/integrations/cases/{case_id}": "Get one tenant case.",
    "/api/v1/integrations/cases/{case_id}/audit": "Audit trail for a case.",
    "/api/v1/integrations/monitoring": "Tenant monitoring snapshot.",
    "/api/v1/integrations/agents": "List tenant agents.",
    "/api/v1/integrations/webhooks": "List webhook subscriptions.",
}

INTEGRATION_POST_EXTRA = {
    "/api/v1/integrations/cases/{case_id}/reconcile": "Reconcile a case.",
    "/api/v1/integrations/cases/{case_id}/draft": "Draft a rebuttal (machine processing, not approval).",
    "/api/v1/integrations/cases/{case_id}/process": "Reconcile + draft. Returns approval: null, human_approval_required: true.",
    "/api/v1/integrations/cases/{case_id}/packet": "Generate a packet from an explicit human approval reference.",
    "/api/v1/integrations/agents/{agent_id}/heartbeat": "Agent heartbeat / liveness.",
}

_KIND_MAP = {"string": "string", "number": "number", "integer": "integer",
             "boolean": "boolean", "object": "object", "array": "array", "any": None}


def _schema_yaml(schema, indent="        "):
    lines = [f"{indent}type: object", f"{indent}properties:"]
    required = []
    for name, kind, req, max_length in schema:
        if req:
            required.append(name)
        lines.append(f"{indent}  {name}:")
        mapped = _KIND_MAP.get(kind)
        if mapped:
            lines.append(f"{indent}    type: {mapped}")
        if max_length:
            lines.append(f"{indent}    maxLength: {max_length}")
    if required:
        lines.append(f"{indent}required: [{', '.join(required)}]")
    return lines


def generate_openapi() -> str:
    out = [
        "openapi: 3.1.0",
        "info:",
        "  title: FolioShield API",
        "  version: 1.1.0",
        "  description: >-",
        "    Hotel chargeback defense API. Legacy endpoints require the shared",
        "    API key when FOLIOSHIELD_API_KEY is configured (fail-closed in",
        "    production). Enterprise integration endpoints require tenant",
        "    Bearer credentials. Machine processing never creates human",
        "    approval: packets are drafts until an explicit, fingerprint-bound",
        "    approval is supplied.",
        "servers:",
        "  - url: http://localhost:8000",
        "security:",
        "  - bearerAuth: []",
        "paths:",
    ]
    for path, summary in sorted(LEGACY_GET.items()):
        out += [f"  {path}:", "    get:", f"      summary: {summary}",
                "      security: []",
                "      responses:", "        '200': {description: OK}"]
    for path, schema in sorted(LEGACY_SCHEMAS.items()):
        out += [f"  {path}:", "    post:", f"      summary: Legacy dispute endpoint {path}.",
                "      requestBody:",
                "        required: true",
                "        content:",
                "          application/json:",
                "            schema:"]
        out += _schema_yaml(schema)
        out += ["      responses:", "        '200': {description: OK}",
                "        '400': {description: Validation or request error}",
                "        '401': {description: Authentication required}",
                "        '409': {description: Approval stale (packet/generate)}",
                "        '429': {description: Rate limited}"]
    for path, summary in sorted(INTEGRATION_GET.items()):
        out += [f"  {path}:", "    get:", f"      summary: {summary}",
                "      responses:", "        '200': {description: OK}",
                "        '401': {description: Authentication required}",
                "        '403': {description: Forbidden (scope/tenant)}",
                "        '404': {description: Not found}"]
    for key, schema in sorted(INTEGRATION_SCHEMAS.items()):
        method, path = key.split(" ", 1)
        out += [f"  {path}:", f"    {method.lower()}:", f"      summary: Integration endpoint {path}.",
                "      requestBody:",
                "        required: true",
                "        content:",
                "          application/json:",
                "            schema:"]
        out += _schema_yaml(schema)
        out += ["      responses:", "        '200': {description: OK}",
                "        '201': {description: Created}",
                "        '400': {description: Validation or request error}",
                "        '401': {description: Authentication required}",
                "        '403': {description: Forbidden (scope/tenant)}"]
    for path, summary in sorted(INTEGRATION_POST_EXTRA.items()):
        out += [f"  {path}:", "    post:", f"      summary: {summary}",
                "      responses:", "        '200': {description: OK}",
                "        '401': {description: Authentication required}",
                "        '403': {description: Forbidden (scope/tenant)}",
                "        '404': {description: Not found}"]
    out += [
        "components:",
        "  securitySchemes:",
        "    bearerAuth:",
        "      type: http",
        "      scheme: bearer",
        "      description: >-",
        "        Legacy endpoints: the shared FOLIOSHIELD_API_KEY. Integration",
        "        endpoints: a tenant credential (<credential_id>.<secret>).",
    ]
    return "\n".join(out) + "\n"


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_openapi(), encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
