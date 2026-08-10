from __future__ import annotations

import json, math, os, re, time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from itertools import product
from pathlib import Path

import requests

KALSHI='https://external-api.kalshi.com/trade-api/v2'
SOFA='https://www.sofascore.com/api/v1'
S=requests.Session(); S.headers.update({'User-Agent':'SyncWorks-EDGE-tennis-T2/1.7'})
ENTRY_FRICTION=1.0; EXIT_FRICTION=0.5
SERIES=['KXATPMATCH','KXWTAMATCH','KXATPCHALLENGERMATCH','KXWTACHALLENGERMATCH','KXITFMATCH','KXITFWMATCH']


def get(url,params=None,timeout=30):
    r=S.get(url,params=params,timeout=timeout); r.raise_for_status(); return r.json()

def dt(v):
    try:
        if isinstance(v,(int,float)):
            if v>1e12:v=v/1000
            return datetime.fromtimestamp(v,tz=timezone.utc)
        return datetime.fromisoformat(str(v).replace('Z','+00:00')).astimezone(timezone.utc) if v else None
    except:return None

def cents(v):
    try:
        x=float(v); return int(round(x*100)) if x<=1.5 else int(round(x))
    except:return None

def cp(c,key):
    sec=c.get(key) or {}; raw=sec.get('close_dollars') if 'close_dollars' in sec else sec.get('close'); return cents(raw)

def norm(s):
    s=re.sub(r'[^a-z0-9 ]+',' ',str(s or '').lower()); return ' '.join(s.split())

def sim(a,b):return SequenceMatcher(None,norm(a),norm(b)).ratio()

def market_text(m):return ' '.join(str(m.get(k) or '') for k in ('title','subtitle','yes_sub_title','no_sub_title','ticker','event_ticker'))

def markets(series):
    d={}
    for base,hist in ((f'{KALSHI}/markets',False),(f'{KALSHI}/historical/markets',True)):
        cur=''
        for _ in range(15):
            p={'series_ticker':series,'limit':1000}
            if not hist:p['status']='settled'
            if cur:p['cursor']=cur
            try:x=get(base,p)
            except Exception:break
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
        except Exception:pass
    return []

def synthetic_rows(cs):
    y=[];n=[]
    for c in cs:
        ts=int(c.get('end_period_ts') or 0);ya=cp(c,'yes_ask');yb=cp(c,'yes_bid')
        if ya is None or yb is None or not(1<=ya<=99 and 0<=yb<=99):continue
        na=100-yb;nb=100-ya
        if not(1<=na<=99 and 0<=nb<=99):continue
        y.append({'ts':ts,'ask':ya,'bid':yb});n.append({'ts':ts,'ask':na,'bid':nb})
    return y,n

def sofa_events_for_day(day):
    out=[]
    for page in range(8):
        try:p=get(f'{SOFA}/sport/tennis/scheduled-tournaments/{day}/page/{page}')
        except Exception:break
        found=[]
        def walk(x):
            if isinstance(x,dict):
                if x.get('id') and isinstance(x.get('homeTeam'),dict) and isinstance(x.get('awayTeam'),dict):found.append(x)
                for v in x.values():walk(v)
            elif isinstance(x,list):
                for v in x:walk(v)
        walk(p)
        seen={e.get('id') for e in out}
        out.extend(e for e in found if e.get('id') not in seen)
        if not found:break
    return out

def event_names(e):
    h=(e.get('homeTeam') or {}).get('name') or '';a=(e.get('awayTeam') or {}).get('name') or ''
    return h,a

def match_sofa(m,events,close):
    txt=market_text(m);best=None
    for e in events:
        h,a=event_names(e)
        if not h or not a:continue
        score=(sim(h,txt)+sim(a,txt))/2
        # substring bonuses matter more than global title ratio
        if norm(h) in norm(txt):score+=.45
        if norm(a) in norm(txt):score+=.45
        st=dt(e.get('startTimestamp') or e.get('start_time'))
        if st and close:
            delta=abs((close-st).total_seconds())/3600
            if delta<8:score+=.2
            elif delta>24:score-=.3
        if best is None or score>best[0]:best=(score,e)
    return best[1] if best and best[0]>=.72 else None

