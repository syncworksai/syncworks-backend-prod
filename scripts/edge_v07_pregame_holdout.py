from __future__ import annotations

import bisect, json, math, os, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests

KALSHI="https://external-api.kalshi.com/trade-api/v2"
MLB_SCHEDULE="https://statsapi.mlb.com/api/v1/schedule"
MLB_FEED="https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
TEAM_CODES={"Arizona Diamondbacks":"ARI","Athletics":"ATH","Atlanta Braves":"ATL","Baltimore Orioles":"BAL","Boston Red Sox":"BOS","Chicago Cubs":"CHC","Chicago White Sox":"CWS","Cincinnati Reds":"CIN","Cleveland Guardians":"CLE","Colorado Rockies":"COL","Detroit Tigers":"DET","Houston Astros":"HOU","Kansas City Royals":"KC","Los Angeles Angels":"LAA","Los Angeles Dodgers":"LAD","Miami Marlins":"MIA","Milwaukee Brewers":"MIL","Minnesota Twins":"MIN","New York Mets":"NYM","New York Yankees":"NYY","Philadelphia Phillies":"PHI","Pittsburgh Pirates":"PIT","San Diego Padres":"SD","San Francisco Giants":"SF","Seattle Mariners":"SEA","St. Louis Cardinals":"STL","Tampa Bay Rays":"TB","Texas Rangers":"TEX","Toronto Blue Jays":"TOR","Washington Nationals":"WSH"}
s=requests.Session(); s.headers.update({"User-Agent":"SyncWorks-EDGE-research/0.7"})

def get_json(url,params=None,timeout=25):
    r=s.get(url,params=params,timeout=timeout); r.raise_for_status(); return r.json()
def cents(v):
    try:return int(round(float(v)*100)) if v not in (None,"") else None
    except:return None
def sigmoid(x): return 1/(1+math.exp(-max(-12,min(12,x))))
def logit(p): p=max(.02,min(.98,p)); return math.log(p/(1-p))
def dt(v):
    try:return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc) if v else None
    except:return None

def play_states(game_pk):
    p=get_json(MLB_FEED.format(game_pk=game_pk)); rows=[]
    for play in p.get("liveData",{}).get("plays",{}).get("allPlays",[]):
        a=play.get("about") or {}; r=play.get("result") or {}; ev=play.get("playEvents") or []
        when=dt(ev[-1].get("endTime")) if ev else None
        if not when or not a.get("isComplete"): continue
        rows.append({"ts":when.timestamp(),"away_score":int(r.get("awayScore") or 0),"home_score":int(r.get("homeScore") or 0),"inning":int(a.get("inning") or 0),"half":str(a.get("halfInning") or ""),"outs":int((play.get("count") or {}).get("outs") or 0)})
    return sorted(rows,key=lambda x:x["ts"])

def mlb_games(day):
    p=get_json(MLB_SCHEDULE,{"sportId":1,"date":day.isoformat(),"hydrate":"team"}); out=[]
    for d in p.get("dates",[]):
        for g in d.get("games",[]):
            if g.get("status",{}).get("abstractGameState")!="Final": continue
            a=(g.get("teams",{}).get("away",{}).get("team",{}) or {}).get("name"); h=(g.get("teams",{}).get("home",{}).get("team",{}) or {}).get("name"); start=dt(g.get("gameDate"))
            if TEAM_CODES.get(a) and TEAM_CODES.get(h) and start: out.append((g["gamePk"],TEAM_CODES[a],TEAM_CODES[h],start.timestamp()))
    return out

def markets_for_day(day):
    start=int(datetime.combine(day,datetime.min.time(),tzinfo=timezone.utc).timestamp()); end=start+172800; out=[]; cursor=""
    for _ in range(10):
        params={"series_ticker":"KXMLBGAME","status":"settled","min_settled_ts":start,"max_settled_ts":end,"limit":1000,"mve_filter":"exclude"}
        if cursor: params["cursor"]=cursor
        try:p=get_json(f"{KALSHI}/markets",params)
        except:break
        out.extend(p.get("markets",[])); cursor=p.get("cursor") or ""
        if not cursor:break
    return out

