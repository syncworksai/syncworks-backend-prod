from __future__ import annotations

import json, os, time
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path
from collections import defaultdict
import requests

KALSHI='https://external-api.kalshi.com/trade-api/v2'
S=requests.Session(); S.headers.update({'User-Agent':'SyncWorks-EDGE-tennis/1.6b'})
ENTRY_FRICTION=1.0; EXIT_FRICTION=0.5
SERIES=['KXATPMATCH','KXWTAMATCH','KXATPCHALLENGERMATCH','KXWTACHALLENGERMATCH','KXITFMATCH','KXITFWMATCH']

def get(url,params=None,timeout=30):
    r=S.get(url,params=params,timeout=timeout); r.raise_for_status(); return r.json()

def dt(v):
    try:return datetime.fromisoformat(str(v).replace('Z','+00:00')).astimezone(timezone.utc) if v else None
    except:return None

def cents(v):
    try:
        x=float(v); return int(round(x*100)) if x<=1.5 else int(round(x))
    except:return None

def cp(c,key):
    sec=c.get(key) or {}; raw=sec.get('close_dollars') if 'close_dollars' in sec else sec.get('close'); return cents(raw)

def markets(series):
    d={}
    for base,hist in ((f'{KALSHI}/markets',False),(f'{KALSHI}/historical/markets',True)):
        cur=''
        for _ in range(12):
            p={'series_ticker':series,'limit':1000}
            if not hist:p['status']='settled'
            if cur:p['cursor']=cur
            try:x=get(base,p)
            except:break
            for m in x.get('markets',[]):
                if m.get('ticker'):d[m['ticker']]=m
            cur=x.get('cursor') or ''
            if not cur:break
    return list(d.values())

def candles(series,m,start,end):
    for u in (f"{KALSHI}/series/{series}/markets/{m['ticker']}/candlesticks",f"{KALSHI}/historical/markets/{m['ticker']}/candlesticks"):
        try:
            x=get(u,{'start_ts':int(start),'end_ts':int(end),'period_interval':1}).get('candlesticks',[])
            if x:return x
        except:pass
    return []

def synthetic_rows(cs):
    yes=[]; no=[]
    for c in cs:
        ts=int(c.get('end_period_ts') or 0); ya=cp(c,'yes_ask'); yb=cp(c,'yes_bid')
        if ya is None or yb is None or not (1<=ya<=99 and 0<=yb<=99):continue
        # Binary complement: NO ask = 100 - YES bid; NO bid = 100 - YES ask.
        na=100-yb; nb=100-ya
        if not (1<=na<=99 and 0<=nb<=99):continue
        yes.append({'ts':ts,'ask':ya,'bid':yb}); no.append({'ts':ts,'ask':na,'bid':nb})
    return yes,no

def build_event(series,m,cutoff):
    res=str(m.get('result') or '').lower()
    if res not in {'yes','no'}:return None
    close=dt(m.get('settlement_ts') or m.get('close_time') or m.get('expiration_time') or m.get('latest_expiration_time'))
    if not close or close<cutoff:return None
    cs=candles(series,m,(close-timedelta(hours=10)).timestamp(),(close+timedelta(hours=2)).timestamp())
    if len(cs)<20:return None
    yes,no=synthetic_rows(cs)
    if len(yes)<20:return None
    # Use first liquid candle as baseline; avoids requiring two separate player contracts.
    base=None
    for y,n in zip(yes,no):
        if y['ask']-y['bid']<=12 and n['ask']-n['bid']<=12:
            base=(y,n);break
    if not base:return None
    y0,n0=base; total=y0['ask']+n0['ask']
    py=100*y0['ask']/total; pn=100-py
    fav_side='YES' if py>=pn else 'NO'; fav_pre=max(py,pn)
    if not 50<=fav_pre<80:return None
    end_ts=max(r['ts'] for r in yes)
    fav_rows=yes if fav_side=='YES' else no; dog_rows=no if fav_side=='YES' else yes
    fav_won=(res=='yes') if fav_side=='YES' else (res=='no')
    return {'series':series,'ticker':m['ticker'],'event':m.get('event_ticker'),'close_ts':end_ts,'baseline_ts':y0['ts'],'favorite_pregame':round(fav_pre,2),'favorite_won':fav_won,'dog_won':not fav_won,'favorite_rows':fav_rows,'dog_rows':dog_rows}

def q_at(rows,ts):
    out=None
    for r in rows:
        if r['ts']<=ts:out=r
        else:break
    return out

