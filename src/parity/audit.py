from __future__ import annotations

from pathlib import Path

from parity.bundle import write_bundle, write_engine_tree, write_inputs
from parity.cases import GoldenCase
from parity.diff import compare
from parity.hashutil import sha256_json
from parity.ledger import Ledger
from parity.model import DEFAULT_TOLERANCE, ComparisonResult, Finding
from parity.scope import EngineId


def audit_case(case: GoldenCase, bundle_dir: Path) -> tuple[ComparisonResult, Path]:
    left = case.left_ledger()
    right = case.right_ledger()
    result = compare(
        left,
        right,
        left_engine=EngineId.ORACLE,
        right_engine=EngineId.ORACLE_MUTATED,
        left_spec=case.execution_left,
        right_spec=case.execution_right,
        tolerance=DEFAULT_TOLERANCE,
        case=case.spec,
    )
    path = write_comparison_bundle(bundle_dir, case, left, right, result)
    return result, path


def write_comparison_bundle(
    bundle_dir: Path,
    case: GoldenCase,
    left: Ledger,
    right: Ledger,
    result: ComparisonResult,
) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    data_dir = bundle_dir / "inputs" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    left_bars = data_dir / "bars_left.parquet"
    right_bars = data_dir / "bars_right.parquet"
    case.bars_left.write_parquet(left_bars)
    case.bars_right.write_parquet(right_bars)
    inputs = write_inputs(bundle_dir, case.spec, [left_bars, right_bars])
    left_meta = write_engine_tree(
        bundle_dir,
        EngineId.ORACLE,
        left,
        {"spec.json": case.execution_left.model_dump_json(indent=2).encode()},
        parameters={"role": "baseline"},
    )
    right_meta = write_engine_tree(
        bundle_dir,
        EngineId.ORACLE_MUTATED,
        right,
        {"spec.json": case.execution_right.model_dump_json(indent=2).encode()},
        parameters={"role": "mutant"},
    )
    findings: tuple[Finding, ...] = (result.finding,) if result.finding else ()
    bundle_id = sha256_json({"case": case.spec.case_id})[:16]
    write_bundle(
        bundle_dir,
        bundle_id=bundle_id,
        case=case.spec,
        inputs=inputs,
        engines=(left_meta, right_meta),
        tolerance=DEFAULT_TOLERANCE,
        findings=findings,
    )
    return bundle_dir


def category_of(result: ComparisonResult) -> str | None:
    if result.finding is None:
        return None
    return result.finding.category.value