def market_team(m):
    t=str(m.get("ticker") or ""); return t.rsplit("-",1)[-1].upper() if "-" in t else None

def candles(m,start_ts,end_ts):
    for url in (f"{KALSHI}/series/KXMLBGAME/markets/{m['ticker']}/candlesticks",f"{KALSHI}/historical/markets/{m['ticker']}/candlesticks"):
        try:return get_json(url,{"start_ts":int(start_ts),"end_ts":int(end_ts),"period_interval":1}).get("candlesticks",[])
        except:pass
    return []
def candle_ask(c):
    sec=c.get("yes_ask") or {}; return cents(sec.get("close_dollars") if "close_dollars" in sec else sec.get("close"))
def latest_pregame_ask(cs,start):
    vals=[(int(c.get("end_period_ts") or 0),candle_ask(c)) for c in cs if int(c.get("end_period_ts") or 0)<=start and candle_ask(c) is not None]
    vals=[x for x in vals if 1<=x[1]<=99]; return max(vals)[1] if vals else None

def fair_away(pregame_away,away_score,home_score,inning,half,outs,base_run,late_run):
    completed=(max(1,inning)-1)*3+(3 if str(half).lower()=="bottom" else 0)+outs; rem=max(0,27-completed); frac=min(1,rem/27)
    w=base_run+(late_run-base_run)*(1-frac); return sigmoid(logit(pregame_away)+(away_score-home_score)*w)

def fit(rows):
    uniq={}
    for r in sorted(rows,key=lambda x:x["ts"]): uniq.setdefault((r["ticker"],r["inning"]),r)
    data=list(uniq.values()); cand=[]
    for base in (.16,.20,.24,.28,.32):
        for late in (.48,.60,.72,.84,1.00):
            loss=0
            for r in data:
                ap=fair_away(r["pregame_away"],r["away_score"],r["home_score"],r["inning"],r["half"],r["outs"],base,late); p=ap if r["side"]==r["away"] else 1-ap; y=1 if r["won"] else 0; loss+=(p-y)**2
            cand.append((loss/len(data) if data else 1,base,late))
    b,base,late=min(cand); return {"base_run":base,"late_run":late,"train_brier":round(b,5),"samples":len(data)}
def apply(rows,p):
    for r in rows:
        ap=fair_away(r["pregame_away"],r["away_score"],r["home_score"],r["inning"],r["half"],r["outs"],p["base_run"],p["late_run"]); q=ap if r["side"]==r["away"] else 1-ap; r["model_v07"]=round(q*100,2); r["edge_v07"]=round(q*100-r["ask"],2)
def brier(rows):
    uniq={}
    for r in sorted(rows,key=lambda x:x["ts"]): uniq.setdefault((r["ticker"],r["inning"]),r)
    vals=[((r["model_v07"]/100)-(1 if r["won"] else 0))**2 for r in uniq.values()]; return round(sum(vals)/len(vals),5) if vals else None
def strategy(rows,th,focused=False,friction=1.5):
    first={}
    for r in sorted(rows,key=lambda x:x["ts"]):
        if r["edge_v07"]<th: continue
        if focused:
            drop=r["pregame_side"]-r["ask"]
            if not (r["pregame_side"]>=55 and r["trailing"] and r["deficit"] in (1,2) and 4<=r["inning"]<=6 and drop>=12): continue
        first.setdefault(r["ticker"],r)
    trades=list(first.values()); pnl=[(100/min(99,r["ask"]+friction)-1) if r["won"] else -1 for r in trades]; wins=sum(r["won"] for r in trades)
    return {"trades":len(trades),"wins":wins,"win_rate_pct":round(100*wins/len(trades),2) if trades else None,"net_profit_$1_each":round(sum(pnl),2),"roi_pct":round(100*sum(pnl)/len(trades),2) if trades else None,"friction_cents":friction}

