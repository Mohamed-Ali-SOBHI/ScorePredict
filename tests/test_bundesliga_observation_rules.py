import unittest
import pandas as pd
from inference.bundesliga_observation import policy as register
from inference.bundesliga_observation_rules import evaluate,VERSION
COLUMNS=['fixture_id', 'decision_at_utc', 'kickoff_utc', 'quote_observed_at_utc', 'features_available_at_utc', 'bookmaker', 'price_type', 'filter_version', 'model_primary_sha256', 'model_secondary_sha256', 'p_primary_draw', 'p_binary_draw', 'odds_away', 'odds_draw', 'odds_home', 'selected', 'abstention_reason', 'stake_units', 'result_status', 'settled_at_utc', 'profit_units', 'closing_quote_at_utc', 'closing_odds_away', 'closing_odds_draw', 'closing_odds_home']

class FollowupRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.policy=register()

    def row(self,i=0,status='lost'):
        d=pd.Timestamp('2026-10-27T12:00:00Z')+pd.Timedelta(days=i*4)
        return dict(fixture_id=str(i),decision_at_utc=(d-pd.Timedelta(hours=2)).isoformat(),kickoff_utc=d.isoformat(),
          quote_observed_at_utc=(d-pd.Timedelta(hours=3)).isoformat(),features_available_at_utc=(d-pd.Timedelta(days=3)).isoformat(),
          bookmaker='B365',price_type='executable',filter_version=VERSION,model_primary_sha256=self.policy['primary_hashes'][0],model_secondary_sha256=self.policy['secondary_hashes'][0],
          p_primary_draw=.35,p_binary_draw=.32,odds_away=2,odds_draw=4,odds_home=3,
          selected=1,abstention_reason='',stake_units=1,result_status=status,
          settled_at_utc=(d+pd.Timedelta(hours=3)).isoformat() if status!='pending' else '',profit_units=3 if status=='won' else (-1 if status=='lost' else None),
          closing_quote_at_utc='',closing_odds_away=None,closing_odds_draw=None,closing_odds_home=None)

    def run_rows(self,rows,now='2028-01-01T00:00:00Z'):return evaluate(pd.DataFrame(rows,columns=COLUMNS),self.policy,now)

    def test_empty_before_and_after_deadline(self):
        self.assertEqual(self.run_rows([])['status'],'pas_de_nouveaux_paris')
        self.assertEqual(self.run_rows([],now='2029-01-01T00:00:00Z')['status'],'clore_non_confirmee')

    def test_budget_stop_does_not_reset_after_recovery(self):
        rows=[self.row(i) for i in range(10)]+[self.row(11,'won')]
        state=self.run_rows(rows);self.assertEqual(state['gain'],-7);self.assertEqual(state['status'],'abandon_budget')

    def test_pending_exposure_uses_remaining_budget(self):
        rows=[self.row(i) for i in range(9)]+[self.row(10,'pending')]
        self.assertEqual(self.run_rows(rows)['status'],'suspendre_exposition')

    def test_reject_duplicate_future_information_wrong_stakes_and_bad_profit(self):
        row=self.row()
        for rows in [[row,row],[dict(row,stake_units=2)],[dict(row,profit_units=3)],
                     [dict(row,quote_observed_at_utc='2026-11-01T00:00:00Z')],[dict(row,p_binary_draw=.1)],
                     [dict(row,model_primary_sha256='unknown')],[dict(row,price_type='average')],
                     [dict(row,decision_at_utc='2026-10-27T10:00:00')]]:
            self.assertEqual(self.run_rows(rows)['status'],'suspendre_integrite')

    def test_profitable_cohort_without_closing_evidence_is_not_promoted(self):
        rows=[self.row(i,'won' if i%3==0 else 'lost') for i in range(100)]
        state=self.run_rows(rows);self.assertEqual(state['status'],'clore_non_confirmee');self.assertEqual(state['closing_coverage'],0)

    def test_quota_waits_for_outstanding_results(self):
        rows=[self.row(i,'won' if i%3==0 else 'lost') for i in range(99)]+[self.row(99,'pending')]
        self.assertEqual(self.run_rows(rows)['status'],'attendre_reglement_cohorte')

if __name__=='__main__':unittest.main()
