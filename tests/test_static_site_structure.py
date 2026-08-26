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
        self.assertIn('href="./assets/landing.css?v=v16"', landing)
        self.assertNotIn('src="./assets/app.js', landing)

    def test_how_it_works_follows_the_hero_and_explains_the_filters(self) -> None:
        landing = (STATIC / "index.html").read_text(encoding="utf-8")
        process_start = landing.index('id="fonctionnement"')
        results_start = landing.index('id="resultats"')
        self.assertLess(landing.index('id="journal"'), process_start)
        self.assertLess(process_start, results_start)
        self.assertIn('aria-label="Les cinq étapes du système"', landing)
        for copy in {
            "La méthode",
            "L’IA propose.",
            "Double IA",
            "Auto-censure",
            "Value Betting",
            "L'abstention",
        }:
            self.assertIn(copy, landing)

    def test_landing_uses_only_local_assets_and_the_approved_logo(self) -> None:
        landing = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", landing)
        self.assertNotIn("https://", landing)
        self.assertNotIn("http://", landing)
        self.assertIn("scorepredict-logo-v3.png", landing)
        self.assertNotIn("scorepredict-mark-concept-v1", landing)

    def test_landing_rivalry_carousel_keeps_the_dashboard_as_the_data_surface(self) -> None:
        landing = (STATIC / "index.html").read_text(encoding="utf-8")
        script = (STATIC / "assets" / "landing.js").read_text(encoding="utf-8")
        for element_id in {"match-object", "object-primary", "object-secondary"}:
            self.assertIn(f'id="{element_id}"', landing)
        for dashboard_only_id in {"live-settled", "live-return", "memory-state", "test-return", "load-error"}:
            self.assertNotIn(f'id="{dashboard_only_id}"', landing)
        self.assertIn("Grandes rivalités", landing)
        for club in {"FC Barcelone", "Real Madrid", "Liverpool", "Manchester City", "Arsenal", "Chelsea"}:
            self.assertIn(club, landing + script)
        self.assertIn("setupRivalryCarousel", script)
        self.assertIn("visibilitychange", script)
        self.assertIn("prefers-reduced-motion", script)
        self.assertIn("Ouvrir le journal", landing)
        self.assertIn("Tu dois savoir quand jouer.", landing)
        self.assertIn("Tu dois savoir quand te coucher.", landing)
        self.assertNotIn("Le journal avant match", landing)
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
        script = (STATIC / "assets" / "app.js").read_text(encoding="utf-8")
        required_ids = {
            "hero-title",
            "pick-list",
            "no-pick",
            "result-list",
            "tracking-pending",
            "tracking-verified",
            "load-error",
        }
        for element_id in required_ids:
            self.assertIn(f'id="{element_id}"', dashboard)
        self.assertIn('src="./assets/app.js?v=31"', dashboard)
        self.assertIn('href="./assets/styles.css?v=31"', dashboard)
        self.assertIn("Rendement des mises publiées", dashboard)
        self.assertIn('`${signed(returnPercent, decimalOne)} %`', script)
        self.assertIn("Soit ${signed(profit)}", script)
        self.assertIn('class="prediction-pitch"', dashboard)
        self.assertIn('class="prediction-choice"', script)
        self.assertIn('LEAGUE_COUNTRIES', script)
        self.assertIn('resultLabel(row.status, row.date)', script)
        self.assertIn('return "À venir"', script)
        for removed_copy in {
            "Lecture du choix",
            "Essais sur les saisons passées",
            "Comment une décision est publiée",
            "À garder en tête",
            "Historique permanent actif",
            "Données du jour prêtes",
            "décision publiée",
            "Choix du jour",
            "matchs examinés",
            "paris retenus",
            "Journal de décision",
        }:
            self.assertNotIn(removed_copy, dashboard + script)


if __name__ == "__main__":
    unittest.main()
