"""
FolioShield — Enterprise Design Tokens & Theme System.

Centralized source of truth for the FolioShield color system, semantic design
tokens, WCAG 2.2 AA contrast calculation, and Streamlit / Embedded CSS injection.

Brand Foundations:
  - Deep Navy:   #173B50  (Primary Brand, Headings, Primary CTA)
  - Muted Gold:  #D5B77A  (Decorative Brand Accent, Borders, Highlights)
  - Off-White:   #F5F5F0  (Canvas Surface, Light Background)
  - Steel Blue:  #697B83  (Secondary Brand Accent, Captions, Borders)
  - Charcoal:    #252D32  (Primary High-Contrast Body Text)

Accessible Contrast Adjustments (WCAG 2.2 AA >= 4.5:1 on light surfaces):
  - Accessible Gold Text (Light Mode):       #8A6A2F  (Contrast 4.59:1 on #F5F5F0)
  - Accessible Steel Blue Text (Light Mode): #596B75  (Contrast 5.07:1 on #F5F5F0)
  - Steel Blue Text (Dark Mode):             #8FA2AB  (Contrast 6.69:1 on #13191D)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


# -----------------------------------------------------------------------------
# 1. PALETTE DEFINITIONS (HEX CONSTANTS)
# -----------------------------------------------------------------------------
NAVY = "#173B50"
GOLD_DECOR = "#D5B77A"
GOLD_TEXT_LIGHT = "#8A6A2F"
OFF_WHITE = "#F5F5F0"
STEEL_BLUE_DECOR = "#697B83"
STEEL_BLUE_TEXT_LIGHT = "#596B75"
STEEL_BLUE_TEXT_DARK = "#8FA2AB"
CHARCOAL = "#252D32"

DARK_CANVAS = "#13191D"
DARK_SURFACE = "#22292E"
DARK_SIDEBAR = "#192025"
DARK_BORDER = "#3A454D"


# -----------------------------------------------------------------------------
# 2. CONTRAST CALCULATION UTILITIES (WCAG 2.2 AA SPECIFICATION)
# -----------------------------------------------------------------------------
def relative_luminance(hex_code: str) -> float:
    """Computes WCAG relative luminance for a 3-, 6-, or 8-digit hex code."""
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


def contrast_ratio(hex1: str, hex2: str) -> float:
    """Computes the WCAG contrast ratio (1.0:1 to 21.0:1) between two hex colors."""
    l1 = relative_luminance(hex1)
    l2 = relative_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def is_accessible_text(fg_hex: str, bg_hex: str, large_text: bool = False) -> bool:
    """Returns True if foreground text meets WCAG AA on the given background.

    - Normal text: >= 4.5:1
    - Large text (>= 18pt / 24px or bold >= 14pt / 18.66px): >= 3.0:1
    """
    threshold = 3.0 if large_text else 4.5
    return contrast_ratio(fg_hex, bg_hex) >= threshold


def is_accessible_ui(fg_hex: str, bg_hex: str) -> bool:
    """Returns True if a non-text UI control/border meets WCAG 2.2 AA (>= 3.0:1)."""
    return contrast_ratio(fg_hex, bg_hex) >= 3.0


def ensure_accessible_text_color(
    text_hex: str,
    bg_hex: str,
    fallback_light: str = OFF_WHITE,
    fallback_dark: str = CHARCOAL,
) -> str:
    """Returns text_hex if it meets 4.5:1 contrast on bg_hex; otherwise chooses

    whichever fallback provides the highest compliant contrast ratio.
    """
    if is_accessible_text(text_hex, bg_hex):
        return text_hex
    cr_light = contrast_ratio(fallback_light, bg_hex)
    cr_dark = contrast_ratio(fallback_dark, bg_hex)
    return fallback_light if cr_light >= cr_dark else fallback_dark


# -----------------------------------------------------------------------------
# 3. SEMANTIC DESIGN TOKENS
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class ThemeTokens:
    mode: str
    text_primary: str
    text_secondary: str
    text_accent: str  # WCAG AA compliant accent for headings / emphasis
    bg_canvas: str
    bg_surface: str
    bg_elevated: str
    bg_sidebar: str
    brand_primary: str
    brand_accent_decor: str
    border_subtle: str
    border_control: str
    border_accent: str
    # Semantic Feedback States (Text, Background, Border)
    status_success_text: str
    status_success_bg: str
    status_success_border: str
    status_warning_text: str
    status_warning_bg: str
    status_warning_border: str
    status_error_text: str
    status_error_bg: str
    status_error_border: str
    status_info_text: str
    status_info_bg: str
    status_info_border: str
    # Interactive & State Indicators
    focus_ring: str
    focus_halo: str
    button_primary_bg: str
    button_primary_text: str
    button_primary_border: str
    button_primary_hover_bg: str
    button_primary_hover_text: str
    button_secondary_bg: str
    button_secondary_text: str
    button_secondary_border: str
    button_secondary_hover_bg: str
    disabled_bg: str
    disabled_text: str
    disabled_border: str


LIGHT_TOKENS = ThemeTokens(
    mode="light",
    text_primary=CHARCOAL,  # #252D32 (12.8:1 on #F5F5F0)
    text_secondary=STEEL_BLUE_TEXT_LIGHT,  # #596B75 (5.07:1 on #F5F5F0)
    text_accent=GOLD_TEXT_LIGHT,  # #8A6A2F (4.59:1 on #F5F5F0)
    bg_canvas=OFF_WHITE,  # #F5F5F0
    bg_surface="#FFFFFF",  # #FFFFFF
    bg_elevated="#FFFFFF",
    bg_sidebar="#ECECE6",  # Subtle grey-beige
    brand_primary=NAVY,  # #173B50 (10.8:1 on #F5F5F0)
    brand_accent_decor=GOLD_DECOR,  # #D5B77A (Preserved for borders/decorations)
    border_subtle="#DCDCD4",
    border_control=STEEL_BLUE_DECOR,  # #697B83 (4.03:1 on #F5F5F0, >= 3:1)
    border_accent=GOLD_DECOR,
    status_success_text="#1B5E20",  # 7.06:1 on #EBF5EE
    status_success_bg="#EBF5EE",
    status_success_border="#2E7D32",
    status_warning_text="#7D5700",  # 6.11:1 on #FFF8E1
    status_warning_bg="#FFF8E1",
    status_warning_border="#FFB300",
    status_error_text="#B71C1C",  # 5.71:1 on #FDEBEB
    status_error_bg="#FDEBEB",
    status_error_border="#E53935",
    status_info_text="#0F4C81",  # 7.68:1 on #E8F0F5
    status_info_bg="#E8F0F5",
    status_info_border=NAVY,
    focus_ring=NAVY,  # Crisp Navy keyboard ring
    focus_halo="rgba(23, 59, 80, 0.20)",
    button_primary_bg=NAVY,
    button_primary_text=OFF_WHITE,  # 10.8:1
    button_primary_border=NAVY,
    button_primary_hover_bg="#0E2431",
    button_primary_hover_text="#FFFFFF",
    button_secondary_bg="#FFFFFF",
    button_secondary_text=NAVY,
    button_secondary_border=STEEL_BLUE_DECOR,
    button_secondary_hover_bg="#FAF9F5",
    disabled_bg="#E0E0E0",
    disabled_text="#757575",
    disabled_border="#BDBDBD",
)

DARK_TOKENS = ThemeTokens(
    mode="dark",
    text_primary=OFF_WHITE,  # #F5F5F0 (16.2:1 on #13191D)
    text_secondary=STEEL_BLUE_TEXT_DARK,  # #8FA2AB (6.69:1 on #13191D)
    text_accent=GOLD_DECOR,  # #D5B77A (9.19:1 on #13191D)
    bg_canvas=DARK_CANVAS,  # #13191D
    bg_surface=DARK_SURFACE,  # #22292E
    bg_elevated="#2A333A",
    bg_sidebar=DARK_SIDEBAR,  # #192025
    brand_primary=NAVY,  # #173B50
    brand_accent_decor=GOLD_DECOR,  # #D5B77A
    border_subtle=DARK_BORDER,  # #3A454D
    border_control=STEEL_BLUE_DECOR,  # #697B83 (4.02:1 on #13191D, >= 3.0:1)
    border_accent=GOLD_DECOR,
    status_success_text="#A5D6A7",  # 8.91:1 on #132E1B
    status_success_bg="#132E1B",
    status_success_border="#2E7D32",
    status_warning_text="#FFE082",  # 11.59:1 on #2E2611
    status_warning_bg="#2E2611",
    status_warning_border="#FFA000",
    status_error_text="#EF9A9A",  # 7.96:1 on #2E1414
    status_error_bg="#2E1414",
    status_error_border="#C62828",
    status_info_text="#90CAF9",  # 9.08:1 on #102433
    status_info_bg="#102433",
    status_info_border=NAVY,
    focus_ring=GOLD_DECOR,  # Crisp Gold keyboard ring on dark
    focus_halo="rgba(213, 183, 122, 0.25)",
    button_primary_bg=GOLD_DECOR,
    button_primary_text=NAVY,  # 6.14:1
    button_primary_border=GOLD_DECOR,
    button_primary_hover_bg="#E2CCA0",
    button_primary_hover_text="#0E2431",
    button_secondary_bg=DARK_SURFACE,
    button_secondary_text=OFF_WHITE,
    button_secondary_border=STEEL_BLUE_TEXT_DARK,
    button_secondary_hover_bg="#2D373D",
    disabled_bg="#1A2024",
    disabled_text="#6E7A82",
    disabled_border="#2D353B",
)


# -----------------------------------------------------------------------------
# 4. CSS STYLESHEET GENERATOR
# -----------------------------------------------------------------------------
def get_theme_css(dark_mode: bool = False) -> str:
    """Generates the enterprise-grade CSS stylesheet for FolioShield.

    Scoped properly to avoid broad element collisions, enforces WCAG 2.2 AA
    contrast, provides visible keyboard focus rings, and maintains visual hierarchy.
    """
    t = DARK_TOKENS if dark_mode else LIGHT_TOKENS

    return f"""
