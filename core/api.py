"""
FolioShield REST API Server.

The original dispute endpoints remain available for backward compatibility.
Enterprise integration endpoints under /api/v1/integrations require Bearer
API credentials issued through core.integrations and are tenant-scoped.

Important deployment note: the built-in Python http.server implementation
is suitable for local development and controlled integration testing. It is
not, by itself, a production internet-facing server. Production deployments
must terminate TLS and enforce network controls at a reviewed reverse proxy
or production server layer. See docs/integrations/deployment.md.
"""

import base64
import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from .client import FolioShield
from .config import config
from .integrations.authentication import parse_bearer_token
from .integrations.contracts import IntegrationCaseRef
from .integrations.registry import IntegrationRegistry
from .integrations.service import IntegrationService
from .integrations.webhooks import WebhookManager

logger = logging.getLogger(__name__)
fs = FolioShield()

MAX_JSON_BODY_BYTES = int(os.getenv("FOLIOSHIELD_API_MAX_BODY_MB", "15")) * 1024 * 1024
ALLOWED_ORIGINS = {
    origin.strip() for origin in os.getenv("FOLIOSHIELD_API_CORS_ORIGINS", "http://localhost:8501,http://localhost:3000").split(",")
    if origin.strip()
}
INTEGRATION_ROOT = os.getenv("FOLIOSHIELD_INTEGRATION_ROOT", "data/integrations")


def _integration_service() -> IntegrationService:
    registry = IntegrationRegistry(root=INTEGRATION_ROOT)
    return IntegrationService(registry=registry, engine=FolioShield(), webhooks=WebhookManager(registry))


