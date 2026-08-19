from __future__ import annotations

import pytest

from parity.cases import case_by_id
from parity.diff import compare
from parity.model import AttributionCategory, VECTORBT_TOLERANCE
from parity.scope import EngineId


vectorbt = pytest.importorskip("vectorbt")


def test_vectorbt_same_vs_next_bar_is_fill_timing() -> None:
    from parity.engines.vectorbt_adapter import run_vectorbt

    case = case_by_id("fill-timing-next-vs-same")
    left = run_vectorbt(case.bars_left, case.signals, case.execution_left)
    right = run_vectorbt(case.bars_right, case.signals, case.execution_right)
    result = compare(
        left.ledger,
        right.ledger,
        left_engine=EngineId.VECTORBT,
        right_engine=EngineId.ORACLE_MUTATED,
        left_spec=case.execution_left,
        right_spec=case.execution_right,
        tolerance=VECTORBT_TOLERANCE,
        case=case.spec,
    )
    assert result.finding is not None
    assert result.finding.category is AttributionCategory.FILL_TIMING
    assert left.raw_files["orders.csv"]
    assert b"New Cash" in left.raw_files["logs.csv"] or b"Cash" in left.raw_files["logs.csv"]