<style>
    :root {{
        /* Semantic Design Tokens */
        --fs-text-primary: {t.text_primary};
        --fs-text-secondary: {t.text_secondary};
        --fs-text-accent: {t.text_accent};
        --fs-bg-canvas: {t.bg_canvas};
        --fs-bg-surface: {t.bg_surface};
        --fs-bg-elevated: {t.bg_elevated};
        --fs-bg-sidebar: {t.bg_sidebar};
        --fs-brand-primary: {t.brand_primary};
        --fs-brand-accent: {t.brand_accent_decor};
        --fs-border-subtle: {t.border_subtle};
        --fs-border-control: {t.border_control};
        --fs-border-accent: {t.border_accent};
        --fs-focus-ring: {t.focus_ring};
        --fs-focus-halo: {t.focus_halo};
        --fs-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        --fs-radius: 8px;

        /* Compatibility Aliases */
        --fs-navy: {NAVY};
        --fs-gold: {GOLD_DECOR};
        --fs-offwhite: {OFF_WHITE};
        --fs-steelblue: {t.text_secondary};
        --fs-charcoal: {CHARCOAL};
        --fs-primary: {t.brand_primary};
        --fs-accent: {t.text_accent};
        --fs-secondary: {t.text_secondary};
        --fs-bg: {t.bg_canvas};
        --fs-text: {t.text_primary};
        --fs-card-bg: {t.bg_surface};
        --fs-sidebar-bg: {t.bg_sidebar};
        --fs-border: {t.border_subtle};
    }}

    /* Canvas & Streamlit App Shell */
    .stApp, [data-testid="stAppViewContainer"] {{
        background-color: var(--fs-bg-canvas) !important;
        color: var(--fs-text-primary) !important;
        font-family: var(--fs-font) !important;
    }}

    /* Header Bar — seamless with canvas background */
    header[data-testid="stHeader"] {{
        background-color: var(--fs-bg-canvas) !important;
        border-bottom: 1px solid var(--fs-border-subtle) !important;
    }}
    header[data-testid="stHeader"] svg,
    header[data-testid="stHeader"] button,
    header[data-testid="stHeader"] [data-testid="stToolbar"] {{
        color: var(--fs-text-primary) !important;
        fill: var(--fs-text-primary) !important;
    }}
    [data-testid="stDecoration"] {{
        display: none !important;
    }}

    /* Keyboard Focus Visibility (WCAG 2.2 Level AA SC 2.4.7 / 2.4.11) */
    a:focus-visible,
    button:focus-visible,
    input:focus-visible,
    textarea:focus-visible,
    select:focus-visible,
    [role="button"]:focus-visible,
    [role="tab"]:focus-visible,
    [tabindex]:focus-visible {{
        outline: 2px solid var(--fs-focus-ring) !important;
        outline-offset: 2px !important;
        box-shadow: 0 0 0 4px var(--fs-focus-halo) !important;
    }}

    /* Typography & Hierarchy — Scoped cleanly (no broad p, span, div collisions) */
    .stApp h1, .stMarkdown h1, .main-header {{
        font-size: 2.2rem !important;
        font-weight: 700 !important;
        color: {"var(--fs-text-primary)" if dark_mode else "var(--fs-brand-primary)"} !important;
        margin-bottom: 4px !important;
        letter-spacing: -0.015em !important;
        font-family: var(--fs-font) !important;
    }}
    .stApp h2, .stMarkdown h2 {{
        font-size: 1.45rem !important;
        font-weight: 700 !important;
        color: {"var(--fs-text-primary)" if dark_mode else "var(--fs-brand-primary)"} !important;
        border-bottom: 2px solid var(--fs-border-accent) !important;
        padding-bottom: 6px !important;
        margin-top: 20px !important;
        margin-bottom: 12px !important;
    }}
    .sub-header, p.sub-header {{
        font-size: 1.05rem !important;
        font-weight: 500 !important;
        color: var(--fs-text-secondary) !important;
        margin-bottom: 22px !important;
        line-height: 1.5 !important;
    }}
    .stApp h3, .stMarkdown h3, [data-testid="stSubheader"] {{
        font-size: 1.25rem !important;
        font-weight: 600 !important;
        color: {"var(--fs-text-accent)" if dark_mode else "var(--fs-brand-primary)"} !important;
        border-left: 3px solid var(--fs-border-accent) !important;
        padding-left: 10px !important;
        margin-top: 18px !important;
        margin-bottom: 8px !important;
    }}
    .stApp h4, .stMarkdown h4 {{
        font-size: 1.08rem !important;
        font-weight: 600 !important;
        color: var(--fs-text-secondary) !important;
        margin-top: 14px !important;
        margin-bottom: 6px !important;
    }}
    .stApp h5, .stMarkdown h5 {{
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        color: var(--fs-text-accent) !important;
        text-transform: uppercase !important;
        letter-spacing: 0.04em !important;
        margin-top: 10px !important;
        margin-bottom: 4px !important;
    }}
    .stMarkdown p, [data-testid="stMarkdownContainer"] p {{
        color: var(--fs-text-primary);
        line-height: 1.55;
    }}
    .stCaption, [data-testid="stCaptionContainer"] {{
        color: var(--fs-text-secondary) !important;
    }}

    /* Metric Cards & Proof Panels */
    div[data-testid="stMetric"] {{
        background-color: var(--fs-bg-surface) !important;
        border: 1px solid var(--fs-border-subtle) !important;
        border-top: 3px solid {"var(--fs-border-accent)" if dark_mode else "var(--fs-brand-primary)"} !important;
        border-radius: var(--fs-radius) !important;
        padding: 12px !important;
        box-shadow: {"0 2px 6px rgba(0, 0, 0, 0.35)" if dark_mode else "0 1px 3px rgba(23, 59, 80, 0.05)"};
    }}
    div[data-testid="stMetric"] label, div[data-testid="stMetric"] [data-testid="stMetricLabel"] {{
        color: var(--fs-text-secondary) !important;
        font-weight: 600 !important;
    }}
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
        color: {"var(--fs-text-accent)" if dark_mode else "var(--fs-brand-primary)"} !important;
        font-weight: 700 !important;
    }}
    div[data-testid="stMetricDelta"] {{
        font-size: 0.82rem !important;
        white-space: normal !important;
        word-break: break-word !important;
    }}
    div[data-testid="stExpander"] {{
        border: 1px solid var(--fs-border-subtle) !important;
        border-radius: var(--fs-radius) !important;
        background-color: var(--fs-bg-surface) !important;
    }}

    /* Form Controls & Inputs */
    input, textarea, select {{
        background-color: {"#1A2126" if dark_mode else "#FFFFFF"} !important;
        color: var(--fs-text-primary) !important;
        border: 1px solid var(--fs-border-control) !important;
        border-radius: var(--fs-radius) !important;
    }}
    input::placeholder, textarea::placeholder {{
        color: var(--fs-text-secondary) !important;
        opacity: 0.85;
    }}
    div[data-baseweb="select"] > div {{
        background-color: {"#1A2126" if dark_mode else "#FFFFFF"} !important;
        border: 1px solid var(--fs-border-control) !important;
        color: var(--fs-text-primary) !important;
    }}
    ul[data-baseweb="menu"], [data-baseweb="popover"] {{
        background-color: {"#1A2126" if dark_mode else "#FFFFFF"} !important;
        border: 1px solid var(--fs-border-subtle) !important;
    }}
    li[data-baseweb="menu-item"] {{
        color: var(--fs-text-primary) !important;
        background-color: {"#1A2126" if dark_mode else "#FFFFFF"} !important;
    }}
    li[data-baseweb="menu-item"]:hover {{
        background-color: {"#26333D" if dark_mode else "#F0F4F7"} !important;
        color: {"var(--fs-text-accent)" if dark_mode else "var(--fs-brand-primary)"} !important;
    }}

    /* File Uploader Dropzone */
    [data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] {{
        background-color: {"#1A2126" if dark_mode else "#FFFFFF"} !important;
        border: 2px dashed {"var(--fs-border-accent)" if dark_mode else "var(--fs-border-control)"} !important;
        border-radius: var(--fs-radius) !important;
        color: var(--fs-text-primary) !important;
        padding: 1.25rem !important;
    }}
    [data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"]:hover {{
        background-color: {"#222B31" if dark_mode else "#FAF9F5"} !important;
        border-color: {"#E2CCA0" if dark_mode else "var(--fs-brand-primary)"} !important;
    }}
    [data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] span,
    [data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] p,
    [data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] small {{
        color: var(--fs-text-primary) !important;
    }}
    [data-testid="stFileUploader"] section[data-testid="stFileUploaderDropzone"] button {{
        background-color: {"var(--fs-bg-surface)" if dark_mode else "#FFFFFF"} !important;
        border: 1px solid {"var(--fs-border-accent)" if dark_mode else "var(--fs-brand-primary)"} !important;
        color: {"var(--fs-text-accent)" if dark_mode else "var(--fs-brand-primary)"} !important;
        border-radius: var(--fs-radius) !important;
    }}

    /* Callout & Feedback Alert Boxes */
    div[data-testid="stAlert"] {{
        background-color: {t.status_info_bg} !important;
        border: 1px solid {t.status_info_border} !important;
        border-left: 4px solid {t.status_info_border} !important;
        border-radius: var(--fs-radius) !important;
        color: {t.status_info_text} !important;
    }}
    div[data-testid="stAlert"] p, div[data-testid="stAlert"] span {{
        color: {t.status_info_text} !important;
    }}

    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 6px;
        background-color: transparent;
        border-bottom: 2px solid var(--fs-border-accent);
    }}
    .stTabs [data-baseweb="tab"] {{
        padding: 8px 14px;
        font-size: 0.92rem;
        border-radius: var(--fs-radius) var(--fs-radius) 0px 0px;
        font-weight: 600;
        color: var(--fs-text-secondary);
        background-color: transparent;
    }}
    .stTabs [data-baseweb="tab"][aria-selected="true"] {{
        background-color: var(--fs-bg-surface) !important;
        color: {"var(--fs-text-accent)" if dark_mode else "var(--fs-brand-primary)"} !important;
        border-bottom: 3px solid var(--fs-border-accent) !important;
    }}
    .stTabs [data-baseweb="tab"]:hover {{
        background-color: {"#2D373D" if dark_mode else "#EDECE6"};
        color: {"var(--fs-text-accent)" if dark_mode else "var(--fs-brand-primary)"};
    }}

    /* Badges & Chips */
    .badge {{
        display: inline-block;
        padding: 3px 10px;
        font-size: 12px;
        font-weight: 600;
        border-radius: 4px;
        background-color: {"#1D262B" if dark_mode else "#EDECE6"};
        color: {"var(--fs-text-accent)" if dark_mode else "var(--fs-brand-primary)"};
        border: 1px solid var(--fs-border-accent);
    }}

    /* Buttons */
    .stButton > button[kind="primary"] {{
        background-color: {t.button_primary_bg} !important;
        border: 1px solid {t.button_primary_border} !important;
        color: {t.button_primary_text} !important;
        border-radius: var(--fs-radius) !important;
        font-weight: 700 !important;
        box-shadow: {"0 1px 4px rgba(213, 183, 122, 0.25)" if dark_mode else "0 1px 3px rgba(23, 59, 80, 0.15)"};
    }}
    .stButton > button[kind="primary"]:hover {{
        background-color: {t.button_primary_hover_bg} !important;
        border-color: {t.button_primary_hover_bg} !important;
        color: {t.button_primary_hover_text} !important;
    }}
    .stButton > button:not([kind="primary"]) {{
        border: 1px solid {t.button_secondary_border} !important;
        border-radius: var(--fs-radius) !important;
        color: {t.button_secondary_text} !important;
        background-color: {t.button_secondary_bg} !important;
    }}
    .stButton > button:not([kind="primary"]):hover {{
        background-color: {t.button_secondary_hover_bg} !important;
        border-color: var(--fs-border-accent) !important;
        color: {"var(--fs-text-accent)" if dark_mode else "var(--fs-brand-primary)"} !important;
    }}
    .stButton > button:disabled {{
        background-color: {t.disabled_bg} !important;
        color: {t.disabled_text} !important;
        border-color: {t.disabled_border} !important;
        opacity: 0.60 !important;
        cursor: not-allowed !important;
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: var(--fs-bg-sidebar) !important;
        border-right: 1px solid var(--fs-border-subtle) !important;
    }}
    section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{
        color: {"var(--fs-text-accent)" if dark_mode else "var(--fs-brand-primary)"} !important;
        border-bottom: none !important;
        border-left: none !important;
        padding-left: 0 !important;
    }}

    /* Toggle Switch */
    [data-testid="stToggle"] label > div[role="switch"][aria-checked="true"] {{
        background-color: var(--fs-brand-accent) !important;
    }}
    [data-testid="stToggle"] label > div[role="switch"][aria-checked="true"] > div {{
        background-color: var(--fs-brand-primary) !important;
    }}

    /* Data Tables */
    div[data-testid="stDataFrame"], table {{
        background-color: var(--fs-bg-surface) !important;
        border: 1px solid var(--fs-border-subtle) !important;
        border-radius: var(--fs-radius) !important;
    }}

    .fs-brand-logo {{ max-height: 44px; margin-bottom: 6px; }}
</style>
"""


# -----------------------------------------------------------------------------
# 5. EMBEDDED THEME RESOLUTION (BACKWARD-COMPATIBLE API)
# -----------------------------------------------------------------------------
def resolve_active_theme(query_params: Any) -> Any:
    """Returns (theme, embedded_context, error_message) for embedded host integration."""
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
            token,
            cfg.signing_secret,
            issuer=cfg.issuer,
            audience=cfg.audience,
            allowed_origins=cfg.allowed_origins or None,
            origin=query_params.get("fs_embed_origin") if hasattr(query_params, "get") else None,
        )
        return cfg.resolve_theme(context.theme), context, None
    except Exception as exc:
        return theme, None, str(exc)


def theme_css(theme: Any) -> Optional[str]:
    """CSS variables block for a validated theme (None = keep defaults)."""
    if theme is None:
        return None
    return theme.css()
