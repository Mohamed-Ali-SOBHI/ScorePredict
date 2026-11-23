import json
import unittest
from datetime import datetime

from inference.venn_observation import CALIBRATION, decision, lower_probability, private_report
from inference.public_additions import BUNDESLIGA, ENGLAND_HOME


class VennObservationTests(unittest.TestCase):
    now = datetime.fromisoformat("2026-11-23T12:40:00+00:00")
    calibration = json.loads(CALIBRATION.read_text())

    def setUp(self):
        self.row = dict(id="sample", recommended=True, status="pending", league="EPL",
                        outcome="home_win", strategy=ENGLAND_HOME, homeTeam="Home", awayTeam="Away",
                        recordedAt="2026-11-22T22:45:00+00:00", date="2026-11-23T20:00:00+00:00",
                        odds=2.15, modelProbability=.508180170763721)

    def test_calibration_and_first_decision(self):
        self.assertAlmostEqual(lower_probability([(0.2, 1), (0.5, 0), (0.6, 1)], 0.5), 1/3)
        receipt = decision(self.row, self.calibration, self.now)
        self.assertLess(self.now, datetime.fromisoformat(receipt["date"]))
        self.assertFalse(receipt["recommended"])
        self.assertEqual(json.loads(receipt["probability_note"])["selected"],
                         receipt["predicted_probability"] * 2.15 * .98 > 1)
        receipt["result_status"] = "lost"
        summary = private_report([receipt], self.now)
        self.assertEqual(summary["reference"]["profit"], -1)

    def test_only_future_open_active_tickets(self):
        for change in (dict(status="lost"), dict(date=self.now.isoformat()), dict(recommended=False),
                       dict(strategy=BUNDESLIGA, league="Bundesliga", outcome="draw"),
                       dict(date="2027-08-01T12:00:00Z")):
            with self.subTest(change=change):
                self.assertIsNone(decision(dict(self.row, **change), self.calibration, self.now))

    def test_frozen_calibration_matches_research_for_each_active_strategy(self):
        for outcome, probability, expected in [
            ("draw", .365768998861313, .47058823529411764),
            ("away_win", .368626194934729, .34838709677419355),
            ("home_win", .6063827456946, .5507246376811594),
        ]:
            self.assertAlmostEqual(lower_probability(self.calibration[outcome], probability), expected)
