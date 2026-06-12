"""
QUANTUM ALPHA — Live Quantitative Research Framework
=====================================================
Thin CLI entry point. The implementation lives in the quantum_alpha package
(data / features / model / portfolio / backtest / reporting).

Usage:
    # Full S&P 500 scan + backtest
    python quantum_alpha_v5.py

    # Quick scan of specific tickers
    python quantum_alpha_v5.py --tickers AAPL,MSFT,GOOGL,NVDA,AMD --no-backtest

    # Custom horizon (builds Config(prediction_horizon_days=...) — no class
    # attribute mutation)
    python quantum_alpha_v5.py --horizon 42

DISCLAIMER: This is a research tool. You bear full responsibility for any
trades. Past patterns do not guarantee future results.
"""

import warnings

warnings.filterwarnings("ignore")

from quantum_alpha.engine import cli

if __name__ == "__main__":
    cli()
