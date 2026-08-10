from __future__ import annotations

import json
import os
from collections import defaultdict
from itertools import product
from pathlib import Path

import edge_v08b_reversion as observation_source
import edge_v10b_strategy_discovery as archive
from edge_v07_pregame_holdout import fit
from edge_v09_focused_reversion import apply_model

ENTRY_FRICTION = 1.0
EXIT_FRICTION = 0.5
DAILY_CAP = 1.0
A_RISK = 0.25
B_RISK = 0.25
E_BASE_RISK = 0.50


def group_game(rows):
    d = defaultdict(list)
    for r in rows:
        d[r['game_pk']].append(r)
    for v in d.values():
        v.sort(key=lambda x: x['ts'])
    return d


def group_ticker(rows):
    d = defaultdict(list)
    for r in rows:
        d[r['ticker']].append(r)
    for v in d.values():
        v.sort(key=lambda x: x['ts'])
    return d


def batting(r):
    return (r['side']==r['away'] and str(r['half']).lower()=='top') or (r['side']==r['home'] and str(r['half']).lower()=='bottom')


def qa(r):
    return 55 <= r['pregame_side'] < 65 and r['trailing'] and r['deficit'] in (1,2) and 4 <= r['inning'] <= 6 and r['drop_from_pregame'] >= 18 and r['edge_v09'] >= 5


def qb(r):
    return 45 <= r['pregame_side'] < 55 and r['trailing'] and r['deficit']==1 and 4 <= r['inning'] <= 6 and r['drop_from_pregame'] >= 10 and r['edge_v09'] >= 3 and batting(r)


def fixed_trade(entry, series, minutes, risk, code):
    future=[x for x in series if x['ts']>entry['ts']]
    if not future: return None
    target=entry['ts']+minutes*60
    out=next((x for x in future if x['ts']>=target), future[-1])
    ep=min(99.0,float(entry['ask'])+ENTRY_FRICTION)
    xp=max(0.0,float(out['bid'])-EXIT_FRICTION)
    roi=100*(xp/ep-1)
    return {'date':entry['date'],'game_pk':entry['game_pk'],'entry_ts':entry['ts'],'exit_ts':out['ts'],'code':code,'risk':risk,'roi':roi,'pnl_bankroll':risk*roi/100}


def first_ab(rows):
    gt=group_ticker(rows); seen_games=set(); out=[]
    for r in sorted(rows,key=lambda x:x['ts']):
        if r['game_pk'] in seen_games: continue
        if qa(r):
            t=fixed_trade(r,gt[r['ticker']],20,A_RISK,'A')
        elif qb(r):
            t=fixed_trade(r,gt[r['ticker']],30,B_RISK,'B')
        else:
            t=None
        if t:
            seen_games.add(r['game_pk']); out.append(t)
    return out


def first_quotes(rows):
    f={}
    for r in rows:
        f.setdefault(r['side'],r)
    return list(f.values()) if len(f)==2 else []


def e_trade(rows,cfg):
    fq=first_quotes(rows)
    if len(fq)!=2:return None
    fav=max(fq,key=lambda r:r['pregame_side']); dog=min(fq,key=lambda r:r['pregame_side'])
    if fav['pregame_side'] < cfg['pregame_min'] or fav['pregame_side'] >= cfg['pregame_max']:
        return None
    latest={fav['side']:fav,dog['side']:dog}; trigger=None; dog_at=None
    for r in rows:
        latest[r['side']]=r
        f=latest.get(fav['side']); d=latest.get(dog['side'])
        if not f or not d: continue
        if int(f['inning'] or 0)<=cfg['max_inning'] and float(f['ask'])>=cfg['trigger']:
            trigger=f; dog_at=d; break
    if trigger is None:return None
    fav_entry=min(99,float(fav['ask'])+ENTRY_FRICTION)
    fav_contracts=E_BASE_RISK*100/fav_entry
    hedge_risk=E_BASE_RISK*cfg['hedge_mult']
    dog_entry=min(99,float(dog_at['ask'])+ENTRY_FRICTION)
    dog_contracts=hedge_risk*100/dog_entry
    future=[r for r in rows if r['side']==dog['side'] and r['ts']>dog_at['ts']]
    dog_value=None; hedge_closed=False
    for r in future:
        bid=max(0,float(r['bid'])-EXIT_FRICTION)
        if bid>=dog_entry+cfg['target']:
            dog_value=dog_contracts*bid/100; hedge_closed=True; break
    if dog_value is None:
        dog_value=dog_contracts if dog['won'] else 0
    fav_value=fav_contracts if fav['won'] else 0
    cost=E_BASE_RISK+hedge_risk
    pnl=fav_value+dog_value-cost
    return {'date':fav['date'],'game_pk':fav['game_pk'],'entry_ts':fav['ts'],'exit_ts':rows[-1]['ts'],'code':'E','risk':cost,'roi':100*pnl/cost,'pnl_bankroll':pnl,'hedge_closed':hedge_closed}


