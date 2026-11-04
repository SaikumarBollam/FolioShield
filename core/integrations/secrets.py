"""
Secret protection for integration data at rest (Phase 2 P1).

Webhook signing secrets must be recoverable by the delivery engine (it
needs the raw secret to compute HMAC signatures), so they cannot be
stored as one-way hashes like credential secrets. They are encrypted
with Fernet (AES-128-CBC + HMAC) from the `cryptography` package:

- Key source: FOLIOSHIELD_WEBHOOK_SECRET_KEY (a Fernet key). When unset,
  a per-installation key is generated and stored at
  <integration root>/webhook_secret.key with 0600 permissions where the
  OS supports it. Losing that key makes stored secrets unrecoverable —
  subscriptions must then be rotated (the secret is shown once at
  subscribe time, and subscribers keep their own copy for verification).

Credential secrets are NOT handled here — they remain PBKDF2 hashes in
authentication.py (one-way by design).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_cached_key: Optional[bytes] = None
_key_file: Optional[Path] = None


def configure_key_file(path: Optional[str | Path]) -> None:
    """Points the generated-key fallback at the integration root."""
    global _key_file, _cached_key
    with _lock:
        _key_file = Path(path) if path else None
        _cached_key = None


def _load_key() -> bytes:
    global _cached_key
    with _lock:
        if _cached_key is not None:
            return _cached_key
        from cryptography.fernet import Fernet

        from ..config import config

        env_key = (config.webhook_secret_key or "").strip()
        if env_key:
            _cached_key = env_key.encode("utf-8")
            return _cached_key
        if _key_file is not None and _key_file.exists():
            _cached_key = _key_file.read_bytes().strip()
            return _cached_key
        key = Fernet.generate_key()
        if _key_file is not None:
            _key_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = _key_file.with_suffix(".tmp")
            tmp.write_bytes(key)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass  # Windows ACLs differ; the file lives in the data root.
            os.replace(tmp, _key_file)
        _cached_key = key
        return _cached_key


def encrypt_secret(secret: str) -> str:
    """Encrypts a secret for at-rest storage. Returns a Fernet token."""
    from cryptography.fernet import Fernet

    return Fernet(_load_key()).encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> Optional[str]:
    """Decrypts a stored token; None when the key is unavailable/wrong."""
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return Fernet(_load_key()).decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def secret_hint(secret: str) -> str:
    """Last-4 hint safe for display ('…ab12')."""
    text = secret or ""
    return f"…{text[-4:]}" if len(text) >= 4 else "…"
