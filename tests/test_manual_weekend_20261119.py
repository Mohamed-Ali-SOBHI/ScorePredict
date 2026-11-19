import unittest
from datetime import datetime,timedelta,timezone
import pandas as pd
from production.manual_weekend_20261119 import collect,collect_receipt,prepare
from inference.live_tracking import build_tracking_rows
from inference.result_monitor import update_public_snapshot
from inference.portfolio_presets import DEFAULT_PORTFOLIO_NAME

HTML='''<p>UK time (GMT+0) Updated 15:02</p><table><tr><th>Match</th><th>Pick</th><th>Other</th><th>Bet365</th></tr>
<tr><td>15:00 Aston Villa Sunderland</td><td>1 · Aston Villa X · Draw 2 · Sunderland</td><td>9 9 9</td><td>1.80 3.75 4.33</td></tr>
<tr><td>15:00 Bournemouth Nottingham Forest</td><td>1 · Bournemouth X · Draw 2 · Nottingham Forest</td><td>9 9 9</td><td>1.91 3.60 4.00</td></tr></table>'''.encode()
NOW=datetime(2026,11,19,15,20,tzinfo=timezone.utc)

class ManualWeekend(unittest.TestCase):
    def scoreboard(self):
        return pd.DataFrame([dict(home_team_norm='aston villa',away_team_norm='sunderland',official_date='2026-11-21 16:00:00'),
                             dict(home_team_norm='bournemouth',away_team_norm='nottingham forest',official_date='2026-11-21 16:00:00')])
    def test_dynamic_column_and_freshness(self):
        q,_=collect(HTML,NOW);self.assertEqual(q['Aston Villa','Sunderland']['home'],1.80)
        with self.assertRaises(ValueError):collect(HTML,NOW+timedelta(hours=1))
        with self.assertRaises(ValueError):collect(HTML.replace(b'Bet365',b'Other'),NOW)
        receipt=dict(source='https://www.wbookie.com/en/odds?date=2026-11-21',book='Bet365',sourceUpdateUtc='2026-11-19T15:02:00+00:00',retrievedUtc='2026-11-19T15:05:00+00:00',sourceSha256='a'*64,quotes=[
            dict(home='Aston Villa',away='Sunderland',home_odds=1.8,draw_odds=3.75,away_odds=4.33),
            dict(home='Bournemouth',away='Nottingham Forest',home_odds=1.91,draw_odds=3.6,away_odds=4.0)])
        self.assertEqual(q,collect_receipt(receipt,NOW)[0])
        with self.assertRaises(ValueError):collect_receipt(receipt,NOW+timedelta(hours=1))
    def test_model_dedupe_and_early_display(self):
        bets,_=prepare(HTML,self.scoreboard(),NOW,pd.DataFrame());self.assertEqual(len(bets),2)
        old=build_tracking_rows(bets.iloc[[0]],portfolio_name=DEFAULT_PORTFOLIO_NAME)
        again,_=prepare(HTML,self.scoreboard(),NOW,old);self.assertEqual(len(again),1)
        ledger=build_tracking_rows(bets,portfolio_name=DEFAULT_PORTFOLIO_NAME)
        snapshot=update_public_snapshot({'meta':{'activePortfolio':DEFAULT_PORTFOLIO_NAME},'activity':[],'predictions':[]},ledger,portfolio_name=DEFAULT_PORTFOLIO_NAME,generated_at=NOW)
        self.assertEqual(len(snapshot['predictions']),2);self.assertTrue(all(p['earlyPublished'] for p in snapshot['predictions']))
        later=update_public_snapshot(snapshot,ledger,portfolio_name=DEFAULT_PORTFOLIO_NAME,generated_at=NOW+timedelta(minutes=1));self.assertEqual(len(later['predictions']),2)
if __name__=='__main__':unittest.main()
