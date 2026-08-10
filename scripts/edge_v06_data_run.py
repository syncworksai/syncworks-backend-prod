from __future__ import annotations

import bisect
import json
import math
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

KALSHI = "https://external-api.kalshi.com/trade-api/v2"
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
MLB_FEED = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

TEAM_CODES = {
    "Arizona Diamondbacks": "ARI", "Athletics": "ATH", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS", "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET", "Houston Astros": "HOU",
    "Kansas City Royals": "KC", "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN",
    "New York Mets": "NYM", "New York Yankees": "NYY", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

session = requests.Session()
session.headers.update({"User-Agent": "SyncWorks-EDGE-research/0.6"})


def get_json(url, params=None, timeout=25):
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def cents(value):
    if value in (None, ""):
        return None
    try:
        return int(round(float(value) * 100))
    except Exception:
        return None


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-12, min(12, x))))


def logit(p):
    p = max(.02, min(.98, p))
    return math.log(p / (1-p))


def fair_prob(side, away, home, away_score, home_score, inning, half, outs):
    # Same intentionally-simple v0.2 family: neutral pregame strength + home field + live score/time.
    x = logit(.5) - .10
    remaining_outs = max(0, 27 - ((max(1, inning)-1)*3 + (3 if str(half).lower()=="bottom" else 0) + outs))
    leverage = min(1.0, remaining_outs / 27.0)
    score_weight = .16 + .34 * (1-leverage)
    x += (away_score-home_score) * score_weight
    x *= .72 + .28*leverage
    away_p = sigmoid(x)
    return away_p if side == away else 1-away_p


def dt(value):
    if not value: return None
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception: return None


def play_states(game_pk):
    p = get_json(MLB_FEED.format(game_pk=game_pk))
    plays = p.get("liveData", {}).get("plays", {}).get("allPlays", [])
    rows=[]
    for play in plays:
        about=play.get("about") or {}; result=play.get("result") or {}
        events=play.get("playEvents") or []
        when=dt(events[-1].get("endTime")) if events else None
        if not when or not about.get("isComplete"): continue
        rows.append({
            "ts": when.timestamp(), "away_score": int(result.get("awayScore") or 0),
            "home_score": int(result.get("homeScore") or 0), "inning": int(about.get("inning") or 0),
            "half": str(about.get("halfInning") or ""), "outs": int((play.get("count") or {}).get("outs") or 0),
        })
    rows.sort(key=lambda x:x["ts"])
    return rows


def mlb_games(day):
    p=get_json(MLB_SCHEDULE,{"sportId":1,"date":day.isoformat(),"hydrate":"team"})
    out=[]
    for d in p.get("dates",[]):
        for g in d.get("games",[]):
            if g.get("status",{}).get("abstractGameState") != "Final": continue
            a=(g.get("teams",{}).get("away",{}).get("team",{}) or {}).get("name")
            h=(g.get("teams",{}).get("home",{}).get("team",{}) or {}).get("name")
            if TEAM_CODES.get(a) and TEAM_CODES.get(h): out.append((g["gamePk"], TEAM_CODES[a], TEAM_CODES[h]))
    return out


def recent_markets_for_day(day):
    start=int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    end=int((datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)+timedelta(days=2)).timestamp())
    markets=[]; cursor=""
    for _ in range(10):
        params={"series_ticker":"KXMLBGAME","status":"settled","min_settled_ts":start,"max_settled_ts":end,"limit":1000,"mve_filter":"exclude"}
        if cursor: params["cursor"]=cursor
        try: payload=get_json(f"{KALSHI}/markets",params)
        except Exception: break
        markets.extend(payload.get("markets",[])); cursor=payload.get("cursor") or ""
        if not cursor: break
    return markets


def market_team(m):
    t=str(m.get("ticker") or "")
    return t.rsplit("-",1)[-1].upper() if "-" in t else None


def candles(m, start_ts, end_ts):
    ticker=m["ticker"]
    urls=[f"{KALSHI}/series/KXMLBGAME/markets/{ticker}/candlesticks",f"{KALSHI}/historical/markets/{ticker}/candlesticks"]
    for url in urls:
        try:
            return get_json(url,{"start_ts":int(start_ts),"end_ts":int(end_ts),"period_interval":1}).get("candlesticks",[])
        except Exception: pass
    return []


def candle_ask(c):
    sec=c.get("yes_ask") or {}
    return cents(sec.get("close_dollars") if "close_dollars" in sec else sec.get("close"))


