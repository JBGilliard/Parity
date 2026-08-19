"""Write public case contracts and the observability page from source."""

from __future__ import annotations

from pathlib import Path

from parity.audit import audit_case
from parity.cases import GoldenCase, catalog, default_execution, empty_actions
from parity.diff import compare
from parity.engines.observability import render_observability_markdown
from parity.model import AttributionCategory, CaseSpec, DEFAULT_TOLERANCE, FillTiming
from parity.report import render_report, write_report
from parity.reproduce import write_reproduction_report
from parity.scope import SCHEMA_VERSION, EngineId
from parity.strategy import sma_crossover_signals, synthetic_daily_bars

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "observability.md").write_text(
        render_observability_markdown(), encoding="utf-8"
    )
    write_reproduction_report(ROOT / "teardown" / "reproduction.md")
    for case in catalog():
        dest = ROOT / "cases" / case.spec.case_id
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "case.json").write_text(
            case.spec.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        case.bars_left.write_parquet(dest / "bars_left.parquet")
        case.bars_right.write_parquet(dest / "bars_right.parquet")
        case.signals.write_parquet(dest / "signals.parquet")
    showcase()


def showcase() -> None:
    bars = synthetic_daily_bars()
    signals = sma_crossover_signals(bars)
    left_spec = default_execution(fill_timing=FillTiming.NEXT_BAR)
    right_spec = default_execution(fill_timing=FillTiming.SAME_BAR)
    spec = CaseSpec(
        schema_version=SCHEMA_VERSION,
        case_id="sma-20-50-synthetic",
        title="20/50 SMA on synthetic daily bars",
        isolated_variable="fill_timing",
        expected_first_divergence=AttributionCategory.FILL_TIMING,
        execution=left_spec,
        mutated_execution=right_spec,
        instruments=("SYN",),
        notes="Databento is not in this repository. Synthetic daily bars, seed=7, n=80.",
    )
    case = GoldenCase(
        spec=spec,
        bars_left=bars,
        bars_right=bars,
        signals=signals,
        actions_left=empty_actions(),
        actions_right=empty_actions(),
        execution_left=left_spec,
        execution_right=right_spec,
    )
    result = compare(
        case.left_ledger(),
        case.right_ledger(),
        left_engine=EngineId.ORACLE,
        right_engine=EngineId.ORACLE_MUTATED,
        left_spec=left_spec,
        right_spec=right_spec,
        tolerance=DEFAULT_TOLERANCE,
        case=spec,
    )
    write_report(
        ROOT / "teardown" / "sma-20-50-synthetic.md",
        render_report(
            case,
            result,
            extra_notes="Synthetic daily bars. Databento sample is not in this repository.",
        ),
    )
    audit_case(case, ROOT / "teardown" / "bundles" / "sma-20-50-synthetic")


if __name__ == "__main__":
    main()