def replay(e,cfg):
    f=[r for r in e['favorite_rows'] if r['ts']>=e['baseline_ts']]; d=[r for r in e['dog_rows'] if r['ts']>=e['baseline_ts']]
    if not f or not d:return None
    trigger=dog=None
    for fr in f:
        if fr['ts']>e['close_ts']-cfg['min_remaining']*60:break
        if fr['ask']>=cfg['trigger']:
            dq=q_at(d,fr['ts'])
            if dq and fr['ts']-dq['ts']<=180:trigger,dog=fr,dq;break
    if trigger is None:return None
    f0=q_at(f,e['baseline_ts']);
    if not f0:return None
    fav_px=min(99,float(f0['ask'])+ENTRY_FRICTION); fav_contracts=100/fav_px
    hc=cfg['hedge_mult']; dog_px=min(99,float(dog['ask'])+ENTRY_FRICTION); dog_contracts=hc*100/dog_px
    dog_value=None; closed=False
    for r in d:
        if r['ts']<=dog['ts']:continue
        bid=max(0,float(r['bid'])-EXIT_FRICTION)
        if bid>=dog_px+cfg['target']:
            dog_value=dog_contracts*bid/100;closed=True;break
    if dog_value is None:dog_value=dog_contracts if e['dog_won'] else 0
    fav_value=fav_contracts if e['favorite_won'] else 0
    cost=1+hc; pnl=fav_value+dog_value-cost
    return {'ticker':e['ticker'],'close_ts':e['close_ts'],'cost':cost,'pnl':pnl,'roi_pct':100*pnl/cost,'hedge_closed_early':closed,'favorite_pregame':e['favorite_pregame'],'trigger_price':trigger['ask'],'dog_entry':dog_px}

def stats(rs):
    if not rs:return {'events':0,'roi_pct':None}
    cost=sum(x['cost'] for x in rs); pnl=sum(x['pnl'] for x in rs); eq=peak=dd=0
    for x in sorted(rs,key=lambda z:z['close_ts']):
        eq+=x['pnl'];peak=max(peak,eq);dd=min(dd,eq-peak)
    return {'events':len(rs),'roi_pct':round(100*pnl/cost,2),'total_pnl_units':round(pnl,3),'positive_event_pct':round(100*sum(x['pnl']>0 for x in rs)/len(rs),2),'avg_event_roi_pct':round(sum(x['roi_pct'] for x in rs)/len(rs),2),'max_drawdown_units':round(dd,3),'hedge_early_exit_pct':round(100*sum(x['hedge_closed_early'] for x in rs)/len(rs),2)}

def cfgs():
    return [{'trigger':t,'hedge_mult':h,'target':g,'min_remaining':r,'pregame_min':b[0],'pregame_max':b[1]} for t,h,g,r,b in product([75,78,80,82,85,87,90],[.10,.15,.20,.25,.30],[3,5,7,10],[15,30,45,60,90],[(50,55),(55,60),(60,65),(65,70),(70,80),(50,80)])]

def evaluate(events,cfg):
    return [x for x in (replay(e,cfg) for e in events if cfg['pregame_min']<=e['favorite_pregame']<cfg['pregame_max']) if x]

def run(days=240,max_events=1200):
    cutoff=datetime.now(timezone.utc)-timedelta(days=days); events=[]; cov={'markets':0,'usable_events':0,'by_series':{},'errors':[]}
    for s in SERIES:
        ms=markets(s); cov['markets']+=len(ms); n=0
        for m in sorted(ms,key=lambda x:str(x.get('close_time') or x.get('settlement_ts') or ''),reverse=True):
            if len(events)>=max_events:break
            try:e=build_event(s,m,cutoff)
            except Exception as ex:
                cov['errors'].append({'ticker':m.get('ticker'),'error':str(ex)});continue
            if e:events.append(e);n+=1
            if n and n%100==0:time.sleep(.1)
        cov['by_series'][s]=n
        if len(events)>=max_events:break
    events.sort(key=lambda e:e['close_ts']);cov['usable_events']=len(events)
    n=len(events);c1=int(n*.5);c2=int(n*.75);dev,val,hold=events[:c1],events[c1:c2],events[c2:]
    viable=[]
    for cfg in cfgs():
        ds,vs=stats(evaluate(dev,cfg)),stats(evaluate(val,cfg))
        if ds['events']<25 or vs['events']<12 or ds['roi_pct'] is None or vs['roi_pct'] is None or min(ds['roi_pct'],vs['roi_pct'])<=0:continue
        score=min(ds['roi_pct'],vs['roi_pct'])+.15*(ds['roi_pct']+vs['roi_pct'])/2
        viable.append((score,cfg,ds,vs))
    viable.sort(key=lambda x:x[0],reverse=True); win=viable[0] if viable else None
    result={'version':'EDGE-v1.6b-tennis-binary','period_days':days,'coverage':cov,'split_counts':{'development':len(dev),'validation':len(val),'holdout':len(hold)},'configs_tested':len(cfgs()),'robust_candidates':len(viable),'selected':None,'guardrails':['Single binary tennis markets are treated as complementary YES/NO player sides.','NO ask/bid are derived from YES bid/ask complements.','+1c entry and -0.5c exit friction used.','Final holdout is not used for rule selection.','Price-only research; sport-state enrichment required before production.']}
    if win:
        hs=stats(evaluate(hold,win[1]));result['selected']={'config':win[1],'development':win[2],'validation':win[3],'holdout':hs}
    Path('edge_v16b_tennis_results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':run(int(os.environ.get('EDGE_DAYS','240')),int(os.environ.get('EDGE_MAX_EVENTS','1200')))
