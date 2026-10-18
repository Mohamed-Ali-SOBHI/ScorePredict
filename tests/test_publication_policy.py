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

    def test_only_future_bundesliga_is_public_without_changing_recorded_history(self):
        source=self.snapshot();frozen=copy.deepcopy(source)
        data=apply_publication_policy(source)
        self.assertEqual(source,frozen)
        self.assertEqual([p['league'] for p in data['predictions']],['Bundesliga'])
        self.assertEqual(data['summary']['upcomingBets'],1)
        self.assertEqual(data['meta']['publicationVersion'],VERSION)
        self.assertEqual(data['meta']['activePortfolio'],'unchanged-model-version')
        self.assertEqual(data['summary']['liveProfitUnits'],3.27)
        milan=data['activity'][0]
        self.assertTrue(milan['historicalOnly'])
        for key in ['id','odds','status','profitUnits','date']:
            self.assertEqual(milan[key],source['activity'][0][key])
        self.assertEqual(data,apply_publication_policy(data))

    def test_later_private_decisions_cannot_appear_as_public_history(self):
        source=self.snapshot()
        source['activity'].append(dict(source['activity'][0],id='private-forecast',homeTeam='Private home'))
        data=apply_publication_policy(source)
        self.assertEqual(len(data['activity']),2)

    def test_archived_pending_bet_is_preserved_but_not_counted_as_current(self):
        data=apply_publication_policy(self.snapshot())
        self.assertEqual(data['tracking']['pending'],0)
        self.assertEqual(data['tracking']['pendingAll'],0)
        self.assertEqual(data['summary']['pendingPredictions'],0)
        self.assertEqual(data['activity'][0]['id'],'original-milan')
        self.assertEqual(data['activity'][0]['status'],'pending')

    def test_already_published_italian_result_is_kept_even_after_settlement(self):
        source=self.snapshot();source['activity'][0].update(status='lost',actualScore='1 - 0',profitUnits=-1)
        data=apply_publication_policy(source)
        self.assertEqual(data['activity'][0]['status'],'lost')
        self.assertEqual(data['activity'][0]['actualScore'],'1 - 0')
        self.assertEqual(data['activity'][0]['profitUnits'],-1)

    def test_bundesliga_home_and_away_bets_are_not_public(self):
        source=self.snapshot()
        for outcome in ['home','away']:
            source['predictions']=[dict(source['activity'][1],outcome=outcome)]
            self.assertEqual(apply_publication_policy(source)['predictions'],[])
        row=dict(source['activity'][1]);row.pop('outcome');row['outcomeLabel']='Match nul'
        source['predictions']=[row]
        self.assertEqual(len(apply_publication_policy(source)['predictions']),1)


if __name__=='__main__':unittest.main()
