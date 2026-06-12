# REFACTOR_PLAN.md — quantum_alpha_v5.py → a trustworthy pipeline

Work the phases in order. One phase = one commit. After each phase: `pytest`,
then a 20-ticker smoke run. Expected global outcome: the backtest edge shrinks
toward zero as leaks close. **That is success, not failure** — see CLAUDE.md.

## Phase 0 — Make it run at all
- [ ] `python3 -m venv .venv && source .venv/bin/activate`
- [ ] `requirements.txt` with pinned versions (yfinance, pandas, numpy,
      scikit-learn, scipy, lxml, pyarrow, pytest); `pip install -r requirements.txt`
- [ ] Parquet cache layer: prices + the few `.info` fields used for filtering →
      `data/cache/`, keyed by fetch date; skip the network when fresh (< 24 h)
- [ ] Retry/backoff wrapper around all yfinance calls; per-ticker failures are
      logged and skipped, never fatal
- [ ] Fix the Config mutation bug: CLI args construct
      `Config(prediction_horizon_days=args.horizon)` — no class-attribute writes
- [ ] Smoke test passes: 20 tickers fetch → features compute → no crash

## Phase 1 — Remove look-ahead and ticker fingerprints
- [ ] Delete every `.info`-derived feature column from `_compute_features`:
      pe_ratio, forward_pe, pb_ratio, revenue_growth, earnings_growth,
      profit_margin, roe, debt_to_equity, beta, dividend_yield, peg_ratio
- [ ] `.info` survives only in universe filters (marketCap, averageVolume) and
      report metadata — never in X
- [ ] Audit every remaining feature for shift correctness: any rolling stat whose
      comment claims "uses past data only" must actually be shifted so the value
      at t depends on ≤ t−1 inputs (several currently use the same-day close
      against a shifted MA — decide and document the convention, then enforce it)
- [ ] Add the fingerprint test: model trained on static-only features →
      OOF R² ≤ 0

## Phase 2 — Fix cross-validation and uncertainty calibration
- [ ] Build one pooled panel: MultiIndex (date, ticker), sorted by date — replace
      the per-ticker `np.vstack` ordering
- [ ] Implement purged k-fold with embargo = horizon (21 trading days); remove
      TimeSeriesSplit-on-stacked-arrays entirely
- [ ] Recompute OOF predictions, the Ridge meta-learner, and residual calibration
      on the corrected splits
- [ ] Add the CV ordering test: every fold satisfies
      max(train dates) + embargo < min(val dates)
- [ ] Inspect corrected OOF R²: expect ≈ 0.00–0.03 on real monthly equity data.
      Anything above ~0.05 → hunt for remaining leakage before proceeding

## Phase 3 — Honest backtester
- [ ] Apply 10 bps per side on every traded notional; accumulate and report
      annualized turnover
- [ ] Add benchmarks on identical dates: SPY total return and equal-weight of the
      same universe (same survivor set, so the comparison is apples-to-apples)
- [ ] Rename `daily_ret` → `period_ret`; verify the annualization factor matches
      the actual rebalance frequency
- [ ] Report net-of-cost: total return, CAGR, vol, Sharpe, max drawdown,
      turnover, and active return vs each benchmark

## Phase 4 — Falsification suite
- [ ] Permutation test: shuffle forward returns within each date, run the full
      train→backtest loop → |strategy − benchmark| ≈ 0. Wire it as a pytest and
      as a gate the report checks before printing results
- [ ] Feature-lag test: lag all features one extra day → performance must not
      improve (improvement implies the original alignment was leaking)
- [ ] Replace the hardcoded "STATISTICAL INTEGRITY" text block: the report now
      prints each integrity claim with its measured pass/fail and the number
      behind it

## Phase 5 — Re-evaluate and decide
- [ ] Full run on the capped S&P universe; write the report + metrics to
      `results/` with a date stamp; commit
- [ ] Conviction-tier audit: out of sample, do HIGH picks actually beat MEDIUM
      beat LOW? If the ordering doesn't hold, the tiers are decoration
- [ ] Decision point: if net-of-cost edge ≈ 0 vs equal-weight (the likely
      outcome), keep this as the methodology lab it is. Real-money work then
      shifts to the portfolio layer below — not to squeezing this signal

## Later / optional (separate branch each)
- [ ] Cross-sectional long–short quantile evaluation (partially nets out
      survivorship and market beta)
- [ ] Portfolio-layer risk engineering: volatility targeting overlay, max-drawdown
      kill-switch, position/sector caps as a standalone module reusable on ANY
      signal — highest expected value per hour for a risk-management track
- [ ] Point-in-time fundamentals source if budget ever allows (the only honest
      way fundamentals re-enter the feature set)
- [ ] Regime conditioning (e.g., train/evaluate separately by vol regime) — only
      after the falsification suite is green
