"""Report generation.

NOTE: the integrity block is a placeholder until Phase 4 generates each claim
from measured test outcomes (the CV remains known-broken until Phase 2).
"""

from datetime import datetime
from typing import Dict, List, Optional

from .config import Config


def report(
    opps: List[Dict],
    portfolio: Dict,
    bt_results: Dict,
    feature_importances: Optional[Dict[str, float]],
    config: Config,
) -> str:
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

    if "error" not in bt_results:
        hr()
        lines.append("BACKTEST (walk-forward, quarterly retraining, REAL data)")
        hr("-")
        lines.append(f"  Initial Capital:   ${bt_results['initial_capital']:>12,.0f}")
        lines.append(f"  Final Value:       ${bt_results['final_value']:>12,.0f}")
        lines.append(f"  Total Return:      {bt_results['total_return']*100:>+11.1f}%")
        lines.append(f"  CAGR:              {bt_results['cagr']*100:>+11.1f}%")
        lines.append(f"  Volatility:        {bt_results['volatility']*100:>11.1f}%")
        lines.append(f"  Sharpe Ratio:      {bt_results['sharpe_ratio']:>11.2f}")
        lines.append(f"  Max Drawdown:      {bt_results['max_drawdown']*100:>11.1f}%")
        lines.append(f"  Trades:            {bt_results['num_trades']:>11}")
        lines.append(f"  Rebalances:        {bt_results['num_rebalances']:>11}")
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

    # Hardcoded prose — replaced with measured pass/fail output in Phase 4.
    hr()
    lines.append("STATISTICAL INTEGRITY & HONEST DISCLOSURE")
    hr("-")
    lines.append("  NOTE: this block is hardcoded prose pending Phase 4; until the")
    lines.append("  falsification suite lands, treat every claim here as UNVERIFIED.")
    lines.append("  - Data source: Yahoo Finance (real market data)")
    lines.append("  - Universe = current S&P constituents → SURVIVORSHIP-BIASED")
    lines.append("  - Past backtest performance does NOT guarantee future returns")
    hr()

    return "\n".join(lines)