def point_states(event_id):
    try:p=get(f'{SOFA}/event/{event_id}/point-by-point')
    except Exception:return []
    rows=[]
    def walk(x):
        if isinstance(x,dict):
            # Search permissively for score-bearing timestamped point/game objects.
            t=None
            for k in ('timestamp','timeStamp','startTimestamp','endTimestamp','createdAt','time'):
                if k in x:
                    t=dt(x.get(k));
                    if t:break
            if t:
                hs=x.get('homeScore',x.get('homeGames',x.get('home')))
                as_=x.get('awayScore',x.get('awayGames',x.get('away')))
                hset=x.get('homeSetScore',x.get('homeSets',x.get('setHome')))
                aset=x.get('awaySetScore',x.get('awaySets',x.get('setAway')))
                hp=x.get('homePoint',x.get('homePoints'))
                ap=x.get('awayPoint',x.get('awayPoints'))
                srv=x.get('server',x.get('serving',x.get('serve')))
                try:
                    row={'ts':int(t.timestamp()),'home_games':int(hs) if hs is not None and str(hs).isdigit() else None,'away_games':int(as_) if as_ is not None and str(as_).isdigit() else None,'home_sets':int(hset) if hset is not None and str(hset).isdigit() else None,'away_sets':int(aset) if aset is not None and str(aset).isdigit() else None,'home_point':hp,'away_point':ap,'server':srv}
                    if any(row[k] is not None for k in ('home_games','home_sets','home_point')):rows.append(row)
                except:pass
            for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(p)
    d={}
    for r in rows:d[r['ts']]=r
    return sorted(d.values(),key=lambda r:r['ts'])

def state_at(states,ts):
    out=None
    for s in states:
        if s['ts']<=ts:out=s
        else:break
    return out

def q_at(rows,ts):
    out=None
    for r in rows:
        if r['ts']<=ts:out=r
        else:break
    return out

def build_event(series,m,sofa,cutoff):
    res=str(m.get('result') or '').lower()
    if res not in {'yes','no'}:return None
    close=dt(m.get('settlement_ts') or m.get('close_time') or m.get('expiration_time') or m.get('latest_expiration_time'))
    if not close or close<cutoff:return None
    sm=match_sofa(m,sofa,close)
    if not sm:return None
    states=point_states(sm['id'])
    if len(states)<8:return None
    st=dt(sm.get('startTimestamp')) or (close-timedelta(hours=4))
    cs=candles(series,m,(st-timedelta(minutes=90)).timestamp(),(close+timedelta(minutes=20)).timestamp())
    yes,no=synthetic_rows(cs)
    if len(yes)<20:return None
    # baseline = first liquid quote at/before first recorded state, else first liquid quote.
    first_state=states[0]['ts']; pairs=list(zip(yes,no));base=None
    for y,n in pairs:
        if y['ts']<=first_state and y['ask']-y['bid']<=12:base=(y,n)
    if not base:
        for y,n in pairs:
            if y['ask']-y['bid']<=12:base=(y,n);break
    if not base:return None
    y0,n0=base; total=y0['ask']+n0['ask'];py=100*y0['ask']/total;pn=100-py
    fav_side='YES' if py>=pn else 'NO';fav_pre=max(py,pn)
    if not 50<=fav_pre<80:return None
    fav_rows=yes if fav_side=='YES' else no;dog_rows=no if fav_side=='YES' else yes
    fav_won=(res=='yes') if fav_side=='YES' else (res=='no')
    hname,aname=event_names(sm)
    # infer whether favorite corresponds to home or away from yes/no market labels
    ylabel=' '.join(str(m.get(k) or '') for k in ('yes_sub_title','title','subtitle'))
    yes_is_home=sim(hname,ylabel)>=sim(aname,ylabel)
    fav_home=yes_is_home if fav_side=='YES' else not yes_is_home
    return {'series':series,'ticker':m['ticker'],'close_ts':int(close.timestamp()),'baseline_ts':y0['ts'],'favorite_pregame':fav_pre,'favorite_won':fav_won,'dog_won':not fav_won,'favorite_rows':fav_rows,'dog_rows':dog_rows,'states':states,'favorite_home':fav_home,'sofa_id':sm['id']}

