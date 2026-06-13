"""Persist a run's report + metrics to results/ with a date stamp."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .audit import ConvictionAudit
from .integrity import IntegrityCheck, gate_passed

log = logging.getLogger("quantum_alpha.results")


def _jsonable(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _benchmark_summary(bt: Dict) -> Dict:
    out = {}
    for name, m in bt.get("benchmarks", {}).items():
        if "error" in m:
            out[name] = {"error": m["error"]}
        else:
            out[name] = {k: m.get(k) for k in
                         ("cagr", "total_return", "sharpe_ratio",
                          "max_drawdown", "active_cagr")}
    return out


def write_results(
    *,
    report_text: str,
    config,
    bt_results: Dict,
    integrity_checks: List[IntegrityCheck],
    conviction_audit: Optional[ConvictionAudit] = None,
    universe: Optional[List[str]] = None,
    results_dir: str = "results",
    stamp: Optional[str] = None,
) -> Path:
    """Write <stamp>_report.txt + <stamp>_metrics.json, return the dir."""
    stamp = stamp or datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(results_dir) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "report.txt").write_text(report_text)

    metrics = {
        "generated": datetime.now().isoformat(),
        "config": {
            "prediction_horizon_days": config.prediction_horizon_days,
            "rebalance_frequency_days": config.rebalance_frequency_days,
            "transaction_cost_bps": config.transaction_cost_bps,
            "max_universe_size": config.max_universe_size,
            "random_seed": config.random_seed,
        },
        "universe_size": len(universe) if universe else None,
        "universe": universe,
        "falsification_gate_passed": gate_passed(integrity_checks),
        "integrity": [
            {"name": c.name, "passed": c.passed, "gating": c.gating,
             "measure": c.measure, "detail": c.detail}
            for c in integrity_checks
        ],
    }

    if "error" not in bt_results:
        metrics["backtest"] = {
            "window": [bt_results["start_date"], bt_results["end_date"]],
            "num_rebalances": bt_results["num_rebalances"],
            "strategy": {k: bt_results.get(k) for k in
                         ("total_return", "cagr", "volatility", "sharpe_ratio",
                          "max_drawdown", "turnover_annualized", "total_costs",
                          "final_value", "num_trades")},
            "benchmarks": _benchmark_summary(bt_results),
            "oof_r2": bt_results.get("oof_r2"),
        }
    else:
        metrics["backtest"] = {"error": bt_results["error"]}

    if conviction_audit is not None and not conviction_audit.table.empty:
        metrics["conviction_audit"] = {
            "monotonic": conviction_audit.monotonic,
            "detail": conviction_audit.detail,
            "table": conviction_audit.table.reset_index().to_dict("records"),
        }

    (out_dir / "metrics.json").write_text(
        json.dumps(_jsonable(metrics), indent=2)
    )
    log.info(f"Results written to {out_dir}/")
    return out_dir
