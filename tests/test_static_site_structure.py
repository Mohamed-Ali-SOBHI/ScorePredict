from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "production" / "static"


class StaticSiteStructureTests(unittest.TestCase):
    def test_landing_is_separate_from_the_dashboard_application(self) -> None:
        landing = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="./dashboard.html"', landing)
        self.assertIn('src="./assets/landing.js?v=journal-6"', landing)
        self.assertNotIn('src="./assets/app.js', landing)

    def test_landing_uses_only_local_assets_and_the_approved_logo(self) -> None:
        landing = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", landing)
        self.assertNotIn("https://", landing)
        self.assertNotIn("http://", landing)
        self.assertIn("scorepredict-logo-imagegen-v2.png", landing)
        self.assertNotIn("scorepredict-mark-concept-v1", landing)

    def test_landing_rivalry_carousel_keeps_the_dashboard_as_the_data_surface(self) -> None:
        landing = (STATIC / "index.html").read_text(encoding="utf-8")
        script = (STATIC / "assets" / "landing.js").read_text(encoding="utf-8")
        for element_id in {
            "decision-proof",
            "match-object",
            "object-primary",
            "object-secondary",
            "live-settled",
            "live-return",
            "memory-state",
            "test-return",
            "load-error",
        }:
            self.assertIn(f'id="{element_id}"', landing)
        self.assertIn("Grandes rivalités", landing)
        for club in {"FC Barcelone", "Real Madrid", "Liverpool", "Manchester City", "Arsenal", "Chelsea"}:
            self.assertIn(club, landing + script)
        self.assertIn("setupRivalryCarousel", script)
        self.assertIn("visibilitychange", script)
        self.assertIn("prefers-reduced-motion", script)
        self.assertIn("Ouvrir le journal", landing)
        self.assertNotIn("Les affiches qui font vibrer le football", landing)
        self.assertNotIn("carousel-controls", landing)
        self.assertNotIn("Démonstration", landing + script)
        self.assertNotIn("Données réelles à actualiser", landing + script)
        self.assertNotIn("renderDecision", script)
        self.assertNotIn("object-note", landing)
        self.assertNotIn("hero-foot", landing)
        self.assertNotIn("riskLabel", script)
        self.assertNotIn("object-probability", landing)

    def test_dashboard_keeps_the_dynamic_application_contract(self) -> None:
        dashboard = (STATIC / "dashboard.html").read_text(encoding="utf-8")
        required_ids = {
            "header-state",
            "published-time",
            "current-season",
            "hero-title",
            "analysis-summary",
            "pick-list",
            "no-pick",
            "why-panel",
            "result-list",
            "match-film",
            "load-error",
        }
        for element_id in required_ids:
            self.assertIn(f'id="{element_id}"', dashboard)
        self.assertIn('src="./assets/app.js?v=23"', dashboard)


if __name__ == "__main__":
    unittest.main()
