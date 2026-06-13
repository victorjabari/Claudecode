"""Out-of-sample conviction-tier audit.

The conviction tiers (HIGH / MEDIUM / LOW / SPECULATIVE) are only meaningful
if, out of sample, higher tiers actually realize higher forward returns. This
audit replays the SAME classify_conviction logic over the purged out-of-fold
predictions and reports realized forward return by tier. If the ordering does
not hold (HIGH ≥ MEDIUM ≥ LOW), the tiers are decoration, not signal — and the
audit says so.

The out-of-fold rows carry pred, realized y, tree_std and a model-agreement
confidence. The prediction interval used for tiering is reconstructed from the
calibrated residual std (the same calibrated component used at prediction
time: pred ± 1.28·σ_resid for the 80% interval); per-row RF tree percentiles
are not retained out of fold.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from .portfolio import classify_conviction

log = logging.getLogger("quantum_alpha.audit")

TIER_ORDER = ["HIGH", "MEDIUM", "LOW", "SPECULATIVE", "AVOID"]
# Tiers whose ordering we assert (the actionable, positive-expected tiers).
ACTIONABLE = ["HIGH", "MEDIUM", "LOW"]


@dataclass
class ConvictionAudit:
    table: pd.DataFrame      # per-tier: n, mean_pred, mean_realized, hit_rate
    monotonic: bool          # HIGH >= MEDIUM >= LOW in mean realized return
    detail: str

    def passed(self) -> bool:
        return self.monotonic


def conviction_tier_audit(
    oof_frame: Optional[pd.DataFrame],
    calibrated_std: float,
) -> Optional[ConvictionAudit]:
    """Classify each OOF row into a conviction tier and tabulate realized y."""
    if oof_frame is None or oof_frame.empty:
        return None

    df = oof_frame.copy()
    z = 1.28   # 80% interval, matches prediction-time calibration
    ci_low = df["pred"] - z * calibrated_std
    ci_high = df["pred"] + z * calibrated_std

    tiers = [
        classify_conviction(
            expected_return=float(p), ci_low=float(lo), ci_high=float(hi),
            confidence=float(c), tree_std=float(ts),
        )
        for p, lo, hi, c, ts in zip(
            df["pred"], ci_low, ci_high, df["confidence"], df["tree_std"],
        )
    ]
    df["tier"] = tiers

    rows: List[dict] = []
    for tier in TIER_ORDER:
        sub = df[df["tier"] == tier]
        if len(sub) == 0:
            continue
        rows.append({
            "tier": tier,
            "n": int(len(sub)),
            "mean_pred": float(sub["pred"].mean()),
            "mean_realized": float(sub["y"].mean()),
            "median_realized": float(sub["y"].median()),
            "hit_rate": float((sub["y"] > 0).mean()),
        })
    table = pd.DataFrame(rows).set_index("tier") if rows else pd.DataFrame()

    realized = {r["tier"]: r["mean_realized"] for r in rows}
    present = [t for t in ACTIONABLE if t in realized]
    monotonic = all(
        realized[present[i]] >= realized[present[i + 1]]
        for i in range(len(present) - 1)
    ) if len(present) >= 2 else False

    if len(present) < 2:
        detail = (f"only {len(present)} actionable tier(s) populated "
                  f"out of sample — ordering cannot be judged")
    elif monotonic:
        detail = ("realized forward return is monotonic across "
                  + " ≥ ".join(present))
    else:
        detail = ("realized ordering is NOT monotonic across "
                  + " / ".join(present) + " — tiers are not adding signal")

    return ConvictionAudit(table=table, monotonic=monotonic, detail=detail)
