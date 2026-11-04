"""
Host theming for embedded FolioShield.

A host application may supply a theme inside the *signed* embedded context
(or via server-side environment defaults). Theme values are strictly
validated before any CSS is emitted:

  * Colors must be valid hex (#RGB, #RRGGBB, or #RRGGBBAA).
  * Text and background colors must satisfy WCAG 2.2 AA contrast (>= 4.5:1).
  * Font family is restricted to a safe character set (no quotes/semicolons
    that could break out of the CSS declaration).
  * Logo URL must be HTTPS (or a data:image URI) with no quotes/spaces.
  * Brand name is plain text, HTML-escaped at render time.

Any missing, invalid, or contrast-violating value falls back to the
accessible FolioShield default theme. Unsigned browser parameters are never
accepted as theme input.
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


def _relative_luminance(hex_code: str) -> float:
    """Computes relative luminance for contrast checking."""
    h = hex_code.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    elif len(h) >= 6:
        h = h[:6]
    else:
        return 0.0
    try:
        r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return 0.0

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """Computes the WCAG contrast ratio between two hex colors."""
    l1 = _relative_luminance(hex1)
    l2 = _relative_luminance(hex2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


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
        """Build a validated theme; invalid/missing values keep defaults.

        Also enforces WCAG 2.2 AA contrast: if text_color against background_color
        is < 4.5:1, text_color falls back to the higher-contrast accessible default.
        """
        theme = cls()
        if not data:
            return theme
        for field_name in ("primary_color", "accent_color", "background_color", "text_color"):
            value = str(data.get(field_name) or "").strip()
            if _HEX_COLOR.match(value):
                setattr(theme, field_name, value)

        # Accessibility check: text_color must have >= 4.5:1 contrast on background_color
        if _contrast_ratio(theme.text_color, theme.background_color) < 4.5:
            # Fall back to high-contrast dark or light default
            cr_dark = _contrast_ratio(DEFAULT_THEME["text_color"], theme.background_color)
            cr_light = _contrast_ratio("#F5F5F0", theme.background_color)
            theme.text_color = DEFAULT_THEME["text_color"] if cr_dark >= cr_light else "#F5F5F0"

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
        # Accessible text accent: on light background use dark gold #8A6A2F if accent is light gold
        is_light_bg = _relative_luminance(self.background_color) > 0.4
        text_accent = "#8A6A2F" if (is_light_bg and self.accent_color.upper() == "#D5B77A") else self.accent_color
        return f"""
        <style>
        :root {{
            --fs-primary: {self.primary_color};
            --fs-accent: {self.accent_color};
            --fs-bg: {self.background_color};
            --fs-text: {self.text_color};
            --fs-text-accent: {text_accent};
            --fs-font: {self.font_family};
            --fs-radius: {self.border_radius};
        }}
        html, body, [class*="css"] {{ font-family: var(--fs-font); }}
        .main-header, h1, h2, .stMarkdown h1, .stMarkdown h2 {{ color: var(--fs-primary) !important; font-family: var(--fs-font); }}
        .sub-header, p.sub-header, h3, h4, h5, .stMarkdown h3, .stMarkdown h4, .stMarkdown h5, [data-testid="stSubheader"] {{ color: var(--fs-text-accent) !important; }}
        .stTabs [data-baseweb="tab"] {{ border-radius: var(--fs-radius) var(--fs-radius) 0 0; }}
        .stButton > button[kind="primary"] {{ background-color: var(--fs-primary); border-color: var(--fs-primary); border-radius: var(--fs-radius); }}
        .stDownloadButton > button {{ border-radius: var(--fs-radius); }}
        a {{ color: var(--fs-text-accent); }}
        </style>
        """
