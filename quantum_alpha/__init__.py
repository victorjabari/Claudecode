"""
Quantum Alpha — walk-forward equity research pipeline.

Modules:
    config     — Config dataclass (constructor-injected, never mutated)
    data       — yfinance provider with parquet cache + retry/backoff
    features   — price/volume feature engineering
    model      — stacked ensemble with temporal cross-validation
    portfolio  — optimizer, conviction tiers, signal generation
    backtest   — walk-forward backtester
    reporting  — report generation
"""

__version__ = "5.1.0"
