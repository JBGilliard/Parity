from __future__ import annotations

from parity.cases import default_execution
from parity.diff import compare
from parity.model import AttributionCategory, DEFAULT_TOLERANCE, FillTiming
from parity.scope import EngineId
from parity.strategy import sma_crossover_signals, synthetic_daily_bars
from parity.oracle import interpret
from parity.cases import empty_actions


def test_sma_crossover_next_vs_same_bar_on_synthetic_daily() -> None:
    bars = synthetic_daily_bars()
    signals = sma_crossover_signals(bars)
    assert signals.height >= 1
    left_spec = default_execution(fill_timing=FillTiming.NEXT_BAR)
    right_spec = default_execution(fill_timing=FillTiming.SAME_BAR)
    left = interpret(bars, signals, empty_actions(), left_spec)
    right = interpret(bars, signals, empty_actions(), right_spec)
    from parity.model import CaseSpec
    from parity.scope import SCHEMA_VERSION

    case = CaseSpec(
        schema_version=SCHEMA_VERSION,
        case_id="sma-20-50-synthetic",
        title="20/50 SMA on synthetic daily bars",
        isolated_variable="fill_timing",
        expected_first_divergence=AttributionCategory.FILL_TIMING,
        execution=left_spec,
        mutated_execution=right_spec,
        instruments=("SYN",),
        notes="Databento is not in this repository. This is the bounded synthetic stand-in.",
    )
    result = compare(
        left,
        right,
        left_engine=EngineId.ORACLE,
        right_engine=EngineId.ORACLE_MUTATED,
        left_spec=left_spec,
        right_spec=right_spec,
        tolerance=DEFAULT_TOLERANCE,
        case=case,
    )
    assert result.finding is not None
    assert result.finding.category is AttributionCategory.FILL_TIMING
