from __future__ import annotations

import os
import edge_v20_state_sports as state

_original_classify = state.classify_series


def basketball_only(series):
    bucket = _original_classify(series)
    return "BASKETBALL" if bucket == "BASKETBALL" else None


state.classify_series = basketball_only

if __name__ == "__main__":
    days = int(os.environ.get("EDGE_DAYS", "240"))
    max_events = int(os.environ.get("EDGE_MAX_EVENTS", "100"))
    state.run(days=days, max_events=max_events)
