import copy
import unittest

from inference.espn_results import parse_scoreboard, team_name


def fixture():
    return {"events": [{"id": "401884768", "date": "2026-10-17T13:30Z",
        "status": {"type": {"name": "STATUS_FULL_TIME", "state": "post", "completed": True}},
        "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"displayName": "SC Paderborn 07"}, "score": "2"},
            {"homeAway": "home", "team": {"displayName": "Werder Bremen"}, "score": "2"},
        ]}],
    }]}


class EspnResultsTests(unittest.TestCase):
    def parse(self, payload):
        return parse_scoreboard(payload, league="Bundesliga", day="2026-10-17")

    def test_explicit_home_away_and_timezone(self):
        payload = fixture()
        payload["events"][0]["competitions"][0]["competitors"][1]["score"] = "1"
        row = self.parse(payload).iloc[0]
        self.assertEqual((row.home_team_norm, row.away_team_norm), ("werder bremen", "paderborn"))
        self.assertEqual((row.home_score, row.away_score), (1, 2))
        self.assertEqual(str(row.official_date), "2026-10-17 15:30:00")
        self.assertEqual(row.status, "FT")
        self.assertEqual(row.result_source, "espn_scoreboard")

    def test_non_final_statuses_are_not_settled(self):
        for name, completed, state in [
            ("STATUS_SECOND_HALF", False, "in"), ("STATUS_FULL_TIME", False, "post"),
            ("STATUS_ABANDONED", True, "post"), ("STATUS_POSTPONED", True, "post"),
            ("STATUS_FINAL_AET", True, "post"), ("STATUS_FINAL_PEN", True, "post"),
            ("STATUS_FULL_TIME", "true", "post"), ("STATUS_FULL_TIME", True, "in"),
        ]:
            with self.subTest(name=name, completed=completed):
                payload = fixture()
                payload["events"][0]["status"]["type"].update(name=name, completed=completed, state=state)
                self.assertEqual(self.parse(payload).iloc[0].status, "UNCONFIRMED")

    def test_invalid_scores_never_become_zero(self):
        for value in [None, "", "null", "-1", "1.5", True]:
            with self.subTest(value=value):
                payload = fixture()
                payload["events"][0]["competitions"][0]["competitors"][0]["score"] = value
                self.assertEqual(self.parse(payload).iloc[0].status, "UNCONFIRMED")

    def test_wrong_date_and_incomplete_payload(self):
        payload = fixture()
        payload["events"][0]["date"] = "2025-10-17T13:30Z"
        self.assertTrue(self.parse(payload).empty)
        with self.assertRaises(ValueError):
            self.parse({"error": "blocked"})

    def test_aliases_do_not_require_fuzzy_team_matching(self):
        self.assertEqual(team_name("Hamburg SV"), "hamburger sv")
        self.assertEqual(team_name("Borussia Mönchengladbach"), "borussia m gladbach")
        self.assertEqual(team_name("AS Roma"), "roma")
        self.assertEqual(team_name("Tottenham Hotspur"), "tottenham")
        self.assertEqual(team_name("Le Havre AC"), "le havre")

    def test_entire_matchday_is_retained(self):
        payload = fixture()
        payload["events"] = [copy.deepcopy(payload["events"][0]) for _ in range(10)]
        self.assertEqual(len(self.parse(payload)), 10)