def run(days=20):
    end=date.today()-timedelta(days=1); start=end-timedelta(days=days-1); obs=[]; cov={"days":days,"games":0,"matched_games":0,"markets":0,"candles":0,"pregame_baselines":0,"errors":[]}
    for i in range(days):
        day=start+timedelta(days=i)
        try:games=mlb_games(day); markets=markets_for_day(day)
        except Exception as e: cov["errors"].append({"date":str(day),"error":str(e)}); continue
        cov["games"]+=len(games); cov["markets"]+=len(markets)
        for game_pk,away,home,gstart in games:
            matched=[m for m in markets if str(m.get("event_ticker") or "").startswith("KXMLBGAME-") and away in str(m.get("event_ticker")) and home in str(m.get("event_ticker")) and market_team(m) in {away,home}]
            if len(matched)<2: continue
            try:states=play_states(game_pk)
            except Exception as e: cov["errors"].append({"game_pk":game_pk,"error":str(e)}); continue
            if not states:continue
            times=[x["ts"] for x in states]; hist={m["ticker"]:candles(m,gstart-5400,times[-1]+600) for m in matched}; cov["candles"]+=sum(len(v) for v in hist.values()); side_market={market_team(m):m for m in matched}; am=side_market.get(away); hm=side_market.get(home)
            if not am or not hm:continue
            ap=latest_pregame_ask(hist.get(am["ticker"],[]),gstart); hp=latest_pregame_ask(hist.get(hm["ticker"],[]),gstart)
            if ap is None or hp is None or ap+hp<=0:continue
            preaway=ap/(ap+hp); cov["pregame_baselines"]+=1; cov["matched_games"]+=1
            for m in matched:
                side=market_team(m); result=str(m.get("result") or "").lower(); sidepre=100*(preaway if side==away else 1-preaway)
                if result not in {"yes","no"}:continue
                for c in hist.get(m["ticker"],[]):
                    ts=int(c.get("end_period_ts") or 0); ask=candle_ask(c); idx=bisect.bisect_right(times,ts)-1
                    if idx<0 or ts<=gstart or ask is None or not 1<=ask<=99:continue
                    st=states[idx]; trailing=(side==away and st["away_score"]<st["home_score"]) or (side==home and st["home_score"]<st["away_score"])
                    obs.append({"date":str(day),"game_pk":game_pk,"ticker":m["ticker"],"side":side,"away":away,"home":home,"away_score":st["away_score"],"home_score":st["home_score"],"inning":st["inning"],"half":st["half"],"outs":st["outs"],"ask":ask,"won":result=="yes","ts":ts,"pregame_away":preaway,"pregame_side":round(sidepre,2),"trailing":trailing,"deficit":abs(st["away_score"]-st["home_score"])})
            time.sleep(.02)
    dates=sorted({r["date"] for r in obs}); cut=max(1,int(len(dates)*.60)); train=[r for r in obs if r["date"] in set(dates[:cut])]; hold=[r for r in obs if r["date"] in set(dates[cut:])]; params=fit(train); apply(train,params); apply(hold,params)
    def pack(rows): return {"dates":[min([r["date"] for r in rows],default=None),max([r["date"] for r in rows],default=None)],"observations":len(rows),"brier":brier(rows),"all_signals":{str(t):strategy(rows,t) for t in (5,8,10)},"focused_comeback":{str(t):strategy(rows,t,True) for t in (5,8,10)}}
    result={"period":{"start":str(start),"end":str(end)},"coverage":cov,"model":{"version":"EDGE-MLB-v0.7-pregame-context","pregame_baseline":"normalized last pregame Kalshi asks","fit":params,"split":"chronological 60% train / 40% untouched holdout"},"results":{"train":pack(train),"holdout":pack(hold)},"limitations":["Research only; no live orders.","Friction modeled as +1.5 cents to entry price.","Pitcher, bullpen, lineup and injuries are not yet included.","Holdout dates are untouched by coefficient fitting."]}
    Path("edge_v07_results.json").write_text(json.dumps(result,indent=2)); Path("edge_v07_holdout_sample.json").write_text(json.dumps(hold[:5000],indent=2)); print(json.dumps(result,indent=2))
if __name__=="__main__":run(int(os.environ.get("EDGE_DAYS","20")))
# Trigger-only research rerun marker.
