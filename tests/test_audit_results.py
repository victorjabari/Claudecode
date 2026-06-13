"""Conviction-tier audit and results persistence."""

import json

import numpy as np
import pandas as pd

from quantum_alpha.audit import conviction_tier_audit
from quantum_alpha.config import Config
from quantum_alpha.integrity import IntegrityCheck
from quantum_alpha.results import write_results


def _oof_frame(tiers_spec):
    """Build an OOF frame whose rows land in intended tiers.

    tiers_spec: list of (pred, tree_std, confidence, realized_y).
    """
    idx = pd.MultiIndex.from_arrays(
        [pd.bdate_range("2024-01-01", periods=len(tiers_spec)),
         [f"T{i}" for i in range(len(tiers_spec))]],
        names=["date", "ticker"],
    )
    return pd.DataFrame(
        {
            "pred": [s[0] for s in tiers_spec],
            "tree_std": [s[1] for s in tiers_spec],
            "confidence": [s[2] for s in tiers_spec],
            "y": [s[3] for s in tiers_spec],
        },
        index=idx,
    )


def test_audit_flags_monotonic_ordering():
    # calibrated_std small so HIGH's ci_low > 0 is reachable.
    cal = 0.02
    # HIGH: pred high, low tree_std, high conf, big realized.
    # MEDIUM: moderate. LOW: low conf. Realized returns decrease with tier.
    spec = []
    for _ in range(20):
        spec.append((0.10, 0.02, 0.9, 0.08))    # HIGH
    for _ in range(20):
        spec.append((0.04, 0.10, 0.5, 0.03))    # MEDIUM
    for _ in range(20):
        spec.append((0.02, 0.10, 0.35, 0.01))   # LOW
    audit = conviction_tier_audit(_oof_frame(spec), cal)

    assert audit is not None
    assert set(["HIGH", "MEDIUM", "LOW"]).issubset(set(audit.table.index))
    assert audit.monotonic
    assert audit.passed()
    # Realized means strictly decrease HIGH > MEDIUM > LOW here.
    r = audit.table["mean_realized"]
    assert r["HIGH"] > r["MEDIUM"] > r["LOW"]


def test_audit_flags_broken_ordering():
    cal = 0.02
    spec = []
    for _ in range(20):
        spec.append((0.10, 0.02, 0.9, 0.00))    # HIGH but realizes ~0
    for _ in range(20):
        spec.append((0.04, 0.10, 0.5, 0.06))    # MEDIUM realizes more
    for _ in range(20):
        spec.append((0.02, 0.10, 0.35, 0.02))   # LOW
    audit = conviction_tier_audit(_oof_frame(spec), cal)

    assert audit is not None
    assert not audit.monotonic   # HIGH < MEDIUM in realized return
    assert "NOT monotonic" in audit.detail


def test_audit_handles_empty_frame():
    assert conviction_tier_audit(None, 0.05) is None
    assert conviction_tier_audit(pd.DataFrame(), 0.05) is None


def test_write_results_emits_report_and_metrics(tmp_path):
    config = Config()
    bt_results = {
        "start_date": pd.Timestamp("2024-01-01"),
        "end_date": pd.Timestamp("2025-01-01"),
        "num_rebalances": 12,
        "total_return": -0.13, "cagr": -0.13, "volatility": 0.09,
        "sharpe_ratio": -1.8, "max_drawdown": -0.13,
        "turnover_annualized": 3.8, "total_costs": 3503.0,
        "final_value": 868_391.0, "num_trades": 240,
        "oof_r2": 0.003,
        "benchmarks": {
            "equal_weight": {"cagr": 0.46, "total_return": 0.46,
                             "sharpe_ratio": 4.3, "max_drawdown": -0.02,
                             "active_cagr": -0.59},
            "SPY": {"cagr": 0.26, "total_return": 0.26, "sharpe_ratio": 2.5,
                    "max_drawdown": -0.03, "active_cagr": -0.39},
        },
    }
    checks = [
        IntegrityCheck("No look-ahead", True, "max|Δ|=0", "ok"),
        IntegrityCheck("Falsification gate", True, "perm R² 0.001", "ok",
                       gating=True),
    ]

    out_dir = write_results(
        report_text="REPORT BODY", config=config, bt_results=bt_results,
        integrity_checks=checks, conviction_audit=None,
        universe=["AAPL", "MSFT"], results_dir=str(tmp_path), stamp="2026-06-13",
    )

    assert (out_dir / "report.txt").read_text() == "REPORT BODY"
    metrics = json.loads((out_dir / "metrics.json").read_text())
    assert metrics["falsification_gate_passed"] is True
    assert metrics["backtest"]["strategy"]["cagr"] == -0.13
    assert metrics["backtest"]["benchmarks"]["equal_weight"]["cagr"] == 0.46
    assert metrics["universe"] == ["AAPL", "MSFT"]
    assert len(metrics["integrity"]) == 2
