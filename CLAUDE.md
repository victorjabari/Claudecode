# CLAUDE.md — Quantum Alpha (quantitative research framework)

## What this project is
Walk-forward equity research pipeline: yfinance data → features → stacked ensemble
(RF + GB → Ridge meta) → portfolio optimizer → backtest. Runs locally on an M2 Pro,
16 GB RAM, Python. This is a RESEARCH tool, not a trading bot. The owner is building
it partly to learn rigorous backtest methodology (risk-management student).

## Prime directive
Statistical correctness outranks everything: performance numbers, speed, feature
count. If a correctness fix makes the backtest look worse, that is EXPECTED and
ACCEPTABLE — report the degradation plainly. Never reintroduce leakage, weaken a
test, or tune parameters to make results look better. The success condition of this
project is a pipeline whose numbers can be trusted, even if they show zero edge.

## Hard invariants — never violate, never "temporarily disable"
1. **No look-ahead.** No feature at time t may use information from after t.
   yfinance `.info` snapshot fields (trailingPE, revenueGrowth, profitMargins,
   returnOnEquity, beta, dividendYield, pegRatio, etc.) are point-in-time TODAY and
   are FORBIDDEN as historical features. Until a point-in-time fundamentals source
   exists, the feature matrix is price/volume-derived only.
2. **No ticker fingerprints.** No static per-ticker constants in X — they let tree
   models identify the ticker and memorize its realized return. Enforced by test:
   a model trained on static features alone must score OOF R² ≤ 0 (within noise).
3. **Temporal CV only.** Pool training data as one date-indexed panel
   (MultiIndex: date, ticker), sorted by date. Cross-validate with purged k-fold
   plus an embargo ≥ the prediction horizon (21 trading days), because overlapping
   forward-return labels leak across nearby dates. Never apply TimeSeriesSplit to
   arrays stacked ticker-by-ticker — that splits across tickers, not time.
4. **Costs mandatory.** Every backtest applies ≥ 10 bps per side on traded notional
   and reports annualized turnover. Results without costs must never be printed.
5. **Benchmark mandatory.** Every backtest reports SPY total return AND the
   equal-weight portfolio of the same universe over identical dates, beside the
   strategy. A strategy number without a benchmark is meaningless.
6. **Falsification gates results.** The permutation test (shuffle forward-return
   labels within each date, rerun the pipeline → edge over benchmark must be ≈ 0)
   must pass before any backtest output is treated as meaningful. If a change makes
   the permutation test "win," the change introduced leakage — revert it.
7. **Honest reporting.** The report's integrity section must be GENERATED from
   actual measured test outcomes, never hardcoded prose. No comment or docstring
   may claim a property the code does not enforce.
8. **Survivorship caveat.** Universe = current S&P constituents → survivorship-
   biased (yfinance has no delisted tickers). State this in every report. Prefer
   cross-sectional top-vs-bottom-quantile evaluation, where the bias partially
   nets out.

## Environment
- Python 3.11+ in `.venv`. Pin dependencies in `requirements.txt`: yfinance
  (recent), pandas, numpy, scikit-learn, scipy, lxml (required by pd.read_html),
  pyarrow, pytest.
- Cache all downloads to `data/cache/*.parquet`; re-fetch at most once per day.
  Wrap yfinance calls in retry with exponential backoff; skip failed tickers
  gracefully. `.info` is slow and rate-limited — fetch only the fields actually
  used for universe filtering, and cache them.
- Memory: float32 price frames are fine, but do not add complexity purely for RAM.
  ≤ 150 tickers × 3y daily bars is a few MB — RAM is not the constraint here.

## Code conventions
- Keep module separation: data / features / model / portfolio / backtest /
  reporting / tests.
- Config is passed via constructor arguments. Never mutate dataclass class
  attributes after definition — defaults are baked into __init__ at class-creation
  time, so mutation silently does nothing (this was the old `--horizon` CLI bug).
  CLI flags → `Config(prediction_horizon_days=...)` instance.
- Names must be truthful: the rebalance-period return series is monthly, not
  daily — name and annualize it accordingly.
- Seed all randomness; runs must be reproducible.

## Testing
- Run `pytest tests/` after every change; never commit red.
- Required tests:
  (a) no-look-ahead: perturb rows after date t → feature values at t unchanged;
  (b) permutation test (invariant 6);
  (c) static-feature fingerprint test (invariant 2);
  (d) CV split ordering: in every fold, max(train dates) + embargo < min(val dates);
  (e) cost accounting sanity: round-trip on a known trade equals expected bps.

## Workflow for you (Claude Code)
- Work through REFACTOR_PLAN.md phase by phase. One phase = one git commit with a
  message naming the phase.
- After each phase: run pytest, then a 20-ticker smoke run
  (`--tickers AAPL,MSFT,...  --no-backtest`) before any full-universe run.
- Full S&P runs are slow and rate-limited — only run them when a phase explicitly
  calls for it.
- If results degrade after a correctness fix, say so directly. Do not search for
  parameters that restore the old numbers.
