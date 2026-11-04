"""
Tests for FolioShield Enterprise UI Theme, Semantic Tokens, and WCAG Contrast.
"""

import unittest
from ui.theme import (
    NAVY,
    GOLD_DECOR,
    GOLD_TEXT_LIGHT,
    OFF_WHITE,
    STEEL_BLUE_DECOR,
    STEEL_BLUE_TEXT_LIGHT,
    STEEL_BLUE_TEXT_DARK,
    CHARCOAL,
    DARK_CANVAS,
    DARK_SURFACE,
    LIGHT_TOKENS,
    DARK_TOKENS,
    contrast_ratio,
    is_accessible_ui,
    ensure_accessible_text_color,
    get_theme_css,
)
from embedded.theme import HostTheme, DEFAULT_THEME


class TestThemeAccessibility(unittest.TestCase):
    def test_wcag_light_mode_contrast_ratios(self):
        """Light mode text must meet WCAG 2.2 AA (>= 4.5:1 for normal text)."""
        # Primary body text on off-white canvas
        cr_primary = contrast_ratio(CHARCOAL, OFF_WHITE)
        self.assertGreaterEqual(cr_primary, 4.5)
        self.assertGreater(cr_primary, 12.0)  # ~12.8:1

        # Primary brand Navy on off-white canvas
        cr_navy = contrast_ratio(NAVY, OFF_WHITE)
        self.assertGreaterEqual(cr_navy, 4.5)
        self.assertGreater(cr_navy, 10.0)  # ~10.8:1

        # Accessible Gold text on off-white canvas
        cr_gold_text = contrast_ratio(GOLD_TEXT_LIGHT, OFF_WHITE)
        self.assertGreaterEqual(cr_gold_text, 4.5)  # ~4.59:1

        # Accessible Gold text on pure white card
        cr_gold_white = contrast_ratio(GOLD_TEXT_LIGHT, "#FFFFFF")
        self.assertGreaterEqual(cr_gold_white, 4.5)  # ~5.02:1

        # Secondary text on off-white canvas
        cr_secondary = contrast_ratio(STEEL_BLUE_TEXT_LIGHT, OFF_WHITE)
        self.assertGreaterEqual(cr_secondary, 4.5)  # ~5.07:1

        # Secondary text on pure white card
        cr_secondary_white = contrast_ratio(STEEL_BLUE_TEXT_LIGHT, "#FFFFFF")
        self.assertGreaterEqual(cr_secondary_white, 4.5)  # ~5.55:1

        # Confirm old gold text failed (< 3:1)
        cr_old_gold = contrast_ratio(GOLD_DECOR, OFF_WHITE)
        self.assertLess(cr_old_gold, 2.0)

    def test_wcag_dark_mode_contrast_ratios(self):
        """Dark mode text must meet WCAG 2.2 AA (>= 4.5:1 for normal text)."""
        # Primary text on dark canvas
        cr_primary_canvas = contrast_ratio(OFF_WHITE, DARK_CANVAS)
        self.assertGreaterEqual(cr_primary_canvas, 7.0)  # AAA >= 7:1 (~16.2:1)

        # Primary text on dark card
        cr_primary_card = contrast_ratio(OFF_WHITE, DARK_SURFACE)
        self.assertGreaterEqual(cr_primary_card, 7.0)  # AAA >= 7:1 (~13.5:1)

        # Secondary text on dark canvas
        cr_secondary_canvas = contrast_ratio(STEEL_BLUE_TEXT_DARK, DARK_CANVAS)
        self.assertGreaterEqual(cr_secondary_canvas, 4.5)  # ~6.69:1

        # Secondary text on dark card
        cr_secondary_card = contrast_ratio(STEEL_BLUE_TEXT_DARK, DARK_SURFACE)
        self.assertGreaterEqual(cr_secondary_card, 4.5)  # ~5.56:1

        # Gold accent text on dark canvas
        cr_gold_canvas = contrast_ratio(GOLD_DECOR, DARK_CANVAS)
        self.assertGreaterEqual(cr_gold_canvas, 7.0)  # ~9.19:1

        # Gold accent text on dark card
        cr_gold_card = contrast_ratio(GOLD_DECOR, DARK_SURFACE)
        self.assertGreaterEqual(cr_gold_card, 7.0)  # ~7.64:1

    def test_wcag_non_text_ui_contrast(self):
        """Interactive control borders must meet WCAG 2.2 AA non-text contrast (>= 3.0:1)."""
        # Light mode interactive control border on canvas
        self.assertTrue(is_accessible_ui(STEEL_BLUE_DECOR, OFF_WHITE))  # ~4.03:1
        # Light mode interactive control border on white
        self.assertTrue(is_accessible_ui(STEEL_BLUE_DECOR, "#FFFFFF"))  # ~4.41:1

        # Dark mode interactive control border on dark canvas (>= 3.0:1)
        self.assertTrue(is_accessible_ui(DARK_TOKENS.border_control, DARK_CANVAS))
        self.assertGreaterEqual(contrast_ratio(DARK_TOKENS.border_control, DARK_CANVAS), 3.0)
        self.assertTrue(is_accessible_ui(GOLD_DECOR, DARK_CANVAS))  # ~9.19:1

    def test_status_feedback_contrasts(self):
        """Status alerts must have text with >= 4.5:1 contrast against their background."""
        for tokens in (LIGHT_TOKENS, DARK_TOKENS):
            self.assertGreaterEqual(contrast_ratio(tokens.status_success_text, tokens.status_success_bg), 4.5)
            self.assertGreaterEqual(contrast_ratio(tokens.status_warning_text, tokens.status_warning_bg), 4.5)
            self.assertGreaterEqual(contrast_ratio(tokens.status_error_text, tokens.status_error_bg), 4.5)
            self.assertGreaterEqual(contrast_ratio(tokens.status_info_text, tokens.status_info_bg), 4.5)

    def test_ensure_accessible_text_color(self):
        """Inaccessible text colors must be corrected automatically."""
        # White on light off-white is unreadable (fails) -> falls back to Charcoal
        resolved = ensure_accessible_text_color("#FFFFFF", OFF_WHITE)
        self.assertEqual(resolved, CHARCOAL)

        # Black on dark canvas is unreadable (fails) -> falls back to Off-white
        resolved_dark = ensure_accessible_text_color("#000000", DARK_CANVAS)
        self.assertEqual(resolved_dark, OFF_WHITE)

        # High-contrast color preserved as-is
        resolved_good = ensure_accessible_text_color(CHARCOAL, OFF_WHITE)
        self.assertEqual(resolved_good, CHARCOAL)

    def test_host_theme_contrast_validation(self):
        """HostTheme.from_dict must validate and correct low-contrast text inputs."""
        # Unreadable text color provided by host (e.g. white on off-white)
        bad_theme = HostTheme.from_dict({
            "background_color": "#F5F5F0",
            "text_color": "#FFFFFF",
        })
        self.assertEqual(bad_theme.text_color, DEFAULT_THEME["text_color"])
        self.assertGreaterEqual(contrast_ratio(bad_theme.text_color, bad_theme.background_color), 4.5)

        # Accessible host theme preserved
        good_theme = HostTheme.from_dict({
            "background_color": "#000000",
            "text_color": "#FFFFFF",
        })
        self.assertEqual(good_theme.text_color, "#FFFFFF")

    def test_css_generation(self):
        """get_theme_css must emit focus rings, accessible variables, and scoped typography."""
        light_css = get_theme_css(dark_mode=False)
        self.assertIn("--fs-text-primary: #252D32;", light_css)
        self.assertIn("--fs-text-accent: #8A6A2F;", light_css)
        self.assertIn("--fs-focus-ring: #173B50;", light_css)
        self.assertIn("a:focus-visible", light_css)
        self.assertIn("button:focus-visible", light_css)

        dark_css = get_theme_css(dark_mode=True)
        self.assertIn("--fs-text-primary: #F5F5F0;", dark_css)
        self.assertIn("--fs-text-accent: #D5B77A;", dark_css)
        self.assertIn("--fs-bg-canvas: #13191D;", dark_css)
        self.assertIn("--fs-focus-ring: #D5B77A;", dark_css)


if __name__ == "__main__":
    unittest.main()
