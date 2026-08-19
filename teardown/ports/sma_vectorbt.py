"""Manual vectorbt port of the 20/50 SMA showcase.

Ambiguity: vectorbt `from_signals` would hide fill timing in its own
defaults. We emit target-qty signals in Parity and map them to
`Portfolio.from_orders` sizes in `parity.engines.vectorbt_adapter`.
Next-bar vs same-bar is an explicit shift of that size series, not an
engine default.
"""

from parity.cases import default_execution
from parity.engines.vectorbt_adapter import run_vectorbt
from parity.model import FillTiming
from parity.strategy import sma_crossover_signals, synthetic_daily_bars


def run(fill_timing: FillTiming):
    bars = synthetic_daily_bars()
    signals = sma_crossover_signals(bars)
    spec = default_execution(fill_timing=fill_timing)
    return run_vectorbt(bars, signals, spec)
