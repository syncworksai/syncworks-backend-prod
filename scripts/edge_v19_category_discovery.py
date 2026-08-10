from __future__ import annotations

import json, os, time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path
import requests

KALSHI='https://external-api.kalshi.com/trade-api/v2'
S=requests.Session(); S.headers.update({'User-Agent':'SyncWorks-EDGE-category/1.9'})
ENTRY_FRICTION=1.0; EXIT_FRICTION=0.5


def getj(url, params=None, timeout=30):
    r=S.get(url,params=params,timeout=timeout); r.raise_for_status(); return r.json()

def dt(v):
    try:return datetime.fromisoformat(str(v).replace('Z','+00:00')).astimezone(timezone.utc) if v else None
    except:return None

def cents(v):
    try:
        x=float(v); return int(round(x*100)) if x<=1.5 else int(round(x))
    except:return None

def cp(c,k):
    sec=c.get(k) or {}; raw=sec.get('close_dollars') if 'close_dollars' in sec else sec.get('close'); return cents(raw)

def synth(cs):
    y=[]; n=[]
    for c in cs:
        ts=int(c.get('end_period_ts') or 0); ya=cp(c,'yes_ask'); yb=cp(c,'yes_bid')
        if ya is None or yb is None or not(1<=ya<=99 and 0<=yb<=99):continue
        na=100-yb; nb=100-ya
        if not(1<=na<=99 and 0<=nb<=99):continue
        y.append({'ts':ts,'ask':ya,'bid':yb}); n.append({'ts':ts,'ask':na,'bid':nb})
    return y,n

def series_all():
    out=[]; cur=''
    for _ in range(15):
        p={'include_volume':'true','limit':1000}
        if cur:p['cursor']=cur
        x=getj(f'{KALSHI}/series',p); out+=x.get('series',[]); cur=x.get('cursor') or ''
        if not cur:break
    return out

def cat(s):
    c=str(s.get('category') or '').strip().upper()
    if c:return c
    txt=' '.join([str(s.get('title') or ''),str(s.get('ticker') or ''),' '.join(str(x) for x in (s.get('tags') or []))]).lower()
    if any(k in txt for k in ('weather','temperature','hurricane','snow','rain')):return 'WEATHER'
    if any(k in txt for k in ('bitcoin','crypto','ethereum')):return 'CRYPTO'
    if any(k in txt for k in ('fed','cpi','gdp','jobs','economy','inflation')):return 'ECONOMICS'
    if any(k in txt for k in ('election','president','senate','congress','politic')):return 'POLITICS'
    return 'OTHER'

def markets(series):
    d={}
    for endpoint,hist in ((f'{KALSHI}/markets',False),(f'{KALSHI}/historical/markets',True)):
        cur=''
        for _ in range(10):
            p={'series_ticker':series,'limit':1000}
            if not hist:p['status']='settled'
            if cur:p['cursor']=cur
            try:x=getj(endpoint,p)
            except:break
            for m in x.get('markets',[]):
                if m.get('ticker'):d[m['ticker']]=m
            cur=x.get('cursor') or ''
            if not cur:break
    return list(d.values())

def candles(series,ticker,start,end):
    for u in (f'{KALSHI}/series/{series}/markets/{ticker}/candlesticks',f'{KALSHI}/historical/markets/{ticker}/candlesticks'):
        try:
            r=getj(u,{'start_ts':int(start),'end_ts':int(end),'period_interval':1}).get('candlesticks',[])
            if r:return r
        except:pass
    return []

def record(category,series,m,cutoff):
    res=str(m.get('result') or '').lower()
    if res not in {'yes','no'}:return None
    close=dt(m.get('settlement_ts') or m.get('close_time') or m.get('expiration_time') or m.get('latest_expiration_time'))
    if not close or close<cutoff:return None
    cs=candles(series,m['ticker'],(close-timedelta(days=7)).timestamp(),(close+timedelta(minutes=5)).timestamp())
    if len(cs)<25:return None
    y,n=synth(cs)
    if len(y)<25:return None
    base=None
    for yy,nn in zip(y,n):
        if yy['ask']-yy['bid']<=12 and nn['ask']-nn['bid']<=12:
            base=(yy,nn);break
    if not base:return None
    yy,nn=base; tot=yy['ask']+nn['ask']
    if tot<=0:return None
    py=100*yy['ask']/tot; pn=100-py
    return {'category':category,'series':series,'ticker':m['ticker'],'close_ts':max(r['ts'] for r in y),'baseline_ts':yy['ts'],'yes_pre':py,'no_pre':pn,'yes_won':res=='yes','no_won':res=='no','yes_rows':y,'no_rows':n}

