import unittest

import pandas as pd

from inference.supabase_prediction_store import recommended_rows, remote_records


class SupabasePredictionStoreTests(unittest.TestCase):
    def test_normalizes_csv_booleans_and_integer_scores(self) -> None:
        records = remote_records(
            pd.DataFrame(
                [
                    {
                        "snapshot_key": "fixture-1",
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


if __name__ == "__main__":
    unittest.main()
