from __future__ import annotations

import json, os, re, time
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path
import requests

KALSHI='https://external-api.kalshi.com/trade-api/v2'
S=requests.Session(); S.headers.update({'User-Agent':'SyncWorks-EDGE-CFB/2.2'})
ENTRY_FRICTION=1.0; EXIT_FRICTION=0.5

def getj(url,params=None,timeout=30):
    r=S.get(url,params=params,timeout=timeout); r.raise_for_status(); return r.json()
def norm(s): return re.sub(r'[^a-z0-9]+','',str(s or '').lower())
def parse_dt(v):
    try:return datetime.fromisoformat(str(v).replace('Z','+00:00')).astimezone(timezone.utc)
    except:return None
def cents(v):
    if v in (None,''):return None
    try:
        x=float(v); return int(round(x*100)) if x<=1.5 else int(round(x))
    except:return None

def series_list():
    out=[]; cur=''
    for _ in range(12):
        p={'category':'Sports','include_volume':'true','limit':1000}
        if cur:p['cursor']=cur
        x=getj(f'{KALSHI}/series',p); out.extend(x.get('series',[])); cur=x.get('cursor') or ''
        if not cur:break
    return out

def is_cfb_series(s):
    text=' '.join([str(s.get('ticker') or ''),str(s.get('title') or ''),' '.join(str(x) for x in (s.get('tags') or []))]).lower()
    return any(k in text for k in ('college football','ncaa football','ncaaf','cfb'))

def markets_for_series(t):
    out={}
    for endpoint,hist in ((f'{KALSHI}/markets',False),(f'{KALSHI}/historical/markets',True)):
        cur=''
        for _ in range(10):
            p={'series_ticker':t,'limit':1000}
            if not hist:p.update({'status':'settled','mve_filter':'exclude'})
            if cur:p['cursor']=cur
            try:x=getj(endpoint,p)
            except:break
            for m in x.get('markets',[]):
                if m.get('ticker'):out[m['ticker']]=m
            cur=x.get('cursor') or ''
            if not cur:break
    return list(out.values())

def candle_px(c,k):
    sec=c.get(k) or {}; raw=sec.get('close_dollars') if 'close_dollars' in sec else sec.get('close'); return cents(raw)
def candles(series,ticker,start_ts,end_ts):
    for u in (f'{KALSHI}/series/{series}/markets/{ticker}/candlesticks',f'{KALSHI}/historical/markets/{ticker}/candlesticks'):
        try:
            x=getj(u,{'start_ts':int(start_ts),'end_ts':int(end_ts),'period_interval':1}); rows=x.get('candlesticks',[])
            if rows:return rows
        except:pass
    return []
def synthetic_rows(cs):
    yes=[]; no=[]
    for c in cs:
        ts=int(c.get('end_period_ts') or 0); ya,yb=candle_px(c,'yes_ask'),candle_px(c,'yes_bid')
        if ya is None or yb is None or not(1<=ya<=99 and 0<=yb<=99):continue
        na,nb=100-yb,100-ya
        yes.append({'ts':ts,'ask':ya,'bid':yb}); no.append({'ts':ts,'ask':na,'bid':nb})
    return yes,no
def first_liquid(yes,no):
    for y,n in zip(yes,no):
        if y['ask']-y['bid']<=12 and n['ask']-n['bid']<=12:return y,n
    return None

def market_record(series,m,cutoff):
    result=str(m.get('result') or '').lower()
    if result not in {'yes','no'}:return None
    close=parse_dt(m.get('settlement_ts') or m.get('close_time') or m.get('expiration_time') or m.get('latest_expiration_time'))
    if not close or close<cutoff:return None
    cs=candles(series,m['ticker'],(close-timedelta(hours=8)).timestamp(),(close+timedelta(minutes=10)).timestamp())
    if len(cs)<15:return None
    yes,no=synthetic_rows(cs); base=first_liquid(yes,no)
    if not base:return None
    y0,n0=base; total=y0['ask']+n0['ask']; py=100*y0['ask']/total; pn=100-py
    return {'series':series,'ticker':m['ticker'],'market':m,'close_ts':max(r['ts'] for r in yes),'baseline_ts':y0['ts'],'yes_pre':py,'no_pre':pn,'fav_side':'YES' if py>=pn else 'NO','yes_won':result=='yes','no_won':result=='no','yes_rows':yes,'no_rows':no}

