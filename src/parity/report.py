from __future__ import annotations

from pathlib import Path

from parity.cases import GoldenCase
from parity.model import AttributionCategory, ComparisonResult, Finding
from parity.scope import CLAIM


def render_report(
    case: GoldenCase,
    result: ComparisonResult,
    *,
    extra_notes: str = "",
) -> str:
    finding = result.finding
    lines = [
        f"# Audit: {case.spec.case_id}",
        "",
        CLAIM,
        "",
        f"- title: {case.spec.title}",
        f"- isolated variable: `{case.spec.isolated_variable}`",
        f"- expected: `{_cat(case.spec.expected_first_divergence)}`",
        f"- observed: `{_observed(finding)}`",
        f"- engines: `{result.left_engine.value}` vs `{result.right_engine.value}`",
        "",
        "## Execution specification (left)",
        "",
        "```json",
        case.execution_left.model_dump_json(indent=2),
        "```",
        "",
        "## Execution specification (right)",
        "",
        "```json",
        case.execution_right.model_dump_json(indent=2),
        "```",
        "",
    ]
    if finding and finding.first_divergence:
        div = finding.first_divergence
        lines.extend(
            [
                "## First divergence",
                "",
                f"- timestamp: `{div.ts_utc.isoformat()}`",
                f"- event: `{div.event_kind.value}.{div.field}`",
                f"- left: `{div.left_value}`",
                f"- right: `{div.right_value}`",
                "",
                "## Evidence",
                "",
            ]
        )
        for item in finding.evidence:
            lines.append(f"- {item.summary}")
        lines.append("")
    elif finding and finding.category is AttributionCategory.UNEXPLAINED:
        lines.extend(["## Unexplained", "", finding.notes or "no rule matched", ""])
    else:
        lines.extend(["## Result", "", "Ledgers agree within tolerance.", ""])
    if extra_notes:
        lines.extend(["## Notes", "", extra_notes, ""])
    lines.extend(
        [
            "## Reproduction",
            "",
            f"`uv run parity audit {case.spec.case_id}`",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def _cat(value: AttributionCategory | None) -> str:
    return "agreement" if value is None else value.value


def _observed(finding: Finding | None) -> str:
    if finding is None:
        return "agreement"
    return finding.category.value
