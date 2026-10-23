"""Contraste dos tokens de cor dos temas (WCAG 2.2 AA) — sem Qt (Prompt Mestre §14 e §46)."""

import unittest

from app.brand import COLORS
from app.ui import tokens


class TokenContrastTest(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(tokens.contrast_ratio("#000000", "#FFFFFF"), 21.0, places=2)
        self.assertAlmostEqual(tokens.contrast_ratio("#FFFFFF", "#FFFFFF"), 1.0, places=2)
        # o verde da marca sobre branco não atinge 4,5:1 — motivo da variante de texto
        self.assertLess(tokens.contrast_ratio(COLORS["green"], "#FFFFFF"), 4.5)

    def test_both_themes_meet_minimums(self):
        for name, theme in tokens.THEMES.items():
            with self.subTest(tema=name):
                self.assertEqual(tokens.contrast_failures(theme), [])

    def test_themes_have_same_tokens(self):
        self.assertEqual(set(tokens.LIGHT), set(tokens.DARK))

    def test_brand_palette_preserved(self):
        """A paleta oficial não muda; o azul da marca continua no botão principal e na navegação."""
        self.assertEqual(COLORS["blue"], "#1460F2")
        for theme in tokens.THEMES.values():
            self.assertEqual(theme["accent_fill"], COLORS["blue"])
            self.assertEqual(theme["nav_active"], COLORS["blue"])

    def test_invalid_color(self):
        with self.assertRaises(ValueError):
            tokens.luminance("#FFF")


if __name__ == "__main__":
    unittest.main()
