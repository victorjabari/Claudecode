# Quantum Alpha — quantitative research framework

A walk-forward equity research pipeline:
**yfinance → features → stacked ensemble (RF + GB → Ridge meta) → portfolio
optimizer → backtest → falsification + measured integrity report.**

This is a **research tool**, not a trading bot. Its success condition is a
pipeline whose numbers can be trusted — even when they show no edge. See
`CLAUDE.md` for the hard invariants and `DECISIONS.md` for the conclusion.

## Layout

```
quantum_alpha/
  config.py        Frozen Config dataclass (constructor-injected, never mutated)
  data.py          yfinance provider: parquet cache + retry/backoff, .info subset
  features.py      Price/volume features only (no .info, no look-ahead)
  model.py         Pooled (date,ticker) panel + purged walk-forward CV + ensemble
  portfolio.py     Conviction tiers, risk scoring, optimizer, signal generation
  backtest.py      Walk-forward backtest: mandatory costs + SPY/equal-weight
  falsification.py Label permutation + feature-lag tools
  integrity.py     Measured integrity checks; the permutation gate
  audit.py         Out-of-sample conviction-tier audit
  results.py       Dated results/ artifacts (report.txt + metrics.json)
  reporting.py     Report generation (integrity section is measured, not prose)
  engine.py        TradingEngine + CLI
quantum_alpha_v5.py  Thin CLI shim → quantum_alpha.engine.cli
tests/               pytest suite (see Testing)
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
# Quick scan of specific tickers (no backtest)
python quantum_alpha_v5.py --tickers AAPL,MSFT,GOOGL,NVDA,AMD --no-backtest

# Capped S&P universe, full backtest + falsification, save a dated artifact
python quantum_alpha_v5.py --max-universe 50 --save-results

# Custom horizon (builds Config(prediction_horizon_days=...), no class mutation)
python quantum_alpha_v5.py --horizon 42
```

Key flags: `--tickers`, `--no-backtest`, `--horizon`, `--max-universe`,
`--cache-dir`, `--no-falsification` (skips the permutation/lag refits — the
gate then reports NOT RUN and the backtest is withheld), `--save-results`.

Downloads are cached to `data/cache/<YYYY-MM-DD>/` and reused for 24 h, so
repeated runs in a day never touch the network.

## What "trustworthy" means here

Every run prints a **STATISTICAL INTEGRITY** section generated from actual
measurements: no-look-ahead (`max|Δ|≤t`), no fingerprints, CV embargo ordering,
costs applied, benchmarks present, the **falsification gate** (permuted-label
OOF R² must stay ≈ 0), and the feature-lag test. If the gate fails, backtest
results are withheld rather than presented as meaningful.

## Testing

```bash
pytest                  # full suite (includes slow model-refit tests)
pytest -m "not slow"    # fast subset
```

Required tests (CLAUDE.md): no-look-ahead, permutation/falsification,
static-feature fingerprint, CV split ordering, and cost-accounting sanity.
