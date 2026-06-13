"""Report generation.

The integrity section is generated from measured IntegrityChecks
(quantum_alpha.integrity), never hardcoded prose (CLAUDE.md invariant 7). When
the falsification gate has not passed, the backtest section is withheld and
flagged as not meaningful (invariant 6).
"""

from datetime import datetime
from typing import Dict, List, Optional

from .config import Config
from .integrity import IntegrityCheck, gate_passed


def report(
    opps: List[Dict],
    portfolio: Dict,
    bt_results: Dict,
    feature_importances: Optional[Dict[str, float]],
    config: Config,
    integrity_checks: Optional[List[IntegrityCheck]] = None,
) -> str:
    integrity_checks = integrity_checks or []
    gate_ok = gate_passed(integrity_checks) if integrity_checks else False
    have_gate = any(c.gating for c in integrity_checks)
    lines = []

    def hr(char="="):
        lines.append(char * 90)

    def blank():
        lines.append("")

    hr()
    lines.append("QUANTUM ALPHA v5.1 — LIVE MARKET RESEARCH REPORT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Horizon: {config.prediction_horizon_days} trading days")
    lines.append("WARNING: This is a research tool using REAL market data.")
    lines.append("Past patterns do not guarantee future results. "
                 "You bear full responsibility.")
    hr()
    blank()

    lines.append("CONVICTION GUIDE")
    hr("-")
    lines.append("  HIGH:         80% CI entirely above 0, high model agreement, "
                 "low tree variance")
    lines.append("  MEDIUM:       Positive expected return, CI mostly above 0, "
                 "decent agreement")
    lines.append("  LOW:          Positive expected but wide CI or weaker agreement")
    lines.append("  SPECULATIVE:  Positive expected but model is highly uncertain")
    lines.append("  AVOID:        Negative expected return")
    blank()

    lines.append(f"SIGNAL SCAN — {len(opps)} stocks analysed")
    hr("-")
    lines.append(f"{'#':<3} {'Ticker':<7} {'Expect':>7} {'80% CI':>17} "
                 f"{'Conf':>5} {'Convic':<12} {'Sector':<15} {'Vol':>5}")
    hr("-")

    shown = 0
    for i, o in enumerate(opps, 1):
        if shown >= 30:
            break
        conviction = o.get("conviction", "?")
        if conviction == "AVOID" and shown > 15:
            continue
        ci_str = f"[{o['ci_low_pct']:>6}, {o['ci_high_pct']:>6}]"
        lines.append(
            f"{i:<3} {o['ticker']:<7} {o['expected_return_pct']:>7} {ci_str:>17} "
            f"{o['confidence_pct']:>5} {conviction:<12} "
            f"{o['sector']:<15} {o['volatility']*100:.0f}%"
        )
        shown += 1
    blank()

    hr()
    lines.append("UNCERTAINTY BREAKDOWN — Top 10")
    hr("-")
    lines.append(f"{'Ticker':<7} {'RF Pred':>8} {'GB Pred':>8} {'Spread':>8} "
                 f"{'TreeStd':>8} {'Verdict':<12}")
    hr("-")
    for o in opps[:10]:
        spread = abs(o.get("rf_pred", 0) - o.get("gb_pred", 0))
        lines.append(
            f"{o['ticker']:<7} {o.get('rf_pred',0)*100:>+7.1f}% "
            f"{o.get('gb_pred',0)*100:>+7.1f}% {spread*100:>7.1f}% "
            f"{o.get('tree_std',0)*100:>7.1f}% "
            f"{o.get('conviction','?'):<12}"
        )
    blank()

    hr()
    lines.append("RECOMMENDED PORTFOLIO")
    hr("-")
    pos = portfolio.get("positions", {})
    met = portfolio.get("metrics", {})
    if pos:
        lines.append(f"{'Ticker':<7} {'Weight':>7} {'Expect':>8} {'80% CI':>17} "
                     f"{'Convic':<10} {'Sector':<15}")
        hr("-")
        for t, info in sorted(pos.items(), key=lambda x: -x[1]["weight"]):
            ci_str = f"[{info.get('ci_low',0)*100:+.1f}%, {info.get('ci_high',0)*100:+.1f}%]"
            lines.append(
                f"{t:<7} {info['weight']*100:>6.1f}% "
                f"{info['expected_return']*100:>+7.1f}% {ci_str:>17} "
                f"{info.get('conviction','?'):<10} "
                f"{info['factors'].get('sector','?'):<15}"
            )
    else:
        lines.append("  No positions pass filters — model sees insufficient edge.")
    blank()

    lines.append("PORTFOLIO METRICS")
    hr("-")
    lines.append(f"  Expected Return:   {met.get('expected_return',0)*100:+.1f}%")
    lines.append(f"  Expected Vol:      {met.get('expected_volatility',0)*100:.1f}%")
    lines.append(f"  Sharpe Ratio:      {met.get('sharpe_ratio',0):.2f}")
    lines.append(f"  Positions:         {met.get('num_positions',0)}")
    lines.append(f"  Max Position:      {met.get('max_position',0)*100:.1f}%")

    sw = met.get("sector_weights", {})
    if sw:
        blank()
        lines.append("SECTOR ALLOCATION")
        hr("-")
        for s, w in sorted(sw.items(), key=lambda x: -x[1]):
            lines.append(f"  {s:<20} {w*100:.1f}%")
    blank()

    if "error" not in bt_results and have_gate and not gate_ok:
        hr()
        lines.append("BACKTEST — WITHHELD")
        hr("-")
        lines.append("  The falsification gate did NOT pass, so backtest results")
        lines.append("  are not treated as meaningful and are withheld here. See")
        lines.append("  the STATISTICAL INTEGRITY section for the failing check.")
        blank()
    elif "error" not in bt_results:
        hr()
        lines.append("BACKTEST — NET OF COSTS, WITH BENCHMARKS ON IDENTICAL DATES")
        if have_gate:
            lines.append("  (falsification gate: PASSED)")
        hr("-")
        lines.append(
            f"  Window: {bt_results['start_date'].date()} → "
            f"{bt_results['end_date'].date()}   "
            f"({bt_results['num_rebalances']} rebalances, every "
            f"{bt_results['rebalance_frequency_days']} trading days = "
            f"{bt_results['periods_per_year']:.0f} periods/yr)"
        )
        lines.append(
            f"  Costs: {bt_results['cost_bps_per_side']:.0f} bps per side on "
            f"traded notional, applied to strategy AND benchmarks"
        )
        blank()

        benchmarks = bt_results.get("benchmarks", {})
        cols = [("Strategy", bt_results)]
        for name in ("SPY", "equal_weight"):
            bm = benchmarks.get(name, {})
            label = "SPY" if name == "SPY" else "Equal-Weight"
            if bm and "error" not in bm:
                cols.append((label, bm))
            else:
                lines.append(f"  [{label} benchmark unavailable: "
                             f"{bm.get('error', 'missing')}]")

        header = f"  {'':<22}" + "".join(f"{label:>14}" for label, _ in cols)
        lines.append(header)
        hr("-")

        def row(label, key, fmt):
            cells = "".join(
                f"{fmt(metrics[key]):>14}" if key in metrics else f"{'—':>14}"
                for _, metrics in cols
            )
            lines.append(f"  {label:<22}{cells}")

        pct = lambda v: f"{v*100:+.1f}%"
        pos_pct = lambda v: f"{v*100:.1f}%"
        num = lambda v: f"{v:.2f}"
        usd = lambda v: f"${v:,.0f}"

        row("Final Value", "final_value", usd)
        row("Total Return", "total_return", pct)
        row("CAGR", "cagr", pct)
        row("Volatility (ann.)", "volatility", pos_pct)
        row("Sharpe Ratio", "sharpe_ratio", num)
        row("Max Drawdown", "max_drawdown", pct)
        row("Turnover (ann., 2-side)", "turnover_annualized", pos_pct)
        row("Total Costs", "total_costs", usd)
        blank()

        for label, metrics in cols[1:]:
            lines.append(
                f"  Active CAGR vs {label:<13}: "
                f"{(bt_results['cagr'] - metrics['cagr'])*100:+.2f}%"
            )
        if bt_results.get("oof_r2") is not None:
            lines.append(f"  Model OOF R² (last retrain, purged CV): "
                         f"{bt_results['oof_r2']:.4f}")
    else:
        lines.append(f"Backtest: {bt_results['error']}")
    blank()

    if feature_importances:
        hr()
        lines.append("MOST PREDICTIVE FEATURES (RF importance)")
        hr("-")
        sorted_fi = sorted(feature_importances.items(), key=lambda x: -x[1])[:15]
        for name, imp in sorted_fi:
            bar = "#" * int(imp * 200)
            lines.append(f"  {name:<25} {imp:.4f}  {bar}")
    blank()

    # Integrity section — every line is a measured check (invariant 7).
    hr()
    lines.append("STATISTICAL INTEGRITY — MEASURED, NOT ASSERTED")
    hr("-")
    if not integrity_checks:
        lines.append("  No integrity checks were run for this report.")
    else:
        n_pass = sum(c.passed for c in integrity_checks)
        gate_line = (
            "GATE PASSED" if gate_ok else
            ("GATE FAILED — results withheld" if have_gate else "GATE NOT RUN")
        )
        lines.append(f"  Checks passed: {n_pass}/{len(integrity_checks)}    "
                     f"Falsification {gate_line}")
        blank()
        for c in integrity_checks:
            flag = "[GATE]" if c.gating else "      "
            lines.append(f"  {flag} {c.status:<4} {c.name}")
            lines.append(f"              {c.measure}")
            if c.detail:
                lines.append(f"              {c.detail}")
    blank()
    lines.append("  Data source: Yahoo Finance (real market data). Past backtest")
    lines.append("  performance does NOT guarantee future returns.")
    hr()

    return "\n".join(lines)
