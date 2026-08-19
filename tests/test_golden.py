from __future__ import annotations

from parity.cases import catalog
from parity.diff import compare
from parity.model import AttributionCategory, DEFAULT_TOLERANCE
from parity.scope import EngineId


def _run(case):
    return compare(
        case.left_ledger(),
        case.right_ledger(),
        left_engine=EngineId.ORACLE,
        right_engine=EngineId.ORACLE_MUTATED,
        left_spec=case.execution_left,
        right_spec=case.execution_right,
        tolerance=DEFAULT_TOLERANCE,
        case=case.spec,
    )


def test_golden_corpus_classifications() -> None:
    failures = []
    for case in catalog():
        result = _run(case)
        actual = None if result.finding is None else result.finding.category
        if actual is not case.spec.expected_first_divergence:
            failures.append(
                (
                    case.spec.case_id,
                    case.spec.expected_first_divergence,
                    actual,
                    None if result.finding is None else result.finding.notes,
                )
            )
    assert failures == []


def test_matched_cases_have_no_false_certainty() -> None:
    for case in catalog():
        if case.spec.expected_first_divergence is not None:
            continue
        result = _run(case)
        assert result.finding is None


def test_unexplained_is_low_or_none_confidence() -> None:
    case = next(item for item in catalog() if item.spec.case_id == "rebalance-ordering")
    result = _run(case)
    assert result.finding is not None
    assert result.finding.category is AttributionCategory.UNEXPLAINED
    assert result.finding.confidence.value in {"none", "low"}
