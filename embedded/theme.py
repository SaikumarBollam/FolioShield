"""
Host theming for embedded FolioShield.

A host application may supply a theme inside the *signed* embedded context
(or via server-side environment defaults). Theme values are strictly
validated before any CSS is emitted:

  * Colors must be hex (#RGB, #RRGGBB, or #RRGGBBAA).
  * Font family is restricted to a safe character set (no quotes/semicolons
    that could break out of the CSS declaration).
  * Logo URL must be HTTPS (or a data:image URI) with no quotes/spaces.
  * Brand name is plain text, HTML-escaped at render time.

Any missing/invalid value falls back to the FolioShield default theme.
Unsigned browser parameters are never accepted as theme input.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_SAFE_FONT = re.compile(r"^[A-Za-z0-9 ,\-_]+$")
_SAFE_LOGO = re.compile(r"^(https://|data:image/)[^\s\"'<>]+$")

DEFAULT_THEME: Dict[str, str] = {
    "primary_color": "#173B50",
    "accent_color": "#D5B77A",
    "background_color": "#F5F5F0",
    "text_color": "#252D32",
    "font_family": "sans-serif",
    "brand_name": "FolioShield",
    "logo_url": "",
    "border_radius": "8px",
}


@dataclass
class HostTheme:
    primary_color: str = DEFAULT_THEME["primary_color"]
    accent_color: str = DEFAULT_THEME["accent_color"]
    background_color: str = DEFAULT_THEME["background_color"]
    text_color: str = DEFAULT_THEME["text_color"]
    font_family: str = DEFAULT_THEME["font_family"]
    brand_name: str = DEFAULT_THEME["brand_name"]
    logo_url: str = DEFAULT_THEME["logo_url"]
    border_radius: str = DEFAULT_THEME["border_radius"]

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "HostTheme":
        """Build a validated theme; invalid/missing values keep defaults."""
        theme = cls()
        if not data:
            return theme
        for field_name in ("primary_color", "accent_color", "background_color", "text_color"):
            value = str(data.get(field_name) or "").strip()
            if _HEX_COLOR.match(value):
                setattr(theme, field_name, value)
        font = str(data.get("font_family") or "").strip()
        if font and len(font) <= 80 and _SAFE_FONT.match(font):
            theme.font_family = font
        brand = str(data.get("brand_name") or "").strip()
        if brand and len(brand) <= 60:
            theme.brand_name = brand
        logo = str(data.get("logo_url") or "").strip()
        if logo and len(logo) <= 500 and _SAFE_LOGO.match(logo):
            theme.logo_url = logo
        radius = str(data.get("border_radius") or "").strip()
        if re.match(r"^\d{1,2}px$", radius):
            theme.border_radius = radius
        return theme

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    def css(self) -> str:
        """CSS variables + scoped overrides. Values are pre-validated above."""
        return f"""
        <style>
        :root {{
            --fs-primary: {self.primary_color};
            --fs-accent: {self.accent_color};
            --fs-bg: {self.background_color};
            --fs-text: {self.text_color};
            --fs-font: {self.font_family};
            --fs-radius: {self.border_radius};
        }}
        html, body, [class*="css"] {{ font-family: var(--fs-font); }}
        .main-header, h1, h2, .stMarkdown h1, .stMarkdown h2 {{ color: var(--fs-primary) !important; font-family: var(--fs-font); }}
        .sub-header, p.sub-header, h3, h4, h5, .stMarkdown h3, .stMarkdown h4, .stMarkdown h5, [data-testid="stSubheader"] {{ color: var(--fs-accent) !important; }}
        .stTabs [data-baseweb="tab"] {{ border-radius: var(--fs-radius) var(--fs-radius) 0 0; }}
        .stButton > button[kind="primary"] {{ background-color: var(--fs-primary); border-color: var(--fs-primary); border-radius: var(--fs-radius); }}
        .stDownloadButton > button {{ border-radius: var(--fs-radius); }}
        a {{ color: var(--fs-accent); }}
        </style>
        """
