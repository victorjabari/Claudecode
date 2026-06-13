# REFACTOR_PLAN.md — quantum_alpha_v5.py → a trustworthy pipeline

Work the phases in order. One phase = one commit. After each phase: `pytest`,
then a 20-ticker smoke run. Expected global outcome: the backtest edge shrinks
toward zero as leaks close. **That is success, not failure** — see CLAUDE.md.

## Phase 0 — Make it run at all  ✅ (commit: Phase 0)
- [x] `python3 -m venv .venv && source .venv/bin/activate`
- [x] `requirements.txt` with pinned versions (yfinance, pandas, numpy,
      scikit-learn, scipy, lxml, pyarrow, pytest); `pip install -r requirements.txt`
- [x] Parquet cache layer: prices + the few `.info` fields used for filtering →
      `data/cache/`, keyed by fetch date; skip the network when fresh (< 24 h)
- [x] Retry/backoff wrapper around all yfinance calls; per-ticker failures are
      logged and skipped, never fatal
- [x] Fix the Config mutation bug: CLI args construct
      `Config(prediction_horizon_days=args.horizon)` — no class-attribute writes
      (Config is now a frozen dataclass; CLI builds instances)
- [x] Smoke test passes: 20 tickers fetch → features compute → no crash

## Phase 1 — Remove look-ahead and ticker fingerprints  ✅ (commit: Phase 1)
- [x] Delete every `.info`-derived feature column from `_compute_features`:
      pe_ratio, forward_pe, pb_ratio, revenue_growth, earnings_growth,
      profit_margin, roe, debt_to_equity, beta, dividend_yield, peg_ratio
- [x] `.info` survives only in universe filters (marketCap, averageVolume) and
      report metadata — never in X
- [x] Audit every remaining feature for shift correctness. Convention decided
      and documented: a feature at t may use info up to and including the close
      of day t (labels run close[t]→close[t+h]); `.shift(1)` kept only where a
      PRIOR-window baseline is semantically required. No-look-ahead test passes
      bit-for-bit, confirming no remaining feature touches future rows.
- [x] Add the fingerprint test: model trained on static-only features →
      OOF R² ≤ 0 (memorizes in-sample, OOF R² ≤ 0 on embargoed split)

## Phase 2 — Fix cross-validation and uncertainty calibration  ✅ (commit: Phase 2)
- [x] Build one pooled panel: MultiIndex (date, ticker), sorted by date — replace
      the per-ticker `np.vstack` ordering
- [x] Implement purged k-fold with embargo = horizon (21 trading days); remove
      TimeSeriesSplit-on-stacked-arrays entirely
- [x] Recompute OOF predictions, the Ridge meta-learner, and residual calibration
      on the corrected splits (the global RobustScaler — fit on all data before
      OOF — was a leak and is removed; trees are scale-invariant)
- [x] Add the CV ordering test: every fold satisfies
      max(train dates) + embargo < min(val dates)
- [x] Inspect corrected OOF R²: 20-ticker run gives ≈ 0.002 (within the
      expected 0.00–0.03 band). No leakage flag.

## Phase 3 — Honest backtester  ✅ (commit: Phase 3)
- [x] Apply 10 bps per side on every traded notional; accumulate and report
      annualized turnover
- [x] Add benchmarks on identical dates: SPY total return and equal-weight of the
      same universe (same survivor set, so the comparison is apples-to-apples) —
      strategy and benchmarks share one simulation engine
- [x] Rename `daily_ret` → `period_ret`; annualize with
      252/rebalance_frequency_days; CAGR measured from first deployment
- [x] Report net-of-cost: total return, CAGR, vol, Sharpe, max drawdown,
      turnover, and active return vs each benchmark
- Result (20-ticker, net of cost): strategy CAGR −13.2% vs SPY +25.8% vs
  equal-weight +46.1%, turnover 379%/yr. No edge — reported as-is.

## Phase 4 — Falsification suite  ✅ (commit: Phase 4)
- [x] Permutation test: shuffle forward returns within each date → OOF R²
      collapses to ≈ 0. Wired as a pytest (required test b) AND as the report
      gate: a failed gate WITHHOLDS the backtest output.
- [x] Feature-lag test: lag all features one extra day → OOF R² must not
      improve (pytest + measured integrity claim)
- [x] Replace the hardcoded "STATISTICAL INTEGRITY" block: the report now
      generates each claim with its measured pass/fail and the number behind it

## Phase 5 — Re-evaluate and decide  ✅ (commit: Phase 5)
- [x] Full run on the capped S&P universe (--max-universe N --save-results);
      report + metrics.json written to `results/<datestamp>/` and committed.
      (S&P list fetch now sends a browser user-agent; Wikipedia 403s urllib's
      default UA. Graceful fallback to the curated universe still works.)
- [x] Conviction-tier audit wired in: replays classify_conviction over the
      purged OOF predictions and checks HIGH ≥ MEDIUM ≥ LOW in realized return.
      Out of sample the ordering does NOT hold and HIGH/MEDIUM barely populate
      — the audit reports the tiers are decoration rather than hiding it.
- [x] Decision (see DECISIONS.md): net-of-cost edge is negative vs equal-weight,
      OOF R² ≈ 0 with the permutation control in the same band (no edge AND no
      leakage). Keep as a methodology lab; real-money work moves to the
      portfolio/risk layer, not to squeezing this signal.

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
