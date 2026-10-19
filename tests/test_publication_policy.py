import copy
from datetime import datetime,timezone,timedelta
import unittest
from inference.publication_policy import apply_publication_policy,VERSION


class PublicationPolicyTests(unittest.TestCase):
    def snapshot(self):
        future=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        milan={'id':'original-milan','league':'Serie_A','date':'2026-10-18T18:00:00+02:00',
            'homeTeam':'AC Milan','awayTeam':'Atalanta','outcome':'draw','recommended':True,
            'odds':6.3,'status':'pending','profitUnits':0}
        bundes={'id':'original-bundes','league':'Bundesliga','date':'2026-10-17T13:30:00Z',
            'homeTeam':'Werder Bremen','awayTeam':'Paderborn','outcome':'draw','recommended':True,
            'odds':4.27,'status':'won','profitUnits':3.27}
        return {'meta':{'activePortfolio':'unchanged-model-version'},'summary':{'upcomingBets':3,'liveProfitUnits':3.27},
            'activity':[milan,bundes],
            'predictions':[dict(milan),dict(bundes,date=future),dict(milan,id='new-english',league='EPL')]}

    def test_only_active_public_strategies_are_displayed_without_changing_source_history(self):
        source=self.snapshot();frozen=copy.deepcopy(source)
        data=apply_publication_policy(source)
        self.assertEqual(source,frozen)
        self.assertEqual([p['league'] for p in data['predictions']],['Bundesliga'])
        self.assertEqual(data['summary']['upcomingBets'],1)
        self.assertEqual(data['meta']['publicationVersion'],VERSION)
        self.assertEqual(data['meta']['activePortfolio'],'unchanged-model-version')
        self.assertEqual(data['summary']['liveProfitUnits'],3.27)
        self.assertEqual([row['id'] for row in data['activity']],['original-bundes'])
        self.assertEqual(source['activity'][0]['id'],'original-milan')
        self.assertEqual(data,apply_publication_policy(data))

    def test_later_private_decisions_cannot_appear_as_public_history(self):
        source=self.snapshot()
        source['activity'].append(dict(source['activity'][0],id='private-forecast',homeTeam='Private home'))
        data=apply_publication_policy(source)
        self.assertEqual(len(data['activity']),1)

    def test_archived_pending_bet_is_not_public_or_counted_as_current(self):
        data=apply_publication_policy(self.snapshot())
        self.assertEqual(data['tracking']['pending'],0)
        self.assertEqual(data['tracking']['pendingAll'],0)
        self.assertEqual(data['summary']['pendingPredictions'],0)
        self.assertFalse(any(row['id']=='original-milan' for row in data['activity']))

    def test_retired_italian_strategy_stays_private_after_either_a_win_or_loss(self):
        for status,profit in [('lost',-1),('won',5.3)]:
            with self.subTest(status=status):
                source=self.snapshot();source['activity'][0].update(status=status,profitUnits=profit,historicalOnly=True)
                source['summary'].update(liveProfitUnits=3.27+profit,settledLiveBets=2)
                data=apply_publication_policy(source)
                self.assertFalse(any(row['id']=='original-milan' for row in data['activity']))
                self.assertEqual(data['summary']['liveProfitUnits'],3.27)
                self.assertEqual(data['summary']['settledLiveBets'],1)
                self.assertEqual(data['tracking']['verified'],1)
                self.assertEqual(data['tracking']['won'],1)
                self.assertEqual(data['tracking']['lost'],0)
                self.assertEqual(data['performance']['live']['profitUnits'],3.27)
                self.assertEqual(data['performance']['live']['roi'],3.27)
                self.assertEqual(source['activity'][0]['profitUnits'],profit)
                self.assertEqual(data,apply_publication_policy(data))

    def test_unknown_visible_profit_does_not_produce_an_invented_return(self):
        source=self.snapshot();source['activity'][1]['profitUnits']=None
        data=apply_publication_policy(source)
        self.assertIsNone(data['summary']['liveProfitUnits'])
        self.assertIsNone(data['performance']['live']['roi'])

    def test_bundesliga_home_and_away_bets_are_not_public(self):
        source=self.snapshot()
        for outcome in ['home','away']:
            source['predictions']=[dict(source['activity'][1],outcome=outcome)]
            self.assertEqual(apply_publication_policy(source)['predictions'],[])
        row=dict(source['activity'][1]);row.pop('outcome');row['outcomeLabel']='Match nul'
        source['predictions']=[row]
        self.assertEqual(len(apply_publication_policy(source)['predictions']),1)


if __name__=='__main__':unittest.main()