def run(days=10):
    end=date.today()-timedelta(days=1); start=end-timedelta(days=days-1)
    observations=[]; coverage={"days":days,"games":0,"matched_games":0,"markets":0,"candles":0,"errors":[]}
    for di in range(days):
        day=start+timedelta(days=di)
        try: games=mlb_games(day); markets=recent_markets_for_day(day)
        except Exception as exc:
            coverage["errors"].append({"date":str(day),"error":str(exc)}); continue
        coverage["games"] += len(games); coverage["markets"] += len(markets)
        for game_pk, away, home in games:
            matched=[m for m in markets if str(m.get("event_ticker") or "").startswith("KXMLBGAME-") and away in str(m.get("event_ticker")) and home in str(m.get("event_ticker")) and market_team(m) in {away,home}]
            if len(matched)<2: continue
            try: states=play_states(game_pk)
            except Exception as exc:
                coverage["errors"].append({"game_pk":game_pk,"error":str(exc)}); continue
            if not states: continue
            coverage["matched_games"] += 1
            times=[x["ts"] for x in states]
            for m in matched:
                side=market_team(m); result=str(m.get("result") or "").lower()
                cs=candles(m,times[0]-1800,times[-1]+600); coverage["candles"] += len(cs)
                for c in cs:
                    ts=int(c.get("end_period_ts") or 0); idx=bisect.bisect_right(times,ts)-1
                    ask=candle_ask(c)
                    if idx<0 or ask is None or not (1<=ask<=99) or result not in {"yes","no"}: continue
                    st=states[idx]
                    p=fair_prob(side,away,home,st["away_score"],st["home_score"],st["inning"],st["half"],st["outs"])
                    trailing=(side==away and st["away_score"]<st["home_score"]) or (side==home and st["home_score"]<st["away_score"])
                    deficit=abs(st["away_score"]-st["home_score"])
                    observations.append({"date":str(day),"game_pk":game_pk,"ticker":m["ticker"],"side":side,"away":away,"home":home,"score":[st["away_score"],st["home_score"]],"inning":st["inning"],"half":st["half"],"outs":st["outs"],"ask":ask,"model":round(p*100,2),"edge":round(p*100-ask,2),"won":result=="yes","trailing":trailing,"deficit":deficit,"ts":ts})
            time.sleep(.03)

    # One entry per market per threshold: first qualifying observation. This prevents minute-by-minute double-counting.
    thresholds={}
    for th in (5,8,10):
        first={}
        for o in sorted(observations,key=lambda x:x["ts"]):
            if o["edge"]>=th and o["ticker"] not in first: first[o["ticker"]]=o
        trades=list(first.values()); profits=[]
        for o in trades:
            # $1 invested at ask, held to settlement. Gross before fees.
            profit=(100/o["ask"]-1) if o["won"] else -1
            profits.append(profit)
        thresholds[str(th)]={"trades":len(trades),"wins":sum(x["won"] for x in trades),"win_rate_pct":round(100*sum(x["won"] for x in trades)/len(trades),2) if trades else None,"gross_profit_per_$1_each":round(sum(profits),2),"gross_roi_pct":round(100*sum(profits)/len(trades),2) if trades else None}

    comeback={}
    for deficit in (1,2,3):
        subset=[o for o in observations if o["trailing"] and o["deficit"]==deficit and 4<=o["inning"]<=6]
        # unique market+inning observation, earliest minute in state
        seen={}
        for o in sorted(subset,key=lambda x:x["ts"]): seen.setdefault((o["ticker"],o["inning"]),o)
        rows=list(seen.values())
        comeback[str(deficit)]={"samples":len(rows),"actual_win_rate_pct":round(100*sum(x["won"] for x in rows)/len(rows),2) if rows else None,"avg_market_ask_pct":round(sum(x["ask"] for x in rows)/len(rows),2) if rows else None,"avg_model_pct":round(sum(x["model"] for x in rows)/len(rows),2) if rows else None}

    result={"period":{"start":str(start),"end":str(end)},"coverage":coverage,"observations":len(observations),"thresholds":thresholds,"comeback_midgame":comeback,"limitations":["Gross settlement returns only; Kalshi fees/slippage are not deducted in this first execution run.","EDGE fair probability is the current experimental heuristic, not yet calibrated.","One qualifying entry per market per threshold is used to reduce repeated-state overcounting."]}
    Path("edge_v06_results.json").write_text(json.dumps(result,indent=2))
    Path("edge_v06_sample.json").write_text(json.dumps(observations[:5000],indent=2))
    print(json.dumps(result,indent=2))

if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS","10")))
