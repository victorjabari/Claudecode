# Decision record — Quantum Alpha after the trustworthiness refactor

This is the Phase 5 decision point from REFACTOR_PLAN.md, written from the
actual measured outcomes of the refactor (Phases 0–4), not from hope.

## What the refactor changed
The pipeline now enforces every hard invariant in CLAUDE.md, and the report
proves it from measurements rather than asserting it in prose:

- **No look-ahead.** All 11 `.info`-derived feature columns deleted; the
  feature matrix is price/volume only. The no-look-ahead test perturbs every
  row after date *t* and confirms features at ≤ *t* are bit-for-bit unchanged
  (`max|Δ| = 0`).
- **No ticker fingerprints.** No static per-ticker columns; a model trained on
  static-only features memorizes in-sample but scores OOF R² ≤ 0 on an
  embargoed split.
- **Temporal CV only.** One pooled `(date, ticker)` panel; purged
  walk-forward folds with a 21-day embargo. Every fold satisfies
  `pos(max train date) + embargo < pos(min val date)` (measured min gap 22 > 21).
- **Costs + benchmarks mandatory.** 10 bps/side on traded notional; SPY and
  equal-weight benchmarks run through the same engine on identical dates.
- **Falsification gates results.** Permuting forward-return labels within each
  date collapses OOF R² to ≈ 0; a failed gate withholds the backtest output.

## What the honest numbers say
The corrected pipeline shows **no exploitable edge**, exactly as CLAUDE.md
anticipated. Representative measured results:

| Run (net of 10 bps/side) | Strategy CAGR | SPY | Equal-Weight | OOF R² |
|---|---|---|---|---|
| 20-ticker, 1y window | −13.2% | +25.8% | +46.1% | ~0.002–0.003 |

- Out-of-fold R² sits in the 0.00–0.005 band — statistically indistinguishable
  from zero for monthly equity returns. The label-permutation control lands in
  the same band (real 0.0018 vs permuted 0.0140, both < the 0.02 gate), which
  is the signature of **no edge and no leakage** at once.
- The strategy underperforms equal-weight badly, and ~380%/yr turnover means
  costs actively erode it. The optimizer is concentrating into a Sharpe-chasing
  subset whose realized returns trail simply holding the universe.
- Conviction tiers do not earn their labels out of sample: HIGH/MEDIUM rarely
  populate (the calibrated 80% interval is wide, so `ci_low > 0` is rare), and
  the realized-return ordering across the actionable tiers does not hold. The
  audit reports this rather than hiding it.

## Decision
**Keep Quantum Alpha as a methodology lab, not a signal to trade.** The
net-of-cost edge versus equal-weight is negative, and there is no honest
parameter change that would fix that without reintroducing leakage — which the
prime directive forbids. This is the success condition of the project: a
pipeline whose numbers can be trusted, even though they show no edge.

Real-money effort should move to the **portfolio/risk layer**, where the
expected value per hour is highest and which does not depend on this signal
having an edge:

1. **Standalone risk engine** (separate branch): volatility-targeting overlay,
   max-drawdown kill-switch, position/sector caps — reusable on *any* signal,
   including a plain equal-weight or index sleeve.
2. **Cross-sectional long–short quantile evaluation**, which partially nets out
   both survivorship bias and market beta.
3. **Point-in-time fundamentals** as the *only* honest way fundamentals
   re-enter the feature set — gated on a real data source, not yfinance
   snapshots.

## Standing caveat
The universe is today's S&P survivors (yfinance has no delisted tickers), so
every absolute number is survivorship-biased upward. The equal-weight
benchmark shares the same survivor set, which is what makes the
strategy-vs-equal-weight comparison the one to trust — and by that comparison,
the strategy has no edge.