def state_features(e,s):
    if not s:return None
    fs=s['home_sets'] if e['favorite_home'] else s['away_sets'];ds=s['away_sets'] if e['favorite_home'] else s['home_sets']
    fg=s['home_games'] if e['favorite_home'] else s['away_games'];dg=s['away_games'] if e['favorite_home'] else s['home_games']
    set_diff=(fs-ds) if fs is not None and ds is not None else 0
    game_diff=(fg-dg) if fg is not None and dg is not None else 0
    server=str(s.get('server') or '').lower()
    serving=None
    if server:
        serving=('home' in server or server in ('1','true')) if e['favorite_home'] else ('away' in server or server in ('2','false'))
    return {'set_diff':set_diff,'game_diff':game_diff,'serving':serving}

def replay(e,cfg):
    f=[r for r in e['favorite_rows'] if r['ts']>=e['baseline_ts']];d=[r for r in e['dog_rows'] if r['ts']>=e['baseline_ts']]
    f0=q_at(f,e['baseline_ts']);
    if not f0:return None
    trigger=dog=feat=None
    for fr in f:
        if fr['ask']<cfg['trigger']:continue
        s=state_at(e['states'],fr['ts']);ft=state_features(e,s)
        if not ft:continue
        if cfg['set_state']=='NOT_AHEAD' and ft['set_diff']>0:continue
        if cfg['set_state']=='TIED' and ft['set_diff']!=0:continue
        if cfg['set_state']=='ANY' :pass
        if cfg['max_game_lead'] is not None and ft['game_diff']>cfg['max_game_lead']:continue
        if cfg['serving']=='RETURNING' and ft['serving'] is True:continue
        if cfg['serving']=='SERVING' and ft['serving'] is False:continue
        dq=q_at(d,fr['ts'])
        if dq and fr['ts']-dq['ts']<=180:trigger,dog,feat=fr,dq,ft;break
    if trigger is None:return None
    fav_px=min(99,float(f0['ask'])+ENTRY_FRICTION);fav_contracts=100/fav_px
    hc=cfg['hedge_mult'];dog_px=min(99,float(dog['ask'])+ENTRY_FRICTION);dog_contracts=hc*100/dog_px
    dog_value=None;closed=False
    for r in d:
        if r['ts']<=dog['ts']:continue
        bid=max(0,float(r['bid'])-EXIT_FRICTION)
        if bid>=dog_px+cfg['target']:
            dog_value=dog_contracts*bid/100;closed=True;break
    if dog_value is None:dog_value=dog_contracts if e['dog_won'] else 0
    fav_value=fav_contracts if e['favorite_won'] else 0
    cost=1+hc;pnl=fav_value+dog_value-cost
    return {'ticker':e['ticker'],'close_ts':e['close_ts'],'cost':cost,'pnl':pnl,'roi_pct':100*pnl/cost,'hedge_closed_early':closed,'state':feat}

def stats(rs):
    if not rs:return {'events':0,'roi_pct':None}
    cost=sum(x['cost'] for x in rs);pnl=sum(x['pnl'] for x in rs);eq=peak=dd=0
    for x in sorted(rs,key=lambda z:z['close_ts']):eq+=x['pnl'];peak=max(peak,eq);dd=min(dd,eq-peak)
    return {'events':len(rs),'roi_pct':round(100*pnl/cost,2),'pnl_units':round(pnl,3),'positive_pct':round(100*sum(x['pnl']>0 for x in rs)/len(rs),2),'max_drawdown_units':round(dd,3),'hedge_early_exit_pct':round(100*sum(x['hedge_closed_early'] for x in rs)/len(rs),2)}