def q(rows,ts):
    z=None
    for r in rows:
        if r['ts']<=ts:z=r
        else:break
    return z

def opp(side):return 'NO' if side=='YES' else 'YES'
def rows(e,s):return e['yes_rows'] if s=='YES' else e['no_rows']
def pre(e,s):return e['yes_pre'] if s=='YES' else e['no_pre']
def won(e,s):return e['yes_won'] if s=='YES' else e['no_won']

def exitv(contracts,rs,after,target=None,maxm=None,settle=False):
    cut=after+maxm*60 if maxm else None
    for r in rs:
        if r['ts']<=after:continue
        if cut and r['ts']>cut:break
        b=max(0,float(r['bid'])-EXIT_FRICTION)
        if target is not None and b>=target:return contracts*b/100,True
    if cut:
        z=q(rs,cut)
        if z:return contracts*max(0,float(z['bid'])-EXIT_FRICTION)/100,False
    return (contracts if settle else 0),False

def replay(e,f,c):
    # Pick starting side nearest requested pre band center.
    center=(c['pre_min']+c['pre_max'])/2
    side=min(('YES','NO'),key=lambda s:abs(pre(e,s)-center))
    p=pre(e,side)
    if not(c['pre_min']<=p<c['pre_max']):return None
    rs=[r for r in rows(e,side) if r['ts']>=e['baseline_ts']]
    if not rs:return None
    trigger=None
    if f=='CRASH_REVERT':
        trigger=next((r for r in rs if p-r['ask']>=c['move'] and r['ts']<=e['close_ts']-c['min_remaining']*60),None)
        if not trigger:return None
        px=min(99,trigger['ask']+ENTRY_FRICTION); ctr=100/px
        val,hit=exitv(ctr,rs,trigger['ts'],px+c['target'],c['maxm'],won(e,side)); cost=1
    elif f=='SPIKE_FADE':
        trigger=next((r for r in rs if r['ask']-p>=c['move'] and r['ts']<=e['close_ts']-c['min_remaining']*60),None)
        if not trigger:return None
        os=opp(side); ors=rows(e,os); z=q(ors,trigger['ts'])
        if not z:return None
        px=min(99,z['ask']+ENTRY_FRICTION); ctr=100/px
        val,hit=exitv(ctr,ors,trigger['ts'],px+c['target'],c['maxm'],won(e,os)); cost=1
    elif f=='MOMENTUM':
        trigger=next((r for r in rs if r['ask']-p>=c['move'] and r['ts']<=e['close_ts']-c['min_remaining']*60),None)
        if not trigger:return None
        px=min(99,trigger['ask']+ENTRY_FRICTION); ctr=100/px
        val,hit=exitv(ctr,rs,trigger['ts'],px+c['target'],c['maxm'],won(e,side)); cost=1
    else: # HEDGE: buy baseline side, then small opposite hedge after spike
        trigger=next((r for r in rs if r['ask']>=c['leader_trigger'] and r['ts']<=e['close_ts']-c['min_remaining']*60),None)
        if not trigger:return None
        base=q(rs,e['baseline_ts']); os=opp(side); ors=rows(e,os); z=q(ors,trigger['ts'])
        if not base or not z:return None
        bpx=min(99,base['ask']+ENTRY_FRICTION); bctr=100/bpx
        h=c['hedge_mult']; hpx=min(99,z['ask']+ENTRY_FRICTION); hctr=h*100/hpx
        hv,hit=exitv(hctr,ors,trigger['ts'],hpx+c['target'],None,won(e,os))
        bv=bctr if won(e,side) else 0; val=bv+hv; cost=1+h
    pnl=val-cost
    return {'family':f,'ticker':e['ticker'],'close_ts':e['close_ts'],'cost':cost,'pnl':pnl,'roi_pct':100*pnl/cost,'target_hit':hit}

