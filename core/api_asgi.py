"""
Production ASGI (FastAPI) REST API application for FolioShield.

Maintains 100% route, schema, error code, and security contract compatibility
with the reference handler in core.api, but executes on top of high-performance
ASGI servers (uvicorn/gunicorn) with OpenAPI autodoc and request correlation.
"""

import base64
import hmac
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sqlalchemy import text
from core.api import _RateLimiter, _legacy_auth_required
from core.api_schemas import schema_for_legacy, validate_body
from core.application.dispute_service import DisputeService
from core.audit_logger import AuditLogger
from core.client import FolioShield
from core.config import config
from core.infrastructure.database.session import get_db_session
from core.integrations.authentication import parse_bearer_token
from core.integrations.contracts import IntegrationCaseRef
from core.integrations.registry import IntegrationRegistry
from core.integrations.service import IntegrationService
from core.integrations.webhooks import WebhookManager

_rate_limiter = _RateLimiter(config.api_rate_limit_per_min)
_fs = FolioShield()
_dispute_service = DisputeService()


def create_app() -> FastAPI:
    """Application factory for FolioShield ASGI API."""
    app = FastAPI(
        title="FolioShield Enterprise API",
        version="1.1.0",
        description="Autonomous Dispute Defense & Chargeback Mitigation Engine API",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    if config.api_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.api_cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ------------------------------------------------------------- Middleware

    @app.middleware("http")
    async def request_correlation_and_rate_limit(request: Request, call_next: Any) -> Response:
        req_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = req_id

        # Public health endpoints bypass rate limiting and auth
        if request.url.path in (
            "/health",
            "/api/v1/health",
            "/health/liveness",
            "/health/readiness",
            "/docs",
            "/openapi.json",
            "/redoc",
        ):
            response = await call_next(request)
            response.headers["X-Request-Id"] = req_id
            return response

        # Rate limit check
        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.allow(client_ip):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded. Try again later.",
                    "code": "rate_limited",
                    "request_id": req_id,
                },
                headers={"X-Request-Id": req_id, "Retry-After": "60"},
            )

        response = await call_next(request)
        response.headers["X-Request-Id"] = req_id
        return response

    # ------------------------------------------------------------- Helper dependencies

    def _get_integration_service() -> IntegrationService:
        registry = IntegrationRegistry(root=config.integration_root)
        return IntegrationService(
            registry=registry,
            engine=_fs,
            webhooks=WebhookManager(registry),
        )

    def _verify_legacy_auth(authorization: Optional[str], request_id: str) -> None:
        if not _legacy_auth_required():
            return
        token = parse_bearer_token(authorization)
        if not token:
            raise HTTPException(
                status_code=401,
                detail={"error": "Authorization: Bearer <key> required", "code": "unauthorized", "request_id": request_id},
            )
        if config.api_key and hmac.compare_digest(token, config.api_key):
            return
        # Or valid integration credential
        registry = IntegrationRegistry(root=config.integration_root)
        ctx = registry.authenticate(token)
        if ctx:
            return
        raise HTTPException(
            status_code=403,
            detail={"error": "Invalid API key", "code": "forbidden", "request_id": request_id},
        )

    def _verify_integration_auth(authorization: Optional[str], request_id: str) -> Any:
        token = parse_bearer_token(authorization)
        if not token:
            raise HTTPException(
                status_code=401,
                detail={"error": "Bearer token required", "code": "unauthorized", "request_id": request_id},
            )
        registry = IntegrationRegistry(root=config.integration_root)
        principal = registry.authenticate(token)
        if not principal:
            registry.close()
            raise HTTPException(
                status_code=401,
                detail={"error": "Invalid or revoked credentials", "code": "unauthorized", "request_id": request_id},
            )
        ctx = principal.to_context(request_id=request_id)
        service = IntegrationService(registry=registry, engine=_fs, webhooks=WebhookManager(registry))
        return ctx, registry, service

    # ------------------------------------------------------------- Health Routes

    @app.get("/health")
    @app.get("/api/v1/health")
    def health_check(request: Request, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        payload: Dict[str, Any] = {
            "status": "healthy",
            "service": "FolioShield Dispute Defense Engine",
            "version": "1.1.0",
            "request_id": req_id,
        }
        token = parse_bearer_token(authorization)
        if token and config.api_key and hmac.compare_digest(token, config.api_key):
            payload.update({
                "environment": config.environment,
                "provider": _fs.llama_engine.provider,
                "api_configured": _fs.llama_engine.is_api_configured(),
            })
        return payload

    @app.get("/health/liveness")
    def liveness_check(request: Request) -> Dict[str, str]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return {"status": "alive", "request_id": req_id}

    @app.get("/health/readiness")
    def readiness_check(request: Request) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        db_status = "connected"
        try:
            with get_db_session() as session:
                session.execute(text("SELECT 1"))
        except Exception:
            db_status = "degraded"

        storage_status = "ready"
        try:
            _dispute_service.exhibit_store.verify_all(limit=1)
        except Exception:
            storage_status = "unavailable"

        overall_ready = db_status == "connected" and storage_status == "ready"
        if not overall_ready:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "unready",
                    "database": db_status,
                    "storage": storage_status,
                    "request_id": req_id,
                },
            )
        return {
            "status": "ready",
            "database": db_status,
            "storage": storage_status,
            "request_id": req_id,
        }

    # ------------------------------------------------------------- Legacy Dispute Routes

    @app.post("/api/v1/reconcile")
    async def reconcile_dispute(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        _verify_legacy_auth(authorization, req_id)
        body = await request.json()

        schema = schema_for_legacy("/api/v1/reconcile")
        if schema:
            res = validate_body(body, schema)
            if not res["ok"]:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "Request validation failed: " + "; ".join(e["message"] for e in res["errors"]), "code": "invalid_request", "request_id": req_id},
                )

        notice = body.get("notice", {})
        folio = body.get("folio", {})
        docs = body.get("supporting_docs")
        recon = _dispute_service.reconcile_dispute(notice, folio, supporting_docs=docs, actor="api")
        return {"status": "success", "data": recon}

    @app.post("/api/v1/rebuttal/draft")
    async def draft_rebuttal(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        _verify_legacy_auth(authorization, req_id)
        body = await request.json()

        schema = schema_for_legacy("/api/v1/rebuttal/draft")
        if schema:
            res = validate_body(body, schema)
            if not res["ok"]:
                raise HTTPException(
                    status_code=400,
                    detail={"error": "Request validation failed: " + "; ".join(e["message"] for e in res["errors"]), "code": "invalid_request", "request_id": req_id},
                )

        notice = body.get("notice", {})
        folio = body.get("folio", {})
        notes = body.get("custom_notes")
        docs = body.get("supporting_docs")
        recon = _dispute_service.reconcile_dispute(notice, folio, supporting_docs=docs, actor="api")
        draft = _dispute_service.draft_rebuttal(notice, folio, recon, custom_instructions=notes, actor="api")
        return {
            "status": "success",
            "data": {
                "rebuttal_text": draft,
                "engine_used": _fs.llama_engine.last_engine_used,
            },
        }

    @app.post("/api/v1/rebuttal/approve")
    @app.post("/api/v1/dispute/approve")
    async def approve_rebuttal(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        _verify_legacy_auth(authorization, req_id)
        body = await request.json()

        approved_by = body.get("approved_by")
        if not approved_by or not str(approved_by).strip():
            raise HTTPException(
                status_code=400,
                detail={"error": "Field 'approved_by' is required", "code": "invalid_request", "request_id": req_id},
            )

        approval = _dispute_service.approve_rebuttal(
            notice=body.get("notice", {}),
            folio=body.get("folio", {}),
            rebuttal_text=body.get("rebuttal_text", ""),
            approved_by=str(approved_by),
            policy_text=body.get("policy_text"),
            custom_instructions=body.get("custom_notes"),
            supporting_docs=body.get("supporting_docs"),
        )
        return {"status": "success", "data": approval}

    @app.post("/api/v1/packet/generate")
    async def generate_packet(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        _verify_legacy_auth(authorization, req_id)
        body = await request.json()

        notice = body.get("notice", {})
        folio = body.get("folio", {})
        recon = body.get("reconciliation", {})
        rebuttal = body.get("rebuttal_text", "")
        approval = body.get("approval")
        packet_format = body.get("packet_format", "executive")

        approved_by = approval.get("approved_by") if approval else None
        fp = approval.get("fingerprint") if approval else None

        pdf_bytes = _dispute_service.generate_packet(
            notice=notice,
            folio=folio,
            reconciliation=recon,
            rebuttal_text=rebuttal,
            approved_by=approved_by,
            approval_fingerprint=fp,
            packet_format=packet_format,
            policy_text=body.get("policy_text"),
            actor="api",
        )
        sha = AuditLogger.calculate_sha256(pdf_bytes)
        return {
            "status": "success",
            "data": {
                "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8"),
                "sha256": sha,
                "packet_format": packet_format,
                "approved": bool(approved_by and fp),
            },
        }

    @app.post("/api/v1/dispute/process")
    async def process_dispute(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        _verify_legacy_auth(authorization, req_id)
        body = await request.json()

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

        packet_resp = _fs.process_dispute(
            notice=notice_raw,
            folio=folio_raw,
            supporting_docs=docs,
            custom_instructions=custom_notes,
            reviewer_name=reviewer,
            policy_text=policy_text,
            generate_pdf=True,
        )
        return {"status": "success", "data": packet_resp.to_dict()}

    @app.post("/api/v1/submission/bundle")
    async def build_submission_bundle(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        _verify_legacy_auth(authorization, req_id)
        body = await request.json()

        notice = body.get("notice", {})
        folio = body.get("folio", {})
        packet_bytes = base64.b64decode(body.get("packet_base64", ""), validate=True)
        exhibit_files = {k: base64.b64decode(v, validate=True) for k, v in (body.get("exhibits") or {}).items()}
        recon = _fs.reconcile(notice, folio, supporting_docs=body.get("supporting_docs"))
        zip_bytes, info = _fs.build_submission_bundle(
            notice, folio, recon, packet_bytes, exhibit_files,
            portal_id=body.get("portal_id", "generic"),
        )
        return {
            "status": "success",
            "data": {
                "bundle_sha256": info["bundle_sha256"],
                "filename": info["filename"],
                "size_bytes": info["size_bytes"],
                "exhibit_map": info["exhibit_map"],
                "bundle_base64": base64.b64encode(zip_bytes).decode("utf-8"),
            },
        }

    # ------------------------------------------------------------- Integration Routes

    @app.get("/api/v1/integrations/cases")
    def list_integration_cases(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, _reg, svc = _verify_integration_auth(authorization, req_id)
        cases = svc.list_cases(ctx)
        return {"status": "success", "data": cases, "request_id": req_id}

    @app.post("/api/v1/integrations/cases", status_code=201)
    async def create_integration_case(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, _reg, svc = _verify_integration_auth(authorization, req_id)
        ctx.require_scope("cases:write")
        body = await request.json()

        case_ref = IntegrationCaseRef(
            tenant_id=ctx.tenant_id,
            case_id=str(body.get("case_id") or body.get("external_case_id") or uuid.uuid4()),
            external_system=body.get("external_system"),
            external_case_id=body.get("external_case_id"),
            external_folio_id=body.get("external_folio_id"),
            external_transaction_id=body.get("external_transaction_id"),
            property_id=body.get("property_id"),
        )
        if case_ref.property_id and ctx.property_ids and case_ref.property_id not in ctx.property_ids:
            raise HTTPException(status_code=403, detail={"error": "Property is not authorized", "code": "forbidden"})

        record = svc.create_case(ctx, case_ref, notice=body.get("notice"), folio=body.get("folio"))
        return {"status": "success", "data": record, "request_id": req_id}

    @app.get("/api/v1/integrations/cases/{case_id}")
    def get_integration_case(
        case_id: str,
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, _reg, svc = _verify_integration_auth(authorization, req_id)
        record = svc.get_case(ctx, case_id)
        if not record:
            raise HTTPException(
                status_code=404,
                detail={"error": "Case not found", "code": "not_found", "request_id": req_id},
            )
        return {"status": "success", "data": record, "request_id": req_id}

    @app.get("/api/v1/integrations/cases/{case_id}/audit")
    def get_integration_case_audit(
        case_id: str,
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, _reg, svc = _verify_integration_auth(authorization, req_id)
        audit_records = svc.audit_for_case(ctx, case_id)
        return {"status": "success", "data": audit_records, "request_id": req_id}

    @app.post("/api/v1/integrations/cases/{case_id}/documents", status_code=201)
    async def upload_case_document(
        case_id: str,
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, _reg, svc = _verify_integration_auth(authorization, req_id)
        body = await request.json()
        data = base64.b64decode(str(body.get("content_base64") or ""), validate=True)
        result = svc.upload_document(
            ctx,
            case_id,
            str(body.get("document_type") or ""),
            str(body.get("filename") or "document.bin"),
            str(body.get("media_type") or "application/octet-stream"),
            data,
            evidence_doc_type=body.get("evidence_doc_type"),
        )
        return {"status": "success", "data": result, "request_id": req_id}

    @app.post("/api/v1/integrations/cases/{case_id}/reconcile")
    def reconcile_case(
        case_id: str,
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, _reg, svc = _verify_integration_auth(authorization, req_id)
        result = svc.reconcile_case(ctx, case_id)
        return {"status": "success", "data": result, "request_id": req_id}

    @app.post("/api/v1/integrations/cases/{case_id}/draft")
    async def draft_case(
        case_id: str,
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, _reg, svc = _verify_integration_auth(authorization, req_id)
        body = await request.json()
        result = svc.draft_rebuttal(ctx, case_id, custom_instructions=body.get("custom_notes"))
        return {"status": "success", "data": result, "request_id": req_id}

    @app.get("/api/v1/integrations/monitoring")
    def get_monitoring(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, reg, _svc = _verify_integration_auth(authorization, req_id)
        snapshot = reg.monitoring_snapshot(ctx.tenant_id)
        return {"status": "success", "data": snapshot, "request_id": req_id}

    @app.get("/api/v1/integrations/agents")
    def list_agents(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, reg, _svc = _verify_integration_auth(authorization, req_id)
        agents = reg.list_agents(ctx.tenant_id)
        return {"status": "success", "data": agents, "request_id": req_id}

    @app.post("/api/v1/integrations/agents/{agent_id}/heartbeat")
    async def agent_heartbeat(
        agent_id: str,
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, reg, _svc = _verify_integration_auth(authorization, req_id)
        ctx.require_scope("agent:sync")
        body = await request.json()
        agent = reg.agent_heartbeat(
            ctx.tenant_id,
            agent_id,
            version=str(body.get("version") or ""),
            status=str(body.get("status") or "online"),
        )
        if not agent:
            raise HTTPException(status_code=403, detail={"error": "Agent inactive", "code": "agent_inactive"})
        return {"status": "success", "data": agent, "request_id": req_id}

    @app.get("/api/v1/integrations/webhooks")
    def list_webhooks(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, reg, _svc = _verify_integration_auth(authorization, req_id)
        mgr = WebhookManager(reg)
        subscriptions = mgr.list_subscriptions(ctx.tenant_id)
        return {"status": "success", "data": subscriptions, "request_id": req_id}

    @app.post("/api/v1/integrations/webhooks", status_code=201)
    async def create_webhook(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        ctx, reg, _svc = _verify_integration_auth(authorization, req_id)
        ctx.require_scope("webhooks:manage")
        body = await request.json()
        mgr = WebhookManager(reg)
        sub = mgr.subscribe(
            ctx.tenant_id,
            str(body.get("url") or ""),
            list(body.get("event_types") or []),
            secret=body.get("secret"),
            description=str(body.get("description") or ""),
        )
        return {"status": "success", "data": sub, "request_id": req_id}

    return app


app = create_app()
