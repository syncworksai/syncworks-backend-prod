from __future__ import annotations

import json, os, re, time
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path
import requests

from edge_v18_multisport_discovery import (
    series_list, classify_series, markets_for_series, build_market_record,
    q_at, side_rows, side_pre, side_won, stats as base_stats,
    ENTRY_FRICTION, EXIT_FRICTION,
)

S=requests.Session(); S.headers.update({'User-Agent':'SyncWorks-EDGE-state-sports/2.0'})

LEAGUES={
    'BASKETBALL':[('NBA','basketball','nba'),('WNBA','basketball','wnba')],
    'FOOTBALL':[('NFL','football','nfl'),('NCAAF','football','college-football')],
}

def getj(url,params=None,timeout=30):
    r=S.get(url,params=params,timeout=timeout); r.raise_for_status(); return r.json()

def norm(s):return re.sub(r'[^a-z0-9]+','',str(s or '').lower())
def parse_iso(v):
    try:return datetime.fromisoformat(str(v).replace('Z','+00:00')).astimezone(timezone.utc)
    except:return None

def market_team_text(m):
    return ' '.join(str(m.get(k) or '') for k in ('yes_sub_title','title','subtitle','event_ticker','ticker')).lower()

def espn_games(sport,league,date):
    try:return getj(f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard',{'dates':date}).get('events',[])
    except:return []
def espn_summary(sport,league,event_id):
    try:return getj(f'https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary',{'event':event_id})
    except:return {}

def match_game(m,close):
    text=market_team_text(m)
    dates={(close-timedelta(days=1)).strftime('%Y%m%d'),close.strftime('%Y%m%d'),(close+timedelta(days=1)).strftime('%Y%m%d')}
    for bucket,defs in LEAGUES.items():
        for label,sport,league in defs:
            for d in dates:
                for e in espn_games(sport,league,d):
                    comp=((e.get('competitions') or [{}])[0]); teams=[]
                    for c in comp.get('competitors') or []:
                        t=c.get('team') or {}; teams.append((c.get('homeAway'),t.get('displayName') or '',t.get('abbreviation') or ''))
                    if len(teams)!=2:continue
                    score=0
                    for _,name,abbr in teams:
                        if norm(name) in norm(text) or (abbr and abbr.lower() in text):score+=1
                    if score<1:continue
                    # identify YES team by strongest text match
                    yes=None
                    for ha,name,abbr in teams:
                        if norm(name) in norm(text) or (abbr and re.search(rf'\b{re.escape(abbr.lower())}\b',text)):yes=(ha,name,abbr)
                    if not yes:continue
                    return {'label':label,'sport':sport,'league':league,'event_id':e.get('id'),'teams':teams,'yes_team':yes}
    return None

def state_timeline(game):
    x=espn_summary(game['sport'],game['league'],game['event_id']); plays=x.get('plays') or []
    out=[]
    home_name=next(n for ha,n,a in game['teams'] if ha=='home'); away_name=next(n for ha,n,a in game['teams'] if ha=='away')
    yes_home=game['yes_team'][0]=='home'
    for p in plays:
        wall=parse_iso(p.get('wallclock'))
        if not wall:continue
        try:hs=int(p.get('homeScore')); aw=int(p.get('awayScore'))
        except:continue
        period=int((p.get('period') or {}).get('number') or p.get('period') or 0)
        clock=(p.get('clock') or {}).get('displayValue') if isinstance(p.get('clock'),dict) else str(p.get('clock') or '')
        mm=ss=0
        if ':' in clock:
            try:mm,ss=[int(float(z)) for z in clock.split(':')[:2]]
            except:pass
        # approximate regulation seconds remaining
        if game['sport']=='basketball':
            per_len=12*60 if game['league']=='nba' else (10*60 if game['league']=='wnba' else 20*60)
            total_periods=4 if game['league'] in {'nba','wnba'} else 2
        else:
            per_len=15*60; total_periods=4
        remaining=max(0,(total_periods-period)*per_len+mm*60+ss)
        margin=(hs-aw) if yes_home else (aw-hs)
        out.append({'ts':int(wall.timestamp()),'margin':margin,'period':period,'remaining':remaining})
    out.sort(key=lambda z:z['ts']); return out

def state_at(tl,ts):
    z=None
    for s in tl:
        if s['ts']<=ts:z=s
        else:break
    return z

def exit_value(contracts,rs,after,target,maxm,won):
    cut=after+maxm*60
    for r in rs:
        if r['ts']<=after:continue
        if r['ts']>cut:break
        b=max(0,float(r['bid'])-EXIT_FRICTION)
        if b>=target:return contracts*b/100,True
    q=q_at(rs,cut)
    if q:return contracts*max(0,float(q['bid'])-EXIT_FRICTION)/100,False
    return (contracts if won else 0),False

def replay(e,c):
    side=e['fav_side']; p=side_pre(e,side)
    if not(c['pre_min']<=p<c['pre_max']):return None
    rs=[r for r in side_rows(e,side) if r['ts']>=e['baseline_ts']]
    for r in rs:
        if p-r['ask']<c['drop']:continue
        st=state_at(e['timeline'],r['ts'])
        if not st:continue
        if not(c['margin_min']<=st['margin']<=c['margin_max']):continue
        if st['remaining']<c['min_remaining_sec']:continue
        px=min(99,r['ask']+ENTRY_FRICTION); ctr=100/px
        val,hit=exit_value(ctr,rs,r['ts'],px+c['target'],c['maxm'],side_won(e,side)); pnl=val-1
        return {'ticker':e['ticker'],'close_ts':e['close_ts'],'cost':1,'pnl':pnl,'roi_pct':100*pnl,'target_hit':hit,'margin':st['margin'],'remaining':st['remaining']}
    return None

def cfgs(bucket):
    bands=[(50,60),(60,70),(70,85)]
    margins=[(-20,-11),(-10,-6),(-5,-1),(0,5)] if bucket=='BASKETBALL' else [(-21,-10),(-9,-4),(-3,3)]
    remains=[6*60,12*60,18*60] if bucket=='BASKETBALL' else [8*60,15*60,25*60]
    return [{'pre_min':b[0],'pre_max':b[1],'drop':d,'margin_min':m[0],'margin_max':m[1],'min_remaining_sec':r,'target':t,'maxm':x} for b,d,m,r,t,x in product(bands,[10,15,20,25],margins,remains,[4,6,8,10],[10,20,30,60])]
def stats(rr):
    if not rr:return {'trades':0,'roi_pct':None}
    cost=sum(x['cost'] for x in rr); pnl=sum(x['pnl'] for x in rr); eq=peak=dd=0
    for x in sorted(rr,key=lambda z:z['close_ts']):eq+=x['pnl'];peak=max(peak,eq);dd=min(dd,eq-peak)
    return {'trades':len(rr),'roi_pct':round(100*pnl/cost,2),'pnl_units':round(pnl,3),'positive_pct':round(100*sum(x['pnl']>0 for x in rr)/len(rr),2),'max_drawdown_units':round(dd,3),'target_hit_pct':round(100*sum(x['target_hit'] for x in rr)/len(rr),2)}
def split(es):
    es=sorted(es,key=lambda e:e['close_ts']);n=len(es);a=int(n*.5);b=int(n*.75);return es[:a],es[a:b],es[b:]
def ev(es,c):return [z for z in (replay(e,c) for e in es) if z]
def discover(es,bucket):
    d,v,h=split(es); cand=[]
    for c in cfgs(bucket):
        ds,vs=stats(ev(d,c)),stats(ev(v,c))
        if ds['trades']<8 or vs['trades']<4 or ds['roi_pct'] is None or vs['roi_pct'] is None or min(ds['roi_pct'],vs['roi_pct'])<=0:continue
        cand.append((min(ds['roi_pct'],vs['roi_pct']),c,ds,vs))
    cand.sort(key=lambda x:x[0],reverse=True)
    if not cand:return {'robust_candidates':0,'selected':None}
    w=cand[0];return {'robust_candidates':len(cand),'selected':{'config':w[1],'development':w[2],'validation':w[3],'holdout':stats(ev(h,w[1]))}}

def run(days=365,max_events=300):
    cutoff=datetime.now(timezone.utc)-timedelta(days=days); by={'BASKETBALL':[],'FOOTBALL':[]};cov={'markets':0,'market_records':0,'espn_matched':0,'state_timelines':0}
    ss=[s for s in series_list() if classify_series(s) in by]
    for s in ss:
        bucket=classify_series(s)
        if len(by[bucket])>=max_events:continue
        ms=markets_for_series(s['ticker']); cov['markets']+=len(ms)
        for m in sorted(ms,key=lambda x:str(x.get('close_time') or x.get('settlement_ts') or ''),reverse=True):
            if len(by[bucket])>=max_events:break
            try:e=build_market_record(bucket,s['ticker'],m,cutoff)
            except:continue
            if not e:continue
            cov['market_records']+=1
            close=datetime.fromtimestamp(e['close_ts'],timezone.utc); g=match_game(m,close)
            if not g:continue
            cov['espn_matched']+=1; tl=state_timeline(g)
            if len(tl)<10:continue
            cov['state_timelines']+=1; e['timeline']=tl; by[bucket].append(e)
            time.sleep(.02)
    result={'version':'EDGE-v2.0-state-sports','period_days':days,'coverage':cov,'sports':{},'guardrails':['Kalshi minute candles joined to ESPN play timestamps.','Sport/state configurations selected only on development+validation.','Untouched final 25% holdout.','+1c entry and -0.5c exit friction.']}
    for b,es in by.items():result['sports'][b]={'events':len(es),'discovery':discover(es,b) if len(es)>=30 else {'robust_candidates':0,'selected':None}}
    Path('edge_v20_state_sports_results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':run(int(os.environ.get('EDGE_DAYS','365')),int(os.environ.get('EDGE_MAX_EVENTS','300')))