def espn_games(date):
    try:return getj('https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard',{'dates':date,'limit':500}).get('events',[])
    except:return []
def market_text(m):return ' '.join(str(m.get(k) or '') for k in ('yes_sub_title','title','subtitle','event_ticker','ticker')).lower()
def match_game(m,close):
    text=market_text(m); nt=norm(text)
    for d in {(close-timedelta(days=1)).strftime('%Y%m%d'),close.strftime('%Y%m%d'),(close+timedelta(days=1)).strftime('%Y%m%d')}:
        for e in espn_games(d):
            comp=((e.get('competitions') or [{}])[0]); teams=[]
            for c in comp.get('competitors') or []:
                t=c.get('team') or {}; teams.append((c.get('homeAway'),t.get('displayName') or '',t.get('shortDisplayName') or '',t.get('abbreviation') or ''))
            if len(teams)!=2:continue
            hits=0
            for _,name,short,abbr in teams:
                if norm(name) in nt or norm(short) in nt or (abbr and re.search(rf'\b{re.escape(abbr.lower())}\b',text)):hits+=1
            if hits<2:continue
            yes=None
            for team in teams:
                _,name,short,abbr=team
                if norm(name) in nt or norm(short) in nt or (abbr and re.search(rf'\b{re.escape(abbr.lower())}\b',text)):yes=team
            if not yes:continue
            return {'event_id':e.get('id'),'teams':teams,'yes_team':yes}
    return None

def summary(event_id):
    try:return getj('https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary',{'event':event_id})
    except:return {}
def timeline(g):
    x=summary(g['event_id']); plays=x.get('plays') or []; out=[]; yes_home=g['yes_team'][0]=='home'
    for p in plays:
        try:wall=parse_dt(p.get('wallclock')); hs=int(p.get('homeScore')); aw=int(p.get('awayScore'))
        except:continue
        if not wall:continue
        per=p.get('period'); period=int((per or {}).get('number') if isinstance(per,dict) else (per or 0))
        clk=(p.get('clock') or {}); disp=clk.get('displayValue') if isinstance(clk,dict) else str(clk or '')
        mm=ss=0
        if ':' in disp:
            try:mm,ss=[int(float(z)) for z in disp.split(':')[:2]]
            except:pass
        remaining=max(0,(4-period)*900+mm*60+ss); margin=(hs-aw) if yes_home else (aw-hs)
        out.append({'ts':int(wall.timestamp()),'margin':margin,'period':period,'remaining':remaining})
    out.sort(key=lambda z:z['ts']); return out
def state_at(tl,ts):
    z=None
    for s in tl:
        if s['ts']<=ts:z=s
        else:break
    return z
def rows(e,s):return e['yes_rows'] if s=='YES' else e['no_rows']
def pre(e,s):return e['yes_pre'] if s=='YES' else e['no_pre']
def won(e,s):return e['yes_won'] if s=='YES' else e['no_won']
def q_at(rs,ts):
    z=None
    for r in rs:
        if r['ts']<=ts:z=r
        else:break
    return z
def exit_value(ctr,rs,after,target,maxm,wonflag):
    cut=after+maxm*60
    for r in rs:
        if r['ts']<=after:continue
        if r['ts']>cut:break
        b=max(0,float(r['bid'])-EXIT_FRICTION)
        if b>=target:return ctr*b/100,True
    q=q_at(rs,cut)
    if q:return ctr*max(0,float(q['bid'])-EXIT_FRICTION)/100,False
    return (ctr if wonflag else 0),False

def replay(e,c):
    side=e['fav_side']; p=pre(e,side)
    if not(c['pre_min']<=p<c['pre_max']):return None
    rs=[r for r in rows(e,side) if r['ts']>=e['baseline_ts']]
    for r in rs:
        if p-r['ask']<c['drop']:continue
        st=state_at(e['timeline'],r['ts'])
        if not st or not(c['margin_min']<=st['margin']<=c['margin_max']) or st['remaining']<c['min_remaining']:continue
        px=min(99,r['ask']+ENTRY_FRICTION); ctr=100/px; val,hit=exit_value(ctr,rs,r['ts'],px+c['target'],c['maxm'],won(e,side)); pnl=val-1
        return {'ticker':e['ticker'],'close_ts':e['close_ts'],'cost':1,'pnl':pnl,'target_hit':hit}
    return None

