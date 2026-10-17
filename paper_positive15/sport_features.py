"""Frozen causal sporting definition from the research experiment."""
import numpy as np
import pandas as pd
def historical_features(raw,panel):
    """All target features use only events ending <= target kickoff minus 72h.

    Adjust a historical game's xG by its opponent's strength estimated before
    that historical kickoff; then exponentially average the residuals. Venue
    features shrink same-venue means towards the team's overall mean (5 games).
    """
    r=raw.reset_index(drop=True).copy(); groups={}
    for key,g in r.groupby(['league','team_id'],sort=False):
        groups[key]=g.index.to_numpy()
    xf=r.team_xG.to_numpy(float);xa=r.opponent_xG.to_numpy(float)
    prior_for=np.full(len(r),1.35);prior_against=prior_for.copy()
    dates=r.date.to_numpy(dtype='datetime64[ns]');available=dates+np.timedelta64(2,'h')
    for key,ix in groups.items():
        ef=pd.Series(xf[ix]).ewm(alpha=.15,adjust=False).mean().to_numpy()
        ea=pd.Series(xa[ix]).ewm(alpha=.15,adjust=False).mean().to_numpy()
        # Inter-team simultaneous starts cannot affect one another.
        pos=np.searchsorted(available[ix],dates[ix],side='right')-1
        ok=pos>=0
        prior_for[ix[ok]]=ef[pos[ok]];prior_against[ix[ok]]=ea[pos[ok]]
    lookup={(m,int(t)):i for i,(m,t) in enumerate(zip(r.match_id,r.team_id))}
    opp=np.array([lookup[(m,int(t))] for m,t in zip(r.match_id,r.opponent_id)])
    r['adj_attack']=xf-prior_against[opp]
    r['adj_defense']=xa-prior_for[opp]
    r['npxg_diff']=r.team_npxG-r.opponent_npxG
    r['shot_quality']=r.team_xG/r.team_shots.replace(0,np.nan)
    r['opp_shot_quality']=r.opponent_xG/r.opponent_shots.replace(0,np.nan)
    r['finishing']=r.team_goals-r.team_xG
    r['defensive_finishing']=r.opponent_goals-r.opponent_xG
    r['points_surprise']=r.result.map({'w':3,'d':1,'l':0})-r.team_xpts
    basic=['adj_attack','adj_defense','npxg_diff','shot_quality','opp_shot_quality','finishing','defensive_finishing','points_surprise','team_xG','opponent_xG']
    snapshots={}
    for key,ix in groups.items():
        g=r.loc[ix]
        vals=g[basic].ewm(alpha=.15,adjust=False).mean().to_numpy()
        venue={}
        for is_home in (True,False):
            vg=g[g.is_home.eq(is_home)]
            venue[is_home]=(vg.index.to_numpy(),vg[['team_xG','opponent_xG']].ewm(alpha=.15,adjust=False).mean().to_numpy())
        snapshots[key]=(ix,vals,venue)
    output=[];audits=[]
    for row in panel.itertuples(index=False):
        cutoff=np.datetime64(pd.Timestamp(row.date)-pd.Timedelta(hours=72),'ns')
        pair=[]
        for is_home,team in ((True,row.team_id),(False,row.opponent_id)):
            ix,vals,venue=snapshots[(row.league,int(team))]
            k=np.searchsorted(available[ix],cutoff,side='right')-1
            if k>=0:
                v=vals[k].copy(); latest=available[ix[k]]
                assert latest<=cutoff
            else: v=np.full(len(basic),np.nan);latest=np.datetime64('NaT')
            vix,vvals=venue[is_home]
            vk=np.searchsorted(available[vix],cutoff,side='right')-1
            if vk>=0:
                shrink=(vk+1)/(vk+6)
                vg=shrink*(vvals[vk]-v[-2:])
            else: vg=np.zeros(2)
            pair.append(np.r_[v,vg])
            audits.append({'match_id':row.match_id,'team_id':int(team),'decision_time':str(cutoff),'last_result_available':str(latest),'observations':max(0,k+1)})
        h,a=pair; d={}
        for j,n in enumerate(basic):
            d[n+'_gap']=h[j]-a[j]
        d['adj_attack_total']=h[0]+a[0];d['adj_defense_total']=h[1]+a[1]
        d['venue_attack_gap']=h[-2]-a[-2];d['venue_defense_gap']=h[-1]-a[-1]
        d['venue_attack_total']=h[-2]+a[-2];d['venue_defense_total']=h[-1]+a[-1]
        output.append(d)
    return pd.DataFrame(output,index=panel.index),pd.DataFrame(audits)
