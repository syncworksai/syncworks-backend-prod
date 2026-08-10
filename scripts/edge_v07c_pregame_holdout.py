from __future__ import annotations

import bisect, json, os, time
from datetime import date, timedelta
from pathlib import Path

from edge_v07_pregame_holdout import (
    KALSHI, get_json, cents, dt, mlb_games, markets_for_day, market_team, play_states,
    candles, latest_pregame_ask, candle_ask, fit, apply, brier, strategy,
)


def last_trade_before(ticker, start_ts, cutoff_ts):
    params={"ticker":ticker,"min_ts":int(start_ts),"max_ts":int(cutoff_ts),"limit":1000}
    trades=[]
    for url in (f"{KALSHI}/markets/trades", f"{KALSHI}/historical/trades"):
        try:
            payload=get_json(url,params); trades=payload.get("trades",[])
            if trades: break
        except Exception:
            continue
    valid=[]
    for trade in trades:
        when=dt(trade.get("created_time")); price=cents(trade.get("yes_price_dollars"))
        if when and when.timestamp()<=cutoff_ts and price is not None and 1<=price<=99:
            valid.append((when.timestamp(),price))
    return max(valid)[1] if valid else None


def run(days=20):
    end=date.today()-timedelta(days=1); start=end-timedelta(days=days-1)
    obs=[]; cov={"days":days,"games":0,"matched_games":0,"markets":0,"candles":0,"pregame_baselines":0,"baseline_from_candle":0,"baseline_from_trade":0,"errors":[]}
    for i in range(days):
        day=start+timedelta(days=i)
        try: games=mlb_games(day); markets=markets_for_day(day)
        except Exception as e:
            cov["errors"].append({"date":str(day),"error":str(e)}); continue
        cov["games"]+=len(games); cov["markets"]+=len(markets)
        for game_pk,away,home,gstart in games:
            matched=[m for m in markets if str(m.get("event_ticker") or "").startswith("KXMLBGAME-") and away in str(m.get("event_ticker")) and home in str(m.get("event_ticker")) and market_team(m) in {away,home}]
            if len(matched)<2: continue
            try: states=play_states(game_pk)
            except Exception as e:
                cov["errors"].append({"game_pk":game_pk,"error":str(e)}); continue
            if not states: continue
            times=[x["ts"] for x in states]; first_state_ts=times[0]
            hist={m["ticker"]:candles(m,gstart-7200,times[-1]+600) for m in matched}; cov["candles"]+=sum(len(v) for v in hist.values())
            side_market={market_team(m):m for m in matched}; am=side_market.get(away); hm=side_market.get(home)
            if not am or not hm: continue
            ap=latest_pregame_ask(hist.get(am["ticker"],[]),first_state_ts); hp=latest_pregame_ask(hist.get(hm["ticker"],[]),first_state_ts); source="candle"
            if ap is None or hp is None:
                ap=last_trade_before(am["ticker"],gstart-86400,first_state_ts)
                hp=last_trade_before(hm["ticker"],gstart-86400,first_state_ts)
                source="trade"
            if ap is None or hp is None or ap+hp<=0: continue
            preaway=ap/(ap+hp); cov["pregame_baselines"]+=1; cov["matched_games"]+=1; cov[f"baseline_from_{source}"]+=1
            for m in matched:
                side=market_team(m); result=str(m.get("result") or "").lower(); sidepre=100*(preaway if side==away else 1-preaway)
                if result not in {"yes","no"}: continue
                for c in hist.get(m["ticker"],[]):
                    ts=int(c.get("end_period_ts") or 0); ask=candle_ask(c); idx=bisect.bisect_right(times,ts)-1
                    if idx<0 or ts<=first_state_ts or ask is None or not 1<=ask<=99: continue
                    st=states[idx]; trailing=(side==away and st["away_score"]<st["home_score"]) or (side==home and st["home_score"]<st["away_score"])
                    obs.append({"date":str(day),"game_pk":game_pk,"ticker":m["ticker"],"side":side,"away":away,"home":home,"away_score":st["away_score"],"home_score":st["home_score"],"inning":st["inning"],"half":st["half"],"outs":st["outs"],"ask":ask,"won":result=="yes","ts":ts,"pregame_away":preaway,"pregame_side":round(sidepre,2),"trailing":trailing,"deficit":abs(st["away_score"]-st["home_score"]),"baseline_source":source})
            time.sleep(.02)
    dates=sorted({r["date"] for r in obs}); cut=max(1,int(len(dates)*.60)); train_dates=set(dates[:cut]); hold_dates=set(dates[cut:])
    train=[r for r in obs if r["date"] in train_dates]; hold=[r for r in obs if r["date"] in hold_dates]
    params=fit(train); apply(train,params); apply(hold,params)
    def pack(rows):
        return {"dates":[min([r["date"] for r in rows],default=None),max([r["date"] for r in rows],default=None)],"observations":len(rows),"brier":brier(rows),"all_signals":{str(t):strategy(rows,t) for t in (5,8,10)},"focused_comeback":{str(t):strategy(rows,t,True) for t in (5,8,10)}}
    result={"period":{"start":str(start),"end":str(end)},"coverage":cov,"model":{"version":"EDGE-MLB-v0.7c-pregame-context","pregame_baseline":"normalized last quote/trade before first completed MLB play","fit":params,"split":"chronological 60% train / 40% untouched holdout"},"results":{"train":pack(train),"holdout":pack(hold)},"limitations":["Research only; no live orders.","Friction modeled as +1.5 cents to entry price.","Pregame baseline falls back to last actual Kalshi trade before first completed play.","Pitcher, bullpen, lineup and injuries are not yet included."]}
    Path("edge_v07_results.json").write_text(json.dumps(result,indent=2)); Path("edge_v07_holdout_sample.json").write_text(json.dumps(hold[:5000],indent=2)); print(json.dumps(result,indent=2))

if __name__=="__main__": run(int(os.environ.get("EDGE_DAYS","20")))