def cfgs(f):
    bands=[(15,30),(30,45),(45,55),(55,70),(70,85),(15,85)]
    if f in {'CRASH_REVERT','SPIKE_FADE','MOMENTUM'}:
        return [{'pre_min':b[0],'pre_max':b[1],'move':m,'target':t,'maxm':x,'min_remaining':r} for b,m,t,x,r in product(bands,[8,12,18,25],[3,5,8,12],[30,60,180,360],[30,120,360])]
    return [{'pre_min':b[0],'pre_max':b[1],'leader_trigger':lt,'hedge_mult':hm,'target':t,'min_remaining':r} for b,lt,hm,t,r in product(bands,[70,75,80,85,90],[.10,.15,.20,.25],[3,5,8,10],[30,120,360])]

def stats(rr):
    if not rr:return {'trades':0,'roi_pct':None}
    cost=sum(x['cost'] for x in rr); pnl=sum(x['pnl'] for x in rr);eq=peak=dd=0
    for x in sorted(rr,key=lambda z:z['close_ts']):eq+=x['pnl'];peak=max(peak,eq);dd=min(dd,eq-peak)
    return {'trades':len(rr),'roi_pct':round(100*pnl/cost,2),'pnl_units':round(pnl,3),'positive_pct':round(100*sum(x['pnl']>0 for x in rr)/len(rr),2),'max_drawdown_units':round(dd,3),'target_hit_pct':round(100*sum(x['target_hit'] for x in rr)/len(rr),2)}
def split(es):
    es=sorted(es,key=lambda e:e['close_ts']);n=len(es);a=int(n*.5);b=int(n*.75);return es[:a],es[a:b],es[b:]
def ev(es,f,c):return [z for z in (replay(e,f,c) for e in es) if z]

def discover(es,f):
    d,v,h=split(es); cand=[]
    for c in cfgs(f):
        ds,vs=stats(ev(d,f,c)),stats(ev(v,f,c))
        if ds['trades']<12 or vs['trades']<6 or ds['roi_pct'] is None or vs['roi_pct'] is None or min(ds['roi_pct'],vs['roi_pct'])<=0:continue
        score=min(ds['roi_pct'],vs['roi_pct'])+.1*(ds['roi_pct']+vs['roi_pct'])/2
        cand.append((score,c,ds,vs))
    cand.sort(key=lambda x:x[0],reverse=True)
    if not cand:return {'robust_candidates':0,'selected':None}
    w=cand[0]; return {'robust_candidates':len(cand),'selected':{'config':w[1],'development':w[2],'validation':w[3],'holdout':stats(ev(h,f,w[1]))}}

def run(days=365,max_per_cat=600):
    cutoff=datetime.now(timezone.utc)-timedelta(days=days); groups=defaultdict(list); coverage=defaultdict(lambda:{'series':0,'markets_scanned':0,'usable':0})
    ss=series_all()
    for s in ss:
        c=cat(s)
        if c=='SPORTS':continue
        # avoid ultra-small categories until enough data exists
        coverage[c]['series']+=1
    for s in ss:
        c=cat(s)
        if c=='SPORTS' or len(groups[c])>=max_per_cat:continue
        ms=markets(s.get('ticker'))
        coverage[c]['markets_scanned']+=len(ms)
        for m in sorted(ms,key=lambda x:str(x.get('close_time') or x.get('settlement_ts') or ''),reverse=True):
            if len(groups[c])>=max_per_cat:break
            try:e=record(c,s.get('ticker'),m,cutoff)
            except Exception:continue
            if e:groups[c].append(e);coverage[c]['usable']+=1
    result={'version':'EDGE-v1.9-category-discovery','period_days':days,'coverage':dict(coverage),'categories':{},'guardrails':['Each category optimized independently.','Development 50%, validation 25%, untouched holdout 25%.','+1c entry and -0.5c exit friction.','No holdout metric used in rule selection.']}
    fams=['CRASH_REVERT','SPIKE_FADE','MOMENTUM','HEDGE']
    for c,es in groups.items():
        if len(es)<40:continue
        result['categories'][c]={'events':len(es),'split_counts':{'development':len(es)//2,'validation':len(es)//4,'holdout':len(es)-len(es)//2-len(es)//4},'families':{f:discover(es,f) for f in fams}}
    Path('edge_v19_category_results.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2))
if __name__=='__main__':run(int(os.environ.get('EDGE_DAYS','365')),int(os.environ.get('EDGE_MAX_PER_CAT','600')))