class FolioShieldAPIHandler(BaseHTTPRequestHandler):
    """HTTP handler for legacy dispute endpoints and enterprise integrations."""

    server_version = "FolioShieldAPI/1.1"

    # -------------------------------------------------------------- utilities

    def _request_id(self) -> str:
        return self.headers.get("X-Request-Id") or str(uuid.uuid4())

    def _cors_origin(self) -> Optional[str]:
        origin = self.headers.get("Origin")
        if origin and origin in ALLOWED_ORIGINS:
            return origin
        return None

    def _set_headers(self, status: int = 200, content_type: str = "application/json", request_id: Optional[str] = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Request-Id, Idempotency-Key")
        self.send_header("X-Request-Id", request_id or self._request_id())
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def _read_json_body(self) -> Dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return {}
        try:
            content_length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if content_length < 0 or content_length > MAX_JSON_BODY_BYTES:
            raise ValueError("Request body exceeds configured API limit")
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        if len(raw) > MAX_JSON_BODY_BYTES:
            raise ValueError("Request body exceeds configured API limit")
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("JSON body must be an object")
        return parsed

    def _send_json(self, data: Dict[str, Any], status: int = 200, request_id: Optional[str] = None):
        self._set_headers(status, request_id=request_id)
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def _send_error(self, message: str, status: int = 400, request_id: Optional[str] = None, code: str = "bad_request"):
        self._send_json({"status": "error", "error": {"code": code, "message": message},
                         "request_id": request_id or self._request_id()}, status=status, request_id=request_id)

    def _authenticate(self, request_id: str):
        token = parse_bearer_token(self.headers.get("Authorization"))
        if not token:
            return None, None
        registry = IntegrationRegistry(root=INTEGRATION_ROOT)
        principal = registry.authenticate(token)
        if not principal:
            return None, None
        return principal.to_context(request_id=request_id), registry

    def _require_integration(self, request_id: str):
        context, registry = self._authenticate(request_id)
        if not context:
            self._send_error("Authentication required", status=401, request_id=request_id, code="unauthorized")
            return None, None, None
        service = IntegrationService(registry=registry, engine=FolioShield(), webhooks=WebhookManager(registry))
        return context, registry, service

    # ------------------------------------------------------------------- GET

    def do_GET(self):
        request_id = self._request_id()
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/health", "/api/v1/health"):
            self._send_json({
                "status": "healthy",
                "service": "FolioShield Dispute Defense Engine",
                "version": "1.1.0",
                "environment": config.environment,
                "provider": fs.llama_engine.provider,
                "api_configured": fs.llama_engine.is_api_configured(),
                "request_id": request_id,
            }, request_id=request_id)
            return

        if path.startswith("/api/v1/integrations/"):
            context, registry, service = self._require_integration(request_id)
            if not context:
                return
            try:
                parts = [p for p in path.split("/") if p]
                # /api/v1/integrations/cases/{case_id}
                if len(parts) == 5 and parts[3] == "cases":
                    record = service.get_case(context, parts[4])
                    if not record:
                        self._send_error("Case not found", status=404, request_id=request_id, code="not_found")
                    else:
                        self._send_json({"status": "success", "data": record, "request_id": request_id}, request_id=request_id)
                    return
                if len(parts) == 4 and parts[3] == "cases":
                    self._send_json({"status": "success", "data": service.list_cases(context), "request_id": request_id}, request_id=request_id)
                    return
                if len(parts) == 6 and parts[3] == "cases" and parts[5] == "audit":
                    self._send_json({"status": "success", "data": service.audit_for_case(context, parts[4]), "request_id": request_id}, request_id=request_id)
                    return
                if len(parts) == 4 and parts[3] == "monitoring":
                    self._send_json({"status": "success", "data": registry.monitoring_snapshot(context.tenant_id), "request_id": request_id}, request_id=request_id)
                    return
                if len(parts) == 4 and parts[3] == "agents":
                    self._send_json({"status": "success", "data": registry.list_agents(context.tenant_id), "request_id": request_id}, request_id=request_id)
                    return
                if len(parts) == 4 and parts[3] == "webhooks":
                    manager = WebhookManager(registry)
                    self._send_json({"status": "success", "data": manager.list_subscriptions(context.tenant_id), "request_id": request_id}, request_id=request_id)
                    return
                self._send_error("Integration endpoint not found", status=404, request_id=request_id, code="not_found")
            except PermissionError as exc:
                self._send_error(str(exc), status=403, request_id=request_id, code="forbidden")
            except KeyError:
                self._send_error("Case not found", status=404, request_id=request_id, code="not_found")
            except Exception:
                logger.exception("Integration GET failed request_id=%s", request_id)
                self._send_error("Internal server error", status=500, request_id=request_id, code="internal_error")
            return

        self._send_error("Endpoint not found", status=404, request_id=request_id, code="not_found")

    # ------------------------------------------------------------------ POST

    def do_POST(self):
        request_id = self._request_id()
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_error(str(exc), status=400, request_id=request_id, code="invalid_request")
            return
        except Exception:
            self._send_error("Malformed JSON payload", status=400, request_id=request_id, code="invalid_json")
            return

        if path.startswith("/api/v1/integrations/"):
            self._handle_integration_post(path, body, request_id)
            return

        try:
            if path == "/api/v1/reconcile":
                notice = body.get("notice", {})
                folio = body.get("folio", {})
                docs = body.get("supporting_docs")
                recon = fs.reconcile(notice, folio, supporting_docs=docs)
                self._send_json({"status": "success", "data": recon}, request_id=request_id)

            elif path == "/api/v1/rebuttal/draft":
                notice = body.get("notice", {})
                folio = body.get("folio", {})
                notes = body.get("custom_notes")
                docs = body.get("supporting_docs")
                recon = fs.reconcile(notice, folio, supporting_docs=docs)
                draft = fs.draft_rebuttal(notice, folio, recon, custom_instructions=notes)
                self._send_json({
                    "status": "success",
                    "engine": fs.llama_engine.last_engine_used,
                    "rebuttal_text": draft,
                }, request_id=request_id)

            elif path == "/api/v1/packet/generate":
                notice = body.get("notice", {})
                folio = body.get("folio", {})
                rebuttal_text = body.get("rebuttal_text", "")
                approved_by = body.get("approved_by", "Hotel Operations Manager")
                policy_text = body.get("policy_text")
                docs = body.get("supporting_docs")

                recon = fs.reconcile(notice, folio, supporting_docs=docs)
                pdf_bytes = fs.generate_pdf_packet(
                    notice, folio, recon, rebuttal_text,
                    approved_by=approved_by, policy_text=policy_text
                )
                digest = fs.audit_logger.calculate_sha256(pdf_bytes)
                self._send_json({
                    "status": "success",
                    "sha256": digest,
                    "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8"),
                }, request_id=request_id)

            elif path == "/api/v1/submission/bundle":
                notice = body.get("notice", {})
                folio = body.get("folio", {})
                packet_bytes = base64.b64decode(body.get("packet_base64", ""), validate=True)
                exhibit_files = {k: base64.b64decode(v, validate=True) for k, v in (body.get("exhibits") or {}).items()}
                recon = fs.reconcile(notice, folio, supporting_docs=body.get("supporting_docs"))
                zip_bytes, info = fs.build_submission_bundle(
                    notice, folio, recon, packet_bytes, exhibit_files,
                    portal_id=body.get("portal_id", "generic"))
                self._send_json({
                    "status": "success",
                    "bundle_sha256": info["bundle_sha256"],
                    "filename": info["filename"],
                    "size_bytes": info["size_bytes"],
                    "exhibit_map": info["exhibit_map"],
                    "bundle_base64": base64.b64encode(zip_bytes).decode("utf-8"),
                }, request_id=request_id)

            elif path == "/api/v1/submission/register":
                saved = fs.register_submission(body)
                self._send_json({"status": "success", "data": saved.to_dict()}, request_id=request_id)

            elif path == "/api/v1/submission/outcome":
                saved = fs.record_outcome(body)
                self._send_json({"status": "success", "data": saved.to_dict()}, request_id=request_id)

            elif path == "/api/v1/dispute/process":
                notice_raw = body.get("notice", {})
                folio_raw = body.get("folio", {})

                if isinstance(notice_raw, str):
                    notice_raw = base64.b64decode(notice_raw, validate=True)
                if isinstance(folio_raw, str):
                    folio_raw = base64.b64decode(folio_raw, validate=True)

                reviewer = body.get("reviewer_name", "BMS/PMS Integration")
                custom_notes = body.get("custom_notes")
                policy_text = body.get("policy_text")
                docs = body.get("supporting_docs")

                result = fs.process_dispute(
                    notice=notice_raw,
                    folio=folio_raw,
                    supporting_docs=docs,
                    custom_instructions=custom_notes,
                    reviewer_name=reviewer,
                    policy_text=policy_text,
                    generate_pdf=True
                )
                self._send_json({"status": "success", "data": result.to_dict()}, request_id=request_id)

            else:
                self._send_error("Unknown API endpoint", status=404, request_id=request_id, code="not_found")

        except PermissionError as exc:
            self._send_error(str(exc), status=403, request_id=request_id, code="forbidden")
        except KeyError:
            self._send_error("Requested resource not found", status=404, request_id=request_id, code="not_found")
        except ValueError as exc:
            self._send_error(str(exc), status=400, request_id=request_id, code="invalid_request")
        except Exception:
            logger.exception("Error processing API request request_id=%s", request_id)
            self._send_error("Internal server error", status=500, request_id=request_id, code="internal_error")

    def _handle_integration_post(self, path: str, body: Dict[str, Any], request_id: str):
        context, registry, service = self._require_integration(request_id)
        if not context:
            return
        parts = [p for p in path.split("/") if p]
        try:
            # /api/v1/integrations/cases
            if len(parts) == 4 and parts[3] == "cases":
                context.require_scope("cases:write")
                case_ref = IntegrationCaseRef(
                    tenant_id=context.tenant_id,
                    case_id=str(body.get("case_id") or body.get("external_case_id") or uuid.uuid4()),
                    external_system=body.get("external_system"),
                    external_case_id=body.get("external_case_id"),
                    external_folio_id=body.get("external_folio_id"),
                    external_transaction_id=body.get("external_transaction_id"),
                    property_id=body.get("property_id"),
                )
                if case_ref.property_id and context.property_ids and case_ref.property_id not in context.property_ids:
                    raise PermissionError("Property is not authorized for this credential")
                record = service.create_case(context, case_ref, notice=body.get("notice"), folio=body.get("folio"))
                self._send_json({"status": "success", "data": record, "request_id": request_id}, status=201, request_id=request_id)
                return

            # /api/v1/integrations/cases/{id}/documents
            if len(parts) == 6 and parts[3] == "cases" and parts[5] == "documents":
                data = base64.b64decode(str(body.get("content_base64") or ""), validate=True)
                result = service.upload_document(
                    context, parts[4], str(body.get("document_type") or ""),
                    str(body.get("filename") or "document.bin"), str(body.get("media_type") or "application/octet-stream"),
                    data, evidence_doc_type=body.get("evidence_doc_type"))
                self._send_json({"status": "success", "data": result, "request_id": request_id}, status=201, request_id=request_id)
                return

            # /api/v1/integrations/cases/{id}/reconcile|draft|process|packet
            if len(parts) == 6 and parts[3] == "cases" and parts[5] in ("reconcile", "draft", "process", "packet"):
                case_id = parts[4]
                action = parts[5]
                if action == "reconcile":
                    result = service.reconcile_case(context, case_id)
                elif action == "draft":
                    result = service.draft_rebuttal(context, case_id, custom_instructions=body.get("custom_notes"))
                elif action == "process":
                    result = service.process_case(context, case_id, custom_instructions=body.get("custom_notes"), policy_text=body.get("policy_text"))
                else:
                    result = service.generate_packet(
                        context, case_id, approved_by=str(body.get("approved_by") or ""),
                        approval_fingerprint=str(body.get("approval_fingerprint") or ""),
                        policy_text=body.get("policy_text"))
                self._send_json({"status": "success", "data": result, "request_id": request_id}, request_id=request_id)
                return

            # /api/v1/integrations/webhooks
            if len(parts) == 4 and parts[3] == "webhooks":
                context.require_scope("webhooks:manage")
                manager = WebhookManager(registry)
                subscription = manager.subscribe(
                    context.tenant_id, str(body.get("url") or ""), list(body.get("event_types") or []),
                    secret=body.get("secret"), description=str(body.get("description") or ""))
                self._send_json({"status": "success", "data": subscription, "request_id": request_id}, status=201, request_id=request_id)
                return

            # /api/v1/integrations/agents/{agent_id}/heartbeat
            if len(parts) == 6 and parts[3] == "agents" and parts[5] == "heartbeat":
                context.require_scope("agent:sync")
                agent = registry.agent_heartbeat(context.tenant_id, parts[4], version=str(body.get("version") or ""), status=str(body.get("status") or "online"))
                if not agent:
                    self._send_error("Agent is not active", status=403, request_id=request_id, code="agent_inactive")
                else:
                    self._send_json({"status": "success", "data": agent, "request_id": request_id}, request_id=request_id)
                return

            self._send_error("Integration endpoint not found", status=404, request_id=request_id, code="not_found")
        except PermissionError as exc:
            self._send_error(str(exc), status=403, request_id=request_id, code="forbidden")
        except KeyError:
            self._send_error("Case not found", status=404, request_id=request_id, code="not_found")
        except ValueError as exc:
            self._send_error(str(exc), status=400, request_id=request_id, code="invalid_request")
        except Exception:
            logger.exception("Integration POST failed request_id=%s", request_id)
            self._send_error("Internal server error", status=500, request_id=request_id, code="internal_error")

    def log_message(self, format, *args):
        logger.debug("%s - %s", self.address_string(), format % args)


def run_api_server(port: int = 8000, host: str = "0.0.0.0"):
    """Starts the FolioShield REST API server.

    ThreadingHTTPServer improves local integration concurrency, but this is
    still not a complete production deployment. Terminate TLS and apply
    network controls in front of it for production use.
    """
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, FolioShieldAPIHandler)
    print(f"FolioShield REST API listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down FolioShield REST API server...")
        httpd.server_close()


if __name__ == "__main__":
    port = int(os.getenv("API_PORT", "8000"))
    run_api_server(port=port)
