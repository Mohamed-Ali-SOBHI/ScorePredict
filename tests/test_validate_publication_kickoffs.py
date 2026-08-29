from __future__ import annotations

import unittest

import pandas as pd

from inference.validate_publication_kickoffs import validate_publication_kickoffs


class PublicationKickoffValidationTests(unittest.TestCase):
    @staticmethod
    def _fixtures() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "date": "2026-08-29 15:30:00",
                    "league": "Bundesliga",
                    "home_team": "Spvgg Elversberg",
                    "away_team": "Bayer Leverkusen",
                }
            ]
        )

    def test_accepts_the_verified_paris_kickoff(self) -> None:
        snapshot = {
            "predictions": [
                {
                    "date": "2026-08-29T15:30:00+02:00",
                    "league": "Bundesliga",
                    "homeTeam": "Spvgg Elversberg",
                    "awayTeam": "Bayer Leverkusen",
                }
            ]
        }

        validate_publication_kickoffs(snapshot, self._fixtures())

    def test_blocks_the_six_hour_regression(self) -> None:
        snapshot = {
            "predictions": [
                {
                    "date": "2026-08-29T09:30:00+02:00",
                    "league": "Bundesliga",
                    "homeTeam": "Spvgg Elversberg",
                    "awayTeam": "Bayer Leverkusen",
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "Publication bloquée"):
            validate_publication_kickoffs(snapshot, self._fixtures())

    def test_blocks_a_public_date_without_an_explicit_timezone(self) -> None:
        snapshot = {
            "predictions": [
                {
                    "date": "2026-08-29 15:30:00",
                    "league": "Bundesliga",
                    "homeTeam": "Spvgg Elversberg",
                    "awayTeam": "Bayer Leverkusen",
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "fuseau horaire absent"):
            validate_publication_kickoffs(snapshot, self._fixtures())


if __name__ == "__main__":
    unittest.main()
