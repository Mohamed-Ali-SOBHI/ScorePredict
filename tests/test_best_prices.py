from datetime import datetime, timedelta, timezone
import unittest

import pandas as pd

from inference import best_prices as prices
from inference.greek_draw_pipeline import selections
from inference.greek_draw_journal import merge_public_picks
from inference.public_additions import ENGLAND_HOME
from production.dashboard import DashboardService


class BestPricesTests(unittest.TestCase):
    now = datetime(2026, 11, 28, 10, tzinfo=timezone.utc)
    kickoff = "2026-11-28T14:30:00Z"

    def market(self, **changes):
        return dict(dict(league="Bundesliga", home="FSV Mainz 05", away="Union Berlin",
                         kickoff=self.kickoff, at=self.now.isoformat(), href="/cote/mainz-union-88",
                         offers=[dict(book="A", prices={"draw":4.6,"home_win":1.44}),
                                 dict(book="B", prices={"draw":4.8,"home_win":1.39})]), **changes)

    def offers(self, records, **changes):
        args = dict(league="Bundesliga",home="Mainz 05",away="Union Berlin",
                    kickoff=self.kickoff,outcome="draw",now=self.now)
        return prices.match_offers(records, **(args | changes))

    def test_best_named_offer_for_exact_fixture_and_selection(self):
        r=self.market()
        self.assertEqual([q['bookmaker'] for q in self.offers([r])],['B','A'])
        self.assertEqual(self.offers([r], outcome='home_win')[0]['bookmaker'],'A')
        self.assertFalse(self.offers([r],league='EPL'))
        self.assertFalse(self.offers([r],away='Schalke 04'))
        self.assertFalse(self.offers([r],kickoff="2026-11-28T14:31:00Z"))
        self.assertFalse(self.offers([r,r]))
        self.assertFalse(self.offers([r],now=self.now+timedelta(minutes=31)))
        self.assertFalse(self.offers([r],now=self.now-timedelta(minutes=1)))
        self.assertFalse(self.offers([r],now=datetime.fromisoformat(self.kickoff)))
        r['offers'].append(dict(book='B',prices={'draw':5}))
        self.assertEqual([q['bookmaker'] for q in self.offers([r])],['A'])

    def test_qualification_at_execution_and_immutable_model_inputs(self):
        row=dict(league="Bundesliga", selected_outcome="draw", team_name="Mainz 05", opponent_name="Union Berlin",
                 strategy_name="bundesliga_draw_4_00_10_00_nonfavorite_4__filter_original", recommended_bet="draw",
                 kickoff_utc=self.kickoff, selected_odds=4.50, predicted_probability=.30,market_probability=.20,
                 market_draw_odds_open=4.50, probability_note="sealed")
        original=pd.DataFrame([row])
        ticket=prices.apply_prices(original,[self.market()],self.now).iloc[0]
        self.assertEqual(ticket.selected_odds,4.8)
        self.assertEqual(ticket.market_draw_odds_open,4.50)
        self.assertEqual(ticket.predicted_probability,.30)
        self.assertAlmostEqual(ticket.expected_value,.44)
        self.assertEqual(prices.public_quote(ticket.probability_note)['publishedQuote']['referenceOdds'],4.50)
        self.assertEqual(original.iloc[0].selected_odds,4.50)
        over_cap = self.market(offers=[dict(book="A", prices={"draw":10.25}),dict(book="B", prices={"draw":9.80})])
        self.assertEqual(prices.apply_prices(original,[over_cap],self.now).iloc[0].selected_odds,10.25)
        self.assertFalse(prices.apply_prices(original,[],self.now).iloc[0].recommended_bet)
        low=self.market(offers=[dict(book="A",prices={"draw":3.4})])
        self.assertFalse(prices.apply_prices(original,[low],self.now).iloc[0].recommended_bet)
        original['recommended_bet']=""
        self.assertFalse(prices.apply_prices(original,[self.market()],self.now).iloc[0].recommended_bet)
        english=original.assign(league="EPL", strategy_name=ENGLAND_HOME, recommended_bet="home_win",
                                selected_outcome="home_win", predicted_probability=.8, selected_odds=1.4)
        self.assertAlmostEqual(prices.apply_prices(english,[self.market(league="EPL")],self.now).iloc[0].expected_value,.8*1.44*.98-1)

    def test_greek_ledger_and_historical_price(self):
        row=dict(homeTeam="Volos NFC",awayTeam="Asteras Tripolis",fixtureId="espn:8",date=self.kickoff,prices=(2.5,3.3,2.65))
        market=self.market(league="G1",home="Volos Nps",away="Asteras Tripolis")
        pick=selections([row],[.4],self.now,[market])[0]
        self.assertEqual(pick['odds'],4.8)
        self.assertFalse(selections([row],[.4],self.now,[]))
        again=selections([row],[.4],self.now,[self.market(league="G1",home="Volos Nps",away="Asteras Tripolis",
                                            offers=[dict(book="C",prices={"draw":5})])])[0]
        self.assertEqual(next(x for x in merge_public_picks([pick],[again]) if x['fixtureId']=="espn:8"),pick)
        old=dict(date=self.kickoff,league="EPL",homeTeam="Leeds",awayTeam="Coventry",outcome="home_win",odds=1.48)
        merged=DashboardService._merge_upcoming_predictions([dict(old,odds=1.52,publishedQuote={"bookmaker":"A"})],[old])
        self.assertEqual(merged[0]['odds'],1.48)
        self.assertNotIn('publishedQuote',merged[0])
