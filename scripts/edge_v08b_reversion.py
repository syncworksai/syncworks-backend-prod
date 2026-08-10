from __future__ import annotations

import bisect
import time
from collections import defaultdict
from datetime import date, timedelta

import edge_v08_reversion as base
from edge_v07_pregame_holdout import (
    candle_ask,
    candles,
    latest_pregame_ask,
    market_team,
    markets_for_day,
    mlb_games,
    play_states,
)
from edge_v07c_pregame_holdout import last_trade_before


def select_same_game_market(markets, away, home, gstart, first_state_ts, last_state_ts):
    """Choose the Kalshi event that actually traded during this MLB game's clock window.

    Back-to-back series can produce multiple KXMLBGAME events containing the same two team
    codes. Team-name matching alone can therefore pair a game to tomorrow's market. We group
    candidate markets by event_ticker and score each group by the number of one-minute candles
    that overlap the current MLB game's timeline. The event with the strongest overlap wins.
    """
    groups = defaultdict(list)
    for m in markets:
        event = str(m.get("event_ticker") or "")
        if not event.startswith("KXMLBGAME-"):
            continue
        if away not in event or home not in event:
            continue
        if market_team(m) not in {away, home}:
            continue
        groups[event].append(m)

    best = None
    best_score = 0
    best_hist = None
    for event, ms in groups.items():
        if len({market_team(m) for m in ms}) < 2:
            continue
        hist = {m["ticker"]: candles(m, gstart - 7200, last_state_ts + 900) for m in ms}
        score = 0
        for cs in hist.values():
            score += sum(
                1 for c in cs
                if first_state_ts - 3600 <= int(c.get("end_period_ts") or 0) <= last_state_ts + 900
            )
        if score > best_score:
            best_score = score
            best = ms
            best_hist = hist
    return best or [], best_hist or {}, best_score


def corrected_build_observations(days=24):
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    obs = []
    coverage = {
        "days": days,
        "games": 0,
        "matched_games": 0,
        "markets": 0,
        "candles": 0,
        "pregame_baselines": 0,
        "baseline_from_candle": 0,
        "baseline_from_trade": 0,
        "ambiguous_same_team_events_resolved": 0,
        "errors": [],
    }

    for i in range(days):
        day = start + timedelta(days=i)
        try:
            games = mlb_games(day)
            markets = markets_for_day(day)
        except Exception as exc:
            coverage["errors"].append({"date": str(day), "error": str(exc)})
            continue
        coverage["games"] += len(games)
        coverage["markets"] += len(markets)

        for game_pk, away, home, gstart in games:
            try:
                states = play_states(game_pk)
            except Exception as exc:
                coverage["errors"].append({"game_pk": game_pk, "error": str(exc)})
                continue
            if not states:
                continue
            times = [x["ts"] for x in states]
            first_state_ts, last_state_ts = times[0], times[-1]

            raw_events = {
                str(m.get("event_ticker") or "") for m in markets
                if away in str(m.get("event_ticker") or "") and home in str(m.get("event_ticker") or "")
            }
            if len(raw_events) > 1:
                coverage["ambiguous_same_team_events_resolved"] += 1

            matched, hist, overlap_score = select_same_game_market(
                markets, away, home, gstart, first_state_ts, last_state_ts
            )
            if len(matched) < 2 or overlap_score <= 0:
                continue
            coverage["candles"] += sum(len(v) for v in hist.values())

            side_market = {market_team(m): m for m in matched}
            am, hm = side_market.get(away), side_market.get(home)
            if not am or not hm:
                continue
            ap = latest_pregame_ask(hist.get(am["ticker"], []), first_state_ts)
            hp = latest_pregame_ask(hist.get(hm["ticker"], []), first_state_ts)
            source = "candle"
            if ap is None or hp is None:
                ap = last_trade_before(am["ticker"], gstart - 86400, first_state_ts)
                hp = last_trade_before(hm["ticker"], gstart - 86400, first_state_ts)
                source = "trade"
            if ap is None or hp is None or ap + hp <= 0:
                continue

            preaway = ap / (ap + hp)
            coverage["pregame_baselines"] += 1
            coverage["matched_games"] += 1
            coverage[f"baseline_from_{source}"] += 1

            for m in matched:
                side = market_team(m)
                result = str(m.get("result") or "").lower()
                if result not in {"yes", "no"}:
                    continue
                sidepre = 100 * (preaway if side == away else 1 - preaway)
                for c in hist.get(m["ticker"], []):
                    ts = int(c.get("end_period_ts") or 0)
                    ask = candle_ask(c)
                    bid = base.candle_bid(c)
                    idx = bisect.bisect_right(times, ts) - 1
                    if idx < 0 or ts <= first_state_ts or ts > last_state_ts + 900 or ask is None or not 1 <= ask <= 99:
                        continue
                    if bid is None or not 0 <= bid <= 99:
                        bid = max(0, ask - 2)
                    st = states[idx]
                    trailing = (
                        (side == away and st["away_score"] < st["home_score"])
                        or (side == home and st["home_score"] < st["away_score"])
                    )
                    obs.append({
                        "date": str(day), "game_pk": game_pk, "ticker": m["ticker"], "side": side,
                        "away": away, "home": home, "away_score": st["away_score"], "home_score": st["home_score"],
                        "inning": st["inning"], "half": st["half"], "outs": st["outs"], "ask": ask, "bid": bid,
                        "won": result == "yes", "ts": ts, "pregame_away": preaway,
                        "pregame_side": round(sidepre, 2), "trailing": trailing,
                        "deficit": abs(st["away_score"] - st["home_score"]), "baseline_source": source,
                    })
            time.sleep(.01)
    return start, end, obs, coverage


if __name__ == "__main__":
    base.build_observations = corrected_build_observations
    base.run(int(__import__("os").environ.get("EDGE_DAYS", "24")))
