"""
Host-theme application for the Streamlit UI (extracted from app.py).

Theming rule (unchanged): host theme values are accepted only from the
signed embedded context or server-side env defaults (see
embedded.configuration.resolve_theme); otherwise the FolioShield default
theme in app.py's base CSS applies unchanged. This module only renders
the already-validated theme — validation lives in embedded.theme.
"""

from typing import Any, Optional


def resolve_active_theme(query_params: Any) -> Any:
    """Returns (theme, embedded_context, error_message).

    The env-default theme is resolved first and kept even when a supplied
    context token fails validation (the caller surfaces the rejection);
    theming itself never breaks the app.
    """
    from embedded.configuration import EmbeddedConfiguration

    cfg = EmbeddedConfiguration.from_env()
    theme = cfg.resolve_theme()
    token = query_params.get("fs_embed_token") if hasattr(query_params, "get") else None
    if isinstance(token, list):
        token = token[0] if token else None
    if not (cfg.enabled and token):
        return theme, None, None
    try:
        from embedded.context import validate_context_token

        context = validate_context_token(
            token, cfg.signing_secret, issuer=cfg.issuer,
            audience=cfg.audience, allowed_origins=cfg.allowed_origins or None,
            origin=query_params.get("fs_embed_origin") if hasattr(query_params, "get") else None)
        return cfg.resolve_theme(context.theme), context, None
    except Exception as exc:
        return theme, None, str(exc)


def theme_css(theme: Any) -> Optional[str]:
    """CSS variables block for a validated theme (None = keep defaults)."""
    if theme is None:
        return None
    return theme.css()
