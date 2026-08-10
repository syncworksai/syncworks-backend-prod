from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

import requests

KALSHI = "https://external-api.kalshi.com/trade-api/v2"
S = requests.Session()
S.headers.update({"User-Agent": "SyncWorks-EDGE-multisport/1.8"})
ENTRY_FRICTION = 1.0
EXIT_FRICTION = 0.5


def get_json(url, params=None, timeout=30):
    r = S.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def cents(v):
    if v in (None, ""):
        return None
    try:
        x = float(v)
        return int(round(x * 100)) if x <= 1.5 else int(round(x))
    except Exception:
        return None


def candle_px(c, key):
    sec = c.get(key) or {}
    raw = sec.get("close_dollars") if "close_dollars" in sec else sec.get("close")
    return cents(raw)


def synthetic_rows(cs):
    yes, no = [], []
    for c in cs:
        ts = int(c.get("end_period_ts") or 0)
        ya, yb = candle_px(c, "yes_ask"), candle_px(c, "yes_bid")
        if ya is None or yb is None or not (1 <= ya <= 99 and 0 <= yb <= 99):
            continue
        na, nb = 100 - yb, 100 - ya
        if not (1 <= na <= 99 and 0 <= nb <= 99):
            continue
        yes.append({"ts": ts, "ask": ya, "bid": yb})
        no.append({"ts": ts, "ask": na, "bid": nb})
    return yes, no


