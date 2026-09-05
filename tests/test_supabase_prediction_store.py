import unittest

import pandas as pd

from inference.supabase_prediction_store import portfolio_rows, recommended_rows, remote_records


class SupabasePredictionStoreTests(unittest.TestCase):
    def test_normalizes_csv_booleans_and_integer_scores(self) -> None:
        records = remote_records(
            pd.DataFrame(
                [
                    {
                        "snapshot_key": "fixture-1",
                        "fixture_id": "sportytrader:123",
                        "kickoff_utc": "2026-08-29T13:30:00Z",
                        "date": "2026-08-29 15:30:00",
                        "recommended": 1.0,
                        "match_found": "True",
                        "actual_home_score": 2.0,
                        "actual_away_score": 1.0,
                        "train_max_season": 2025.0,
                        "result_status": "won",
                    }
                ]
            )
        )

        self.assertTrue(records[0]["recommended"])
        self.assertTrue(records[0]["match_found"])
        self.assertEqual(records[0]["actual_home_score"], 2)
        self.assertEqual(records[0]["actual_away_score"], 1)
        self.assertEqual(records[0]["train_max_season"], 2025)
        self.assertEqual(records[0]["date"], "2026-08-29T15:30:00+02:00")
        self.assertEqual(records[0]["fixture_id"], "sportytrader:123")
        self.assertEqual(records[0]["kickoff_utc"], "2026-08-29T13:30:00+00:00")

    def test_keeps_only_recommended_rows_for_remote_storage(self) -> None:
        rows = recommended_rows(
            pd.DataFrame(
                [
                    {"snapshot_key": "bet", "recommended": True},
                    {"snapshot_key": "trend", "recommended": False},
                ]
            )
        )
        self.assertEqual(rows["snapshot_key"].tolist(), ["bet"])

    def test_isolates_each_portfolio_before_remote_storage(self) -> None:
        rows = portfolio_rows(
            pd.DataFrame(
                [
                    {"snapshot_key": "live", "portfolio_name": "production"},
                    {"snapshot_key": "shadow", "portfolio_name": "shadow_candidate"},
                ]
            ),
            "shadow_candidate",
        )
        self.assertEqual(rows["snapshot_key"].tolist(), ["shadow"])


if __name__ == "__main__":
    unittest.main()
