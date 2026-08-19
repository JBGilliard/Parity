from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from parity.audit import audit_case, category_of
from parity.cases import case_by_id, catalog
from parity.engines.observability import render_observability_markdown
from parity.report import render_report, write_report
from parity.reproduce import all_reproduced, reproduce_golden, write_reproduction_report
from parity.scope import CLAIM, PRIMARY_ENGINES

app = typer.Typer(no_args_is_help=True, add_completion=False)
ROOT = Path(__file__).resolve().parents[2]


@app.callback()
def _root() -> None:
    """Parity: first causal divergence, classified only with evidence."""


@app.command()
def claim() -> None:
    """Print what this package does and the two primary engines."""
    typer.echo(CLAIM)
    typer.echo("primary: " + ", ".join(engine.value for engine in PRIMARY_ENGINES))


@app.command("engines")
def engines_cmd() -> None:
    """Print engine event coverage."""
    typer.echo(render_observability_markdown(), nl=False)


@app.command("cases")
def cases_cmd() -> None:
    """List golden micro-cases."""
    for item in catalog():
        expected = item.spec.expected_first_divergence
        label = "agreement" if expected is None else expected.value
        typer.echo(f"{item.spec.case_id:40} {label}")


@app.command()
def audit(
    case_id: str,
    out: Optional[Path] = typer.Option(None, help="Bundle directory"),
) -> None:
    """Run a golden case through the spec interpreter and write a bundle."""
    case = case_by_id(case_id)
    dest = out or ROOT / "bundles" / case_id
    result, path = audit_case(case, dest)
    report = render_report(case, result)
    write_report(path / "report.md", report)
    typer.echo(f"{case_id}: {category_of(result) or 'agreement'}")
    typer.echo(str(path))


@app.command()
def report(case_id: str) -> None:
    """Print a markdown audit for a golden case without writing a bundle."""
    case = case_by_id(case_id)
    from parity.diff import compare
    from parity.model import DEFAULT_TOLERANCE
    from parity.scope import EngineId

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
    typer.echo(render_report(case, result))


@app.command()
def reproduce() -> None:
    """Recompute every golden case. Clean-machine command."""
    rows = reproduce_golden()
    failed = [row for row in rows if row["ok"] != "True"]
    write_reproduction_report(ROOT / "teardown" / "reproduction.md")
    for row in rows:
        mark = "ok" if row["ok"] == "True" else "FAIL"
        typer.echo(f"{mark:4} {row['case_id']:40} expected={row['expected']} actual={row['actual']}")
    if failed:
        raise typer.Exit(code=1)
    if not all_reproduced():
        raise typer.Exit(code=1)
