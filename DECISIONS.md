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
The corrected pipeline shows **no exploitable, trustworthy edge** — exactly as
CLAUDE.md anticipated. The two runs below look opposite on raw return, and that
contradiction is the whole point: raw return over a single one-year window is
noise, and every rigorous measure agrees there is no signal.

| Run (net of 10 bps/side, 12 monthly rebalances) | Strat CAGR | SPY | Equal-Weight | Strat vol | Strat Sharpe | EW Sharpe | OOF R² | perm R² |
|---|---|---|---|---|---|---|---|---|
| 20-ticker, 1y | −13.2% | +25.8% | +46.1% | 9.4% | −1.87 | 4.33 | ~0.002 | — |
| 49-name S&P, 1y | **+43.5%** | +24.8% | +25.4% | **52.1%** | **0.75** | 2.46 | ~0.009–0.014 | 0.005 |

Read these together, not apart:

- **Out-of-fold R² is ≈ 0 in both runs** (0.002–0.014), statistically
  indistinguishable from zero for monthly equity returns. On the S&P run the
  label-permutation control scored 0.005 against a real 0.009 — both under the
  0.02 gate, both noise. That is the signature of **no edge and no leakage at
  once**: shuffling the labels barely changes anything because the features
  were never predicting the labels.
- **The S&P run's +18% "active return" is not edge — it is variance.** The
  strategy ran at **52% annualized volatility** (vs ~9% for the benchmarks),
  a **−27% max drawdown** (vs −4%), and a **Sharpe of 0.75 against the
  equal-weight's 2.46**. Risk-adjusted, it lost decisively. A 12-observation
  window from a high-variance, concentrated portfolio will sometimes print a
  big number; the OOF R² and the permutation control tell you not to bank on it.
- **Turnover ~380%/yr** means costs are a real, persistent drag in both runs;
  the optimizer churns into a concentrated Sharpe-chasing subset.
- **Conviction tiers do not reliably earn their labels.** HIGH essentially
  never populates (the calibrated 80% interval is wide, so `ci_low > 0` is
  rare); on the S&P run MEDIUM (n=42) edged LOW, but the AVOID tier realized
  *positive* (+1.9%), which is itself evidence the tiers are not separating
  outcomes. The audit reports the populated ordering plainly rather than
  dressing it up.

## Decision
**Keep Quantum Alpha as a methodology lab, not a signal to trade.** Out-of-fold
R² is ≈ 0 and the permutation control sits in the same band, so there is no
statistical signal to act on; the one window that printed a large positive
active return did so at 52% volatility and a sub-benchmark Sharpe — variance,
not edge. No honest parameter change would manufacture a trustworthy edge
without reintroducing leakage, which the prime directive forbids. This *is* the
success condition of the project: a pipeline whose numbers can be trusted,
even though — and especially when — they show no edge.

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
strategy-vs-equal-weight comparison the one to trust. On a single window the
strategy can beat it on raw return, but only by taking far more risk
(52% vol, −27% drawdown) for a worse Sharpe — and with OOF R² ≈ 0 and the
permutation control in the same band, there is no signal to expect that to
repeat.