def cfgs():
    return [{'trigger':t,'hedge_mult':h,'target':g,'pregame_min':b[0],'pregame_max':b[1],'set_state':ss,'max_game_lead':gl,'serving':sv} for t,h,g,b,ss,gl,sv in product([78,80,82,85,87,90],[.10,.15,.20,.25],[3,5,7],[(50,55),(55,60),(60,65),(65,70),(50,70)],['ANY','TIED','NOT_AHEAD'],[None,0,1,2],['ANY','SERVING','RETURNING'])]
def evaluate(events,cfg):
    return [x for x in (replay(e,cfg) for e in events if cfg['pregame_min']<=e['favorite_pregame']<cfg['pregame_max']) if x]
def run(days=120,max_events=300):
    cutoff=datetime.now(timezone.utc)-timedelta(days=days)
    bydate={}; events=[];cov={'markets':0,'sofa_days':0,'matched_state_events':0,'by_series':{},'errors':[]}
    # Preload Sofascore date windows lazily around each market close.
    for series in SERIES:
        ms=markets(series);cov['markets']+=len(ms);n=0
        for m in sorted(ms,key=lambda x:str(x.get('close_time') or x.get('settlement_ts') or ''),reverse=True):
            if len(events)>=max_events:break
            close=dt(m.get('settlement_ts') or m.get('close_time') or m.get('expiration_time') or m.get('latest_expiration_time'))
            if not close or close<cutoff:continue
            key=close.date().isoformat()
            if key not in bydate:
                # include prior day because settlement can cross UTC midnight
                ev=[]
                for d in (close.date()-timedelta(days=1),close.date()):
                    try:ev.extend(sofa_events_for_day(d.isoformat()))
                    except Exception as ex:cov['errors'].append({'date':str(d),'error':str(ex)})
                bydate[key]=ev;cov['sofa_days']+=1
            try:e=build_event(series,m,bydate[key],cutoff)
            except Exception as ex:cov['errors'].append({'ticker':m.get('ticker'),'error':str(ex)});continue
            if e:events.append(e);n+=1
            time.sleep(.01)
        cov['by_series'][series]=n
        if len(events)>=max_events:break
    events.sort(key=lambda e:e['close_ts']);cov['matched_state_events']=len(events)
    n=len(events);c1=int(n*.5);c2=int(n*.75);dev,val,hold=events[:c1],events[c1:c2],events[c2:]
    viable=[];configs=cfgs()
    for cfg in configs:
        ds,vs=stats(evaluate(dev,cfg)),stats(evaluate(val,cfg))
        if ds['events']<12 or vs['events']<6 or ds['roi_pct'] is None or vs['roi_pct'] is None or min(ds['roi_pct'],vs['roi_pct'])<=0:continue
        score=min(ds['roi_pct'],vs['roi_pct'])+.15*(ds['roi_pct']+vs['roi_pct'])/2;viable.append((score,cfg,ds,vs))
    viable.sort(key=lambda x:x[0],reverse=True);win=viable[0] if viable else None
    result={'version':'EDGE-v1.7-tennis-T2-state','coverage':cov,'split_counts':{'dev':len(dev),'val':len(val),'holdout':len(hold)},'configs_tested':len(configs),'robust_candidates':len(viable),'selected':None,'t1_holdout_roi_pct':-26.55,'notes':['Research-only Sofascore state adapter; undocumented endpoint must not be production dependency.','+1c entry and -0.5c exit friction.','Final holdout excluded from selection.']}
    if win:result['selected']={'config':win[1],'development':win[2],'validation':win[3],'holdout':stats(evaluate(hold,win[1]))}
    Path('edge_v17_tennis_t2_results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':run(int(os.environ.get('EDGE_DAYS','120')),int(os.environ.get('EDGE_MAX_EVENTS','300')))
