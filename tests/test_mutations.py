from __future__ import annotations

from parity.cases import case_by_id
from parity.diff import compare
from parity.model import AttributionCategory, DEFAULT_TOLERANCE, FillTiming
from parity.scope import EngineId


def test_mutating_fill_timing_moves_the_first_break_category() -> None:
    mutant = case_by_id("fill-timing-next-vs-same")
    matched = case_by_id("fill-timing-matched")
    assert mutant.execution_left.fill_timing is not mutant.execution_right.fill_timing
    assert matched.execution_left.fill_timing is FillTiming.NEXT_BAR
    mutant_result = compare(
        mutant.left_ledger(),
        mutant.right_ledger(),
        left_engine=EngineId.ORACLE,
        right_engine=EngineId.ORACLE_MUTATED,
        left_spec=mutant.execution_left,
        right_spec=mutant.execution_right,
        tolerance=DEFAULT_TOLERANCE,
        case=mutant.spec,
    )
    matched_result = compare(
        matched.left_ledger(),
        matched.right_ledger(),
        left_engine=EngineId.ORACLE,
        right_engine=EngineId.ORACLE_MUTATED,
        left_spec=matched.execution_left,
        right_spec=matched.execution_right,
        tolerance=DEFAULT_TOLERANCE,
        case=matched.spec,
    )
    assert mutant_result.finding is not None
    assert mutant_result.finding.category is AttributionCategory.FILL_TIMING
    assert matched_result.finding is None


def test_mutating_fee_rounding_does_not_look_like_fill_timing() -> None:
    case = case_by_id("fee-rounding-half-even-vs-truncate")
    result = compare(
        case.left_ledger(),
        case.right_ledger(),
        left_engine=EngineId.ORACLE,
        right_engine=EngineId.ORACLE_MUTATED,
        left_spec=case.execution_left,
        right_spec=case.execution_right,
        tolerance=DEFAULT_TOLERANCE,
        case=case.spec,
    )
    assert result.finding is not None
    assert result.finding.category is AttributionCategory.FEE
    assert result.finding.first_divergence is not None
    assert result.finding.first_divergence.event_kind.value == "fee"