def stats(ts):
    if not ts:return {'trades':0,'roi_pct':None,'pnl_pct_bankroll':0}
    risk=sum(t['risk'] for t in ts); pnl=sum(t['pnl_bankroll'] for t in ts)
    eq=peak=dd=0
    for t in sorted(ts,key=lambda x:x['entry_ts']):
        eq+=t['pnl_bankroll']; peak=max(peak,eq); dd=min(dd,eq-peak)
    return {'trades':len(ts),'roi_pct':round(100*pnl/risk,2),'pnl_pct_bankroll':round(pnl,3),'positive_pct':round(100*sum(t['pnl_bankroll']>0 for t in ts)/len(ts),2),'max_drawdown_pct_bankroll':round(dd,3)}


def portfolio(ab,e):
    by_day=defaultdict(list)
    for t in ab+e:
        by_day[t['date']].append(t)
    accepted=[]; skips=0
    for day,items in sorted(by_day.items()):
        used=0
        for t in sorted(items,key=lambda x:(x['entry_ts'], 0 if x['code']=='E' else 1)):
            if used+t['risk']>DAILY_CAP+1e-9:
                skips+=1; continue
            used+=t['risk']; accepted.append(t)
    s=stats(accepted)
    s['skipped_daily_cap']=skips
    s['breakdown']={c:stats([t for t in accepted if t['code']==c]) for c in ('A','B','E')}
    return s


def run(days=120):
    observation_source.markets_for_day=archive.combined_markets_for_day
    start,end,obs,coverage=observation_source.corrected_build_observations(days)
    dates=sorted({r['date'] for r in obs}); n=len(dates); c1=max(1,int(.5*n)); c2=max(2,int(.75*n))
    ds=set(dates[:c1]); vs=set(dates[c1:c2]); hs=set(dates[c2:])
    dev=[r for r in obs if r['date'] in ds]; val=[r for r in obs if r['date'] in vs]; hold=[r for r in obs if r['date'] in hs]
    p=fit(dev)
    for rows in (dev,val,hold):
        apply_model(rows,p)

    configs=[]
    bands=[(50,55),(55,60),(60,65),(65,70),(70,80),(50,80)]
    for trigger,mult,target,maxi,band in product([78,80,82,84,85,87,90],[.10,.15,.20,.25,.30],[3,5,7,10],[4,5,6],bands):
        pmin,pmax=band
        configs.append({'trigger':trigger,'hedge_mult':mult,'target':target,'max_inning':maxi,'pregame_min':pmin,'pregame_max':pmax})

    dev_games=group_game(dev); val_games=group_game(val); hold_games=group_game(hold)
    scored=[]
    for cfg in configs:
        de=[e_trade(g,cfg) for g in dev_games.values()]; de=[x for x in de if x]
        va=[e_trade(g,cfg) for g in val_games.values()]; va=[x for x in va if x]
        sd,sv=stats(de),stats(va)
        if sd['trades']<15 or sv['trades']<8 or sd['roi_pct'] is None or sv['roi_pct'] is None or min(sd['roi_pct'],sv['roi_pct'])<=0:
            continue
        score=min(sd['roi_pct'],sv['roi_pct'])+.15*(sd['roi_pct']+sv['roi_pct'])/2
        scored.append((score,cfg,sd,sv))
    scored.sort(key=lambda x:x[0],reverse=True)
    winner=scored[0] if scored else None

    hold_e=[e_trade(g,winner[1]) for g in hold_games.values()] if winner else []
    hold_e=[x for x in hold_e if x]
    hold_ab=first_ab(hold)
    e1_cfg={'trigger':80,'hedge_mult':.25,'target':5,'max_inning':5,'pregame_min':50,'pregame_max':100}
    e1=[e_trade(g,e1_cfg) for g in hold_games.values()]; e1=[x for x in e1 if x]

    result={'version':'EDGE-v1.5-E2-portfolio','period':[str(start),str(end)],'coverage':coverage,'configs_tested':len(configs),'robust_candidates':len(scored),'selected_e2':None,'e1_frozen':e1_cfg,'holdout':{},'guardrails':['E1 frozen; E2 selected without holdout','1% daily new-risk cap in portfolio replay','Historical simulation is not future performance']}
    if winner:
        result['selected_e2']={'config':winner[1],'development':winner[2],'validation':winner[3],'holdout':stats(hold_e)}
    result['holdout']={'A_B_only':portfolio(hold_ab,[]),'A_B_E1':portfolio(hold_ab,e1),'A_B_E2':portfolio(hold_ab,hold_e) if winner else None,'E1_alone':stats(e1),'E2_alone':stats(hold_e)}
    Path('edge_v15_e2_portfolio_results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    run(int(os.environ.get('EDGE_DAYS','120')))
