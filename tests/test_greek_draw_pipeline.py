from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from inference import greek_draw_pipeline as greek
from inference.greek_draw_journal import merge_public_picks
from inference.publication_policy import apply_publication_policy


class GreekDrawTests(unittest.TestCase):
    clock = datetime(2026, 11, 28, 13, tzinfo=timezone.utc)
    header = "Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A\n"
    quote = "G1,28/11/2026,15:00,Volos NFC,Asteras Tripolis,2.5,3.3,2.65\n"

    def fixture(self):
        return {"id": "401896723", "competitions": [{"date": "2026-11-28T15:00Z",
            "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED"}},
            "competitors": [{"homeAway": "home", "team": {"displayName": "Volos NFC"}},
                            {"homeAway": "away", "team": {"displayName": "Asteras Tripoli"}}]}]}

    def test_window_quote_schedule_and_double_capture(self):
        raw = (self.header + self.quote * 2 + self.quote.replace("G1,", "E0,")).encode()
        matches = greek.candidates(raw, self.clock)
        self.assertEqual(len(matches), 1)
        event = self.fixture()
        checked = greek.verify_schedule(matches, [event, event])
        self.assertEqual(len(checked), 1)
        self.assertEqual(greek.selections(checked, [.30], self.clock), [])
        first = greek.selections(checked, [.42], self.clock)
        second = greek.selections(checked, [.43], self.clock + timedelta(minutes=10))
        public = merge_public_picks(first, second)
        published = [p for p in public if p["fixtureId"] == first[0]["fixtureId"]]
        self.assertEqual(published, first)
        self.assertEqual(greek.selections(checked, [.99], self.clock + timedelta(hours=2)), [])
        self.assertFalse(greek.candidates(raw, self.clock - timedelta(days=1)))
        self.assertFalse(greek.candidates(raw + self.quote.replace("3.3,", "3.7,").encode(), self.clock))
        self.assertFalse(greek.verify_schedule(matches, [event, {**event, "id": "123"}]))
        event["competitions"][0]["status"]["type"]["name"] = "STATUS_POSTPONED"
        self.assertFalse(greek.verify_schedule(matches, [event]))
        data = apply_publication_policy({"greekDrawStudy": public})
        self.assertEqual(apply_publication_policy(data)["greekDrawStudy"], public)
        self.assertEqual(data["summary"]["settledLiveBets"], 0)

    def test_supabase_first_write_wins_and_returns_original_receipt(self):
        table = {}
        def insert(_url, *, params, headers, json, timeout):
            self.assertEqual(params["on_conflict"], "snapshot_key")
            self.assertIn("ignore-duplicates", headers["Prefer"])
            for row in json:
                table.setdefault(row["snapshot_key"], row)
            return Mock()
        def read(*args, **kwargs):
            self.assertEqual(kwargs["params"]["portfolio_name"], "eq." + greek.PORTFOLIO)
            result = Mock()
            result.json.return_value = list(table.values())
            return result
        pick = merge_public_picks()[0]
        with patch.object(greek, "configuration", return_value=("https://test.invalid", "test")), \
                patch.object(greek.requests, "post", side_effect=insert), patch.object(greek, "get", side_effect=read):
            self.assertEqual(greek.persist([pick]), [pick])
            self.assertEqual(greek.persist([{**pick, "odds": 4.0}]), [pick])
            self.assertEqual(len(table), 1)

    def test_weekend_clubs_have_verified_local_images(self):
        assets = Path(__file__).resolve().parents[1] / "production/static/assets"
        records = json.loads((assets / "crests/sources.json").read_text(encoding="utf-8"))["clubs"]
        teams = [r for r in records if "/gre.1/" in r["sourceApi"]]
        self.assertEqual(len(teams), 14)
        mapping = (assets / "team-crests.js").read_text(encoding="utf-8")
        for row in teams:
            self.assertIn(f'"{row["name"]}": "{row["file"]}"', mapping)
            self.assertTrue((assets / "crests" / row["file"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
