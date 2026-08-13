from __future__ import annotations

import os

import edge_v16_strategy_f as base


MODEL_KEYS = ("base_run", "late_run", "starter_coef", "pitch_coef")


def fixed_brier(rows, cfg):
    """Score only model coefficients; fitted diagnostics such as train_brier are metadata."""
    model_cfg = {key: cfg[key] for key in MODEL_KEYS}
    vals = []
    for row in base.unique_fit_rows(rows):
        probability = base.fair_side(row, **model_cfg)
        outcome = 1.0 if row["won"] else 0.0
        vals.append((probability - outcome) ** 2)
    return sum(vals) / len(vals) if vals else 1.0


base.brier = fixed_brier

if __name__ == "__main__":
    base.run(int(os.environ.get("EDGE_DAYS", "60")))