def cfgs():
    bands=[(50,60),(60,70),(70,85),(85,96)]; margins=[(-28,-15),(-14,-8),(-7,-1),(0,7)]; remains=[8*60,15*60,22*60,30*60]
    return [{'pre_min':b[0],'pre_max':b[1],'drop':d,'margin_min':m[0],'margin_max':m[1],'min_remaining':r,'target':t,'maxm':x} for b,d,m,r,t,x in product(bands,[10,15,20,25,30],margins,remains,[4,6,8,10],[10,20,30,60])]
def stats(rr):
    if not rr:return {'trades':0,'roi_pct':None}
    pnl=sum(x['pnl'] for x in rr); eq=peak=dd=0
    for x in sorted(rr,key=lambda z:z['close_ts']):eq+=x['pnl']; peak=max(peak,eq); dd=min(dd,eq-peak)
    return {'trades':len(rr),'roi_pct':round(100*pnl/len(rr),2),'pnl_units':round(pnl,3),'positive_pct':round(100*sum(x['pnl']>0 for x in rr)/len(rr),2),'max_drawdown_units':round(dd,3),'target_hit_pct':round(100*sum(x['target_hit'] for x in rr)/len(rr),2)}
def split(es):
    es=sorted(es,key=lambda e:e['close_ts']); n=len(es); a=int(n*.5); b=int(n*.75); return es[:a],es[a:b],es[b:]
def ev(es,c):return [z for z in (replay(e,c) for e in es) if z]
def discover(es):
    d,v,h=split(es); cand=[]
    for c in cfgs():
        ds,vs=stats(ev(d,c)),stats(ev(v,c))
        if ds['trades']<8 or vs['trades']<4 or ds['roi_pct'] is None or vs['roi_pct'] is None or min(ds['roi_pct'],vs['roi_pct'])<=0:continue
        cand.append((min(ds['roi_pct'],vs['roi_pct']),c,ds,vs))
    cand.sort(key=lambda x:x[0],reverse=True)
    if not cand:return {'robust_candidates':0,'selected':None}
    w=cand[0]; return {'robust_candidates':len(cand),'selected':{'config':w[1],'development':w[2],'validation':w[3],'holdout':stats(ev(h,w[1]))}}

def run(days=420,max_events=90):
    cutoff=datetime.now(timezone.utc)-timedelta(days=days); events=[]; cov={'series':0,'markets':0,'market_records':0,'espn_matched':0,'state_timelines':0}
    ss=[s for s in series_list() if is_cfb_series(s)]; cov['series']=len(ss)
    for s in ss:
        if len(events)>=max_events:break
        ms=markets_for_series(s['ticker']); cov['markets']+=len(ms)
        for m in sorted(ms,key=lambda x:str(x.get('close_time') or x.get('settlement_ts') or ''),reverse=True):
            if len(events)>=max_events:break
            try:e=market_record(s['ticker'],m,cutoff)
            except:continue
            if not e:continue
            cov['market_records']+=1; close=datetime.fromtimestamp(e['close_ts'],timezone.utc); g=match_game(m,close)
            if not g:continue
            cov['espn_matched']+=1; tl=timeline(g)
            if len(tl)<10:continue
            cov['state_timelines']+=1; e['timeline']=tl; events.append(e); time.sleep(.02)
    result={'version':'EDGE-v2.2-CFB-only','period_days':days,'events':len(events),'coverage':cov,'discovery':discover(events) if len(events)>=30 else {'robust_candidates':0,'selected':None},'guardrails':['CFB only.','Kalshi minute candles joined to ESPN college-football play timestamps.','Config selected only on development+validation.','Untouched final 25% holdout.','+1c entry and -0.5c exit friction.']}
    Path('edge_v22_cfb_results.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2))
if __name__=='__main__':run(int(os.environ.get('EDGE_DAYS','420')),int(os.environ.get('EDGE_MAX_EVENTS','90')))
