from __future__ import annotations

from pathlib import Path

from parity.cases import GoldenCase, catalog
from parity.diff import compare
from parity.model import DEFAULT_TOLERANCE
from parity.scope import EngineId


def expected_category(case: GoldenCase) -> str | None:
    expected = case.spec.expected_first_divergence
    return None if expected is None else expected.value


def actual_category(case: GoldenCase) -> str | None:
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
    if result.finding is None:
        return None
    return result.finding.category.value


def reproduce_golden() -> list[dict[str, str | None]]:
    rows = []
    for case in catalog():
        expected = expected_category(case)
        actual = actual_category(case)
        rows.append(
            {
                "case_id": case.spec.case_id,
                "expected": expected,
                "actual": actual,
                "ok": str(expected == actual),
            }
        )
    return rows


def all_reproduced() -> bool:
    return all(row["ok"] == "True" for row in reproduce_golden())


def write_reproduction_report(path: Path) -> None:
    rows = reproduce_golden()
    lines = ["# Golden reproduction", "", "| case | expected | actual | ok |", "|---|---|---|---|"]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['expected']} | {row['actual']} | {row['ok']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