def series_list():
    rows, cursor = [], ""
    for _ in range(12):
        p = {"category": "Sports", "include_volume": "true", "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        x = get_json(f"{KALSHI}/series", p)
        rows.extend(x.get("series", []))
        cursor = x.get("cursor") or ""
        if not cursor:
            break
    return rows


def classify_series(s):
    text = " ".join([
        str(s.get("ticker") or ""), str(s.get("title") or ""),
        " ".join(str(x) for x in (s.get("tags") or [])),
    ]).lower()
    if any(k in text for k in ("nba", "wnba", "basketball", "ncaa basketball", "college basketball")):
        return "BASKETBALL"
    if any(k in text for k in ("nfl", "football", "ncaa football", "college football", "cfb")):
        return "FOOTBALL"
    if any(k in text for k in ("golf", "pga", "lpga", "masters", "us open golf", "open championship")):
        return "GOLF"
    return None


def series_volume(s):
    for k in ("volume_fp", "volume", "dollar_volume"):
        try:
            return float(s.get(k) or 0)
        except Exception:
            pass
    return 0.0


def markets_for_series(series_ticker):
    out = {}
    for endpoint, hist in ((f"{KALSHI}/markets", False), (f"{KALSHI}/historical/markets", True)):
        cursor = ""
        for _ in range(12):
            p = {"series_ticker": series_ticker, "limit": 1000}
            if not hist:
                p["status"] = "settled"
                p["mve_filter"] = "exclude"
            if cursor:
                p["cursor"] = cursor
            try:
                x = get_json(endpoint, p)
            except Exception:
                break
            for m in x.get("markets", []):
                if m.get("ticker"):
                    out[m["ticker"]] = m
            cursor = x.get("cursor") or ""
            if not cursor:
                break
    return list(out.values())


def candles(series, ticker, start_ts, end_ts):
    urls = [
        f"{KALSHI}/series/{series}/markets/{ticker}/candlesticks",
        f"{KALSHI}/historical/markets/{ticker}/candlesticks",
    ]
    for u in urls:
        try:
            x = get_json(u, {"start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": 1})
            rows = x.get("candlesticks", [])
            if rows:
                return rows
        except Exception:
            pass
    return []


def first_liquid_pair(yes, no, max_spread=12):
    for y, n in zip(yes, no):
        if y["ask"] - y["bid"] <= max_spread and n["ask"] - n["bid"] <= max_spread:
            return y, n
    return None


def build_market_record(bucket, series, m, cutoff):
    result = str(m.get("result") or "").lower()
    if result not in {"yes", "no"}:
        return None
    close = parse_dt(m.get("settlement_ts") or m.get("close_time") or m.get("expiration_time") or m.get("latest_expiration_time"))
    if not close or close < cutoff:
        return None
    hours = 9 if bucket in {"BASKETBALL", "FOOTBALL"} else 120
    cs = candles(series, m["ticker"], (close - timedelta(hours=hours)).timestamp(), (close + timedelta(minutes=10)).timestamp())
    if len(cs) < 15:
        return None
    yes, no = synthetic_rows(cs)
    if len(yes) < 15:
        return None
    base = first_liquid_pair(yes, no)
    if not base:
        return None
    y0, n0 = base
    total = y0["ask"] + n0["ask"]
    if total <= 0:
        return None
    py = 100 * y0["ask"] / total
    pn = 100 - py
    fav_side = "YES" if py >= pn else "NO"
    fav_pre = max(py, pn)
    yes_won = result == "yes"
    return {
        "bucket": bucket,
        "series": series,
        "ticker": m["ticker"],
        "event": m.get("event_ticker"),
        "close_ts": max(r["ts"] for r in yes),
        "baseline_ts": y0["ts"],
        "yes_pre": round(py, 2),
        "no_pre": round(pn, 2),
        "fav_side": fav_side,
        "fav_pre": round(fav_pre, 2),
        "yes_won": yes_won,
        "no_won": not yes_won,
        "yes_rows": yes,
        "no_rows": no,
    }


def side_rows(e, side):
    return e["yes_rows"] if side == "YES" else e["no_rows"]


def side_pre(e, side):
    return e["yes_pre"] if side == "YES" else e["no_pre"]


def side_won(e, side):
    return e["yes_won"] if side == "YES" else e["no_won"]


def opposite(side):
    return "NO" if side == "YES" else "YES"


def q_at(rows, ts):
    out = None
    for r in rows:
        if r["ts"] <= ts:
            out = r
        else:
            break
    return out


def exit_value(contracts, rows, after_ts, target_px=None, max_minutes=None, won=False):
    cutoff = after_ts + max_minutes * 60 if max_minutes else None
    for r in rows:
        if r["ts"] <= after_ts:
            continue
        if cutoff and r["ts"] > cutoff:
            break
        executable_bid = max(0.0, float(r["bid"]) - EXIT_FRICTION)
        if target_px is not None and executable_bid >= target_px:
            return contracts * executable_bid / 100.0, True
    if cutoff:
        q = q_at(rows, cutoff)
        if q:
            return contracts * max(0.0, float(q["bid"]) - EXIT_FRICTION) / 100.0, False
    return (contracts if won else 0.0), False


def replay_reversion(e, family, cfg):
    side = e["fav_side"] if family == "A" else ("YES" if abs(e["yes_pre"] - 50) <= abs(e["no_pre"] - 50) else "NO")
    pre = side_pre(e, side)
    if not (cfg["pre_min"] <= pre < cfg["pre_max"]):
        return None
    rows = [r for r in side_rows(e, side) if r["ts"] >= e["baseline_ts"]]
    trigger = None
    for r in rows:
        if r["ts"] > e["close_ts"] - cfg["min_remaining"] * 60:
            break
        if pre - r["ask"] >= cfg["drop"]:
            trigger = r
            break
    if not trigger:
        return None
    px = min(99.0, trigger["ask"] + ENTRY_FRICTION)
    contracts = 100.0 / px
    value, hit = exit_value(
        contracts, rows, trigger["ts"], target_px=px + cfg["target"],
        max_minutes=cfg["max_minutes"], won=side_won(e, side),
    )
    pnl = value - 1.0
    return {"family": family, "ticker": e["ticker"], "close_ts": e["close_ts"], "cost": 1.0, "pnl": pnl, "roi_pct": 100*pnl, "target_hit": hit}


def replay_hedge(e, cfg):
    side = e["fav_side"]
    pre = side_pre(e, side)
    if not (cfg["pre_min"] <= pre < cfg["pre_max"]):
        return None
    fav_rows = [r for r in side_rows(e, side) if r["ts"] >= e["baseline_ts"]]
    dog_side = opposite(side)
    dog_rows = [r for r in side_rows(e, dog_side) if r["ts"] >= e["baseline_ts"]]
    trigger = None
    for r in fav_rows:
        if r["ts"] > e["close_ts"] - cfg["min_remaining"]*60:
            break
        if r["ask"] >= cfg["leader_trigger"]:
            trigger = r
            break
    if not trigger:
        return None
    f0 = q_at(fav_rows, e["baseline_ts"])
    d0 = q_at(dog_rows, trigger["ts"])
    if not f0 or not d0:
        return None
    fav_px = min(99.0, f0["ask"] + ENTRY_FRICTION)
    fav_contracts = 100.0 / fav_px
    hedge_cost = cfg["hedge_mult"]
    dog_px = min(99.0, d0["ask"] + ENTRY_FRICTION)
    dog_contracts = hedge_cost * 100.0 / dog_px
    dog_value, hit = exit_value(dog_contracts, dog_rows, trigger["ts"], target_px=dog_px + cfg["target"], max_minutes=None, won=side_won(e, dog_side))
    fav_value = fav_contracts if side_won(e, side) else 0.0
    cost = 1.0 + hedge_cost
    pnl = fav_value + dog_value - cost
    return {"family": "E", "ticker": e["ticker"], "close_ts": e["close_ts"], "cost": cost, "pnl": pnl, "roi_pct": 100*pnl/cost, "target_hit": hit}


def replay_golf(e, family, cfg):
    # Golf YES = named player wins; NO = field wins. Most players begin as underdogs.
    pre = e["yes_pre"]
    if not (cfg["pre_min"] <= pre < cfg["pre_max"]):
        return None
    yr = [r for r in e["yes_rows"] if r["ts"] >= e["baseline_ts"]]
    nr = [r for r in e["no_rows"] if r["ts"] >= e["baseline_ts"]]
    if family == "G_CRASH":
        trigger = next((r for r in yr if pre - r["ask"] >= cfg["move"] and r["ts"] <= e["close_ts"]-cfg["min_remaining"]*60), None)
        if not trigger:
            return None
        px = min(99.0, trigger["ask"] + ENTRY_FRICTION); contracts = 100.0/px
        value, hit = exit_value(contracts, yr, trigger["ts"], target_px=px+cfg["target"], max_minutes=cfg["max_minutes"], won=e["yes_won"])
        pnl=value-1
    else:
        trigger = next((r for r in yr if r["ask"] - pre >= cfg["move"] and r["ts"] <= e["close_ts"]-cfg["min_remaining"]*60), None)
        if not trigger:
            return None
        nq=q_at(nr,trigger["ts"])
        if not nq:return None
        px=min(99.0,nq["ask"]+ENTRY_FRICTION); contracts=100.0/px
        value, hit=exit_value(contracts,nr,trigger["ts"],target_px=px+cfg["target"],max_minutes=cfg["max_minutes"],won=e["no_won"])
        pnl=value-1
    return {"family":family,"ticker":e["ticker"],"close_ts":e["close_ts"],"cost":1.0,"pnl":pnl,"roi_pct":100*pnl,"target_hit":hit}


def stats(rows):
    if not rows:
        return {"trades": 0, "roi_pct": None}
    cost = sum(x["cost"] for x in rows); pnl = sum(x["pnl"] for x in rows)
    eq = peak = dd = 0.0
    for x in sorted(rows, key=lambda z:z["close_ts"]):
        eq += x["pnl"]; peak=max(peak,eq); dd=min(dd,eq-peak)
    return {
        "trades":len(rows), "roi_pct":round(100*pnl/cost,2), "pnl_units":round(pnl,3),
        "positive_pct":round(100*sum(x["pnl"]>0 for x in rows)/len(rows),2),
        "avg_trade_roi_pct":round(sum(x["roi_pct"] for x in rows)/len(rows),2),
        "max_drawdown_units":round(dd,3), "target_hit_pct":round(100*sum(x["target_hit"] for x in rows)/len(rows),2),
    }


def split(events):
    e=sorted(events,key=lambda x:x["close_ts"]);n=len(e);a=max(1,int(n*.5));b=max(a+1,int(n*.75));return e[:a],e[a:b],e[b:]


def configs_for(bucket, family):
    if family=="A":
        return [{"pre_min":55,"pre_max":70,"drop":d,"target":t,"max_minutes":m,"min_remaining":r} for d,t,m,r in product([10,15,20],[5,8,10],[30,60,120],[30,60,120])]
    if family=="B":
        return [{"pre_min":45,"pre_max":55,"drop":d,"target":t,"max_minutes":m,"min_remaining":r} for d,t,m,r in product([8,12,16],[5,8,10],[30,60,120],[30,60,120])]
    if family=="E":
        return [{"pre_min":50,"pre_max":70,"leader_trigger":lt,"hedge_mult":h,"target":t,"min_remaining":r} for lt,h,t,r in product([75,80,85,90],[.10,.15,.20,.25],[3,5,7,10],[30,60,120])]
    if family in {"G_CRASH","G_SPIKE_FADE"}:
        return [{"pre_min":5,"pre_max":40,"move":mv,"target":t,"max_minutes":m,"min_remaining":r} for mv,t,m,r in product([5,10,15,20],[3,5,7,10],[60,180,360,720],[120,360,720])]
    return []


def evaluate(events, bucket, family, cfg):
    out=[]
    for e in events:
        if bucket=="GOLF":x=replay_golf(e,family,cfg)
        elif family=="E":x=replay_hedge(e,cfg)
        else:x=replay_reversion(e,family,cfg)
        if x:out.append(x)
    return out


def discover(bucket, events):
    dev,val,hold=split(events)
    families=["G_CRASH","G_SPIKE_FADE"] if bucket=="GOLF" else ["A","B","E"]
    result={"events":len(events),"split":{"development":len(dev),"validation":len(val),"holdout":len(hold)},"families":{}}
    for fam in families:
        candidates=[];cfgs=configs_for(bucket,fam)
        min_dev=10 if bucket=="FOOTBALL" else 15
        min_val=5 if bucket=="FOOTBALL" else 7
        for cfg in cfgs:
            ds=stats(evaluate(dev,bucket,fam,cfg));vs=stats(evaluate(val,bucket,fam,cfg))
            if ds["trades"]<min_dev or vs["trades"]<min_val:continue
            if ds["roi_pct"] is None or vs["roi_pct"] is None or min(ds["roi_pct"],vs["roi_pct"])<=0:continue
            score=min(ds["roi_pct"],vs["roi_pct"])+.10*(ds["roi_pct"]+vs["roi_pct"])/2
            candidates.append((score,cfg,ds,vs))
        candidates.sort(key=lambda x:x[0],reverse=True)
        if candidates:
            _,cfg,ds,vs=candidates[0];hs=stats(evaluate(hold,bucket,fam,cfg))
            result["families"][fam]={"configs_tested":len(cfgs),"robust_candidates":len(candidates),"config":cfg,"development":ds,"validation":vs,"holdout":hs,"decision":"KEEP" if hs["trades"]>=5 and hs["roi_pct"] is not None and hs["roi_pct"]>0 else "REJECT"}
        else:
            result["families"][fam]={"configs_tested":len(cfgs),"robust_candidates":0,"decision":"NO_ROBUST_CANDIDATE"}
    return result


def run(days=365,max_markets_per_bucket=1800):
    cutoff=datetime.now(timezone.utc)-timedelta(days=days)
    all_series=series_list(); by_bucket=defaultdict(list)
    for s in all_series:
        b=classify_series(s)
        if b:by_bucket[b].append(s)
    for b in by_bucket:by_bucket[b].sort(key=series_volume,reverse=True)
    coverage={}; bucket_events={}
    for bucket in ("BASKETBALL","FOOTBALL","GOLF"):
        ev=[]; scanned=0; series_used=[]; errors=[]
        for s in by_bucket.get(bucket,[]):
            if scanned>=max_markets_per_bucket:break
            ms=markets_for_series(s["ticker"]);series_used.append({"ticker":s["ticker"],"title":s.get("title"),"markets":len(ms)})
            for m in sorted(ms,key=lambda x:str(x.get("close_time") or x.get("settlement_ts") or ''),reverse=True):
                if scanned>=max_markets_per_bucket:break
                scanned+=1
                try:r=build_market_record(bucket,s["ticker"],m,cutoff)
                except Exception as ex:
                    errors.append({"ticker":m.get("ticker"),"error":str(ex)});continue
                if r:ev.append(r)
                if scanned%150==0:time.sleep(.08)
        bucket_events[bucket]=ev
        coverage[bucket]={"series_discovered":len(by_bucket.get(bucket,[])),"series_used":series_used,"markets_scanned":scanned,"usable_markets":len(ev),"errors":errors[:25]}
    result={"version":"EDGE-v1.8-multisport","period_days":days,"coverage":coverage,"results":{},"guardrails":["Research only; no live orders.","Single binary markets are converted into executable complementary YES/NO sides.","Entry friction +1c and exit friction -0.5c.","Rules selected on development+validation only; final chronological holdout untouched until selection.","Basketball/football pass is price-dynamics first; sport-state enrichment follows only surviving strategies.","Golf uses player-vs-field strategy analogues rather than team-game rules."]}
    for b in ("BASKETBALL","FOOTBALL","GOLF"):
        result["results"][b]=discover(b,bucket_events[b]) if len(bucket_events[b])>=20 else {"events":len(bucket_events[b]),"decision":"INSUFFICIENT_DATA"}
    Path("edge_v18_multisport_results.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    run(int(os.environ.get("EDGE_DAYS","365")),int(os.environ.get("EDGE_MAX_MARKETS_PER_BUCKET","1800")))
