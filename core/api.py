"""
FolioShield Production REST API Server.
Zero-dependency HTTP server built with Python standard library (http.server)
with optional FastAPI enhancement if installed.

Enables programmatic, headless API integration with Property Management Systems (PMS like OPERA/Mews/Cloudbeds),
Building Management Systems (BMS), accounting ERPs, and dispute webhooks.

Endpoints:
    GET  /health
    POST /api/v1/reconcile
    POST /api/v1/rebuttal/draft
    POST /api/v1/packet/generate
    POST /api/v1/dispute/process
"""

import os
import json
import base64
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from typing import Dict, Any, Optional

from .client import FolioShield
from .config import config

logger = logging.getLogger(__name__)
fs = FolioShield()


class FolioShieldAPIHandler(BaseHTTPRequestHandler):
    """
    HTTP Request Handler serving FolioShield dispute defense endpoints.
    """

    def _set_headers(self, status: int = 200, content_type: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        """Handle CORS pre-flight."""
        self._set_headers(204)

    def _read_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length).decode("utf-8")
        return json.loads(raw)

    def _send_json(self, data: Dict[str, Any], status: int = 200):
        self._set_headers(status)
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def _send_error(self, message: str, status: int = 400):
        self._send_json({"status": "error", "message": message}, status=status)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/health", "/api/v1/health"):
            self._send_json({
                "status": "healthy",
                "service": "FolioShield Dispute Defense Engine",
                "version": "1.0.0",
                "environment": config.environment,
                "provider": fs.llama_engine.provider,
                "api_configured": fs.llama_engine.is_api_configured()
            })
        else:
            self._send_error(f"Endpoint '{parsed.path}' not found", status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()
        except Exception as e:
            self._send_error(f"Malformed JSON payload: {str(e)}", status=400)
            return

        try:
            if path == "/api/v1/reconcile":
                # Expects: {"notice": {...}, "folio": {...}, "supporting_docs": {...}}
                notice = body.get("notice", {})
                folio = body.get("folio", {})
                docs = body.get("supporting_docs")
                recon = fs.reconcile(notice, folio, supporting_docs=docs)
                self._send_json({"status": "success", "data": recon})

            elif path == "/api/v1/rebuttal/draft":
                # Expects: {"notice": {...}, "folio": {...}, "custom_notes": "...", "supporting_docs": {...}}
                notice = body.get("notice", {})
                folio = body.get("folio", {})
                notes = body.get("custom_notes")
                docs = body.get("supporting_docs")
                recon = fs.reconcile(notice, folio, supporting_docs=docs)
                draft = fs.draft_rebuttal(notice, folio, recon, custom_instructions=notes)
                self._send_json({
                    "status": "success",
                    "engine": fs.llama_engine.last_engine_used,
                    "rebuttal_text": draft
                })

            elif path == "/api/v1/packet/generate":
                # Expects: {"notice": {...}, "folio": {...}, "rebuttal_text": "...", "approved_by": "..."}
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
                    "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8")
                })

            elif path == "/api/v1/dispute/process":
                # Full end-to-end processing: expects {"notice": {...}, "folio": {...}}
                # Notice and folio can be dicts or base64 PDF bytes
                notice_raw = body.get("notice", {})
                folio_raw = body.get("folio", {})

                if isinstance(notice_raw, str):
                    notice_raw = base64.b64decode(notice_raw)
                if isinstance(folio_raw, str):
                    folio_raw = base64.b64decode(folio_raw)

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
                self._send_json({"status": "success", "data": result.to_dict()})

            else:
                self._send_error(f"Unknown API endpoint: {path}", status=404)

        except Exception as e:
            logger.exception("Error processing API request on %s", path)
            self._send_error(str(e), status=500)

    def log_message(self, format, *args):
        # Override standard http.server stderr spew to use standard logger
        logger.debug("%s - %s", self.address_string(), format % args)


def run_api_server(port: int = 8000, host: str = "0.0.0.0"):
    """Starts the FolioShield REST API server."""
    server_address = (host, port)
    httpd = HTTPServer(server_address, FolioShieldAPIHandler)
    print(f"FolioShield REST API listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down FolioShield REST API server...")
        httpd.server_close()


if __name__ == "__main__":
    port = int(os.getenv("API_PORT", "8000"))
    run_api_server(port=port)
