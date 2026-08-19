from __future__ import annotations

from parity.engines.lean_adapter import LEAN_CAPABILITIES, lean_available
from parity.engines.vectorbt_adapter import VECTORBT_CAPABILITIES, vectorbt_available
from parity.scope import ENGINE_PINS, PRIMARY_ENGINES, EngineId

COVERAGE_NOTES = (
    "vectorbt 1.1.0 exposes filled orders, per-bar cash/position logs, and "
    "Filled/Ignored/rejected-style status when log=True. LEAN local results "
    "expose Orders, order-events (fill price/qty/fee), and equity charts. "
    "Position series in LEAN JSON is reconstructed from fills when holdings "
    "are absent. Corporate-action and lookahead evidence are native in the "
    "spec interpreter and reconstructed or gap-flagged in the engine adapters."
)


def engine_status() -> dict[str, dict[str, object]]:
    return {
        EngineId.VECTORBT.value: {
            "available": vectorbt_available(),
            "pin": ENGINE_PINS[EngineId.VECTORBT].version,
            "capabilities": [item.__dict__ for item in VECTORBT_CAPABILITIES],
        },
        EngineId.LEAN.value: {
            "available": lean_available(),
            "pin": ENGINE_PINS[EngineId.LEAN].version,
            "capabilities": [item.__dict__ for item in LEAN_CAPABILITIES],
        },
    }


def render_observability_markdown() -> str:
    lines = [
        "# Engine event coverage",
        "",
        COVERAGE_NOTES,
        "",
        "## Primary engines",
        "",
    ]
    status = engine_status()
    for engine_id in PRIMARY_ENGINES:
        block = status[engine_id.value]
        lines.append(f"### {engine_id.value}")
        lines.append("")
        lines.append(f"- pin: `{block['pin']}`")
        if engine_id is EngineId.VECTORBT:
            lines.append("- extra: optional `uv` group `vectorbt` (Commons Clause). core never imports it.")
        else:
            lines.append("- reader: always importable. live docker is opt-in.")
        lines.append("")
        lines.append("| event | status | notes |")
        lines.append("|---|---|---|")
        for cap in block["capabilities"]:
            lines.append(f"| {cap['event']} | {cap['status']} | {cap['notes']} |")
        lines.append("")
    lines.extend(
        [
            "## Gaps",
            "",
            "- vectorbt `orders` are fills. Unfilled/rejected intent lives in `logs` when `log=True`.",
            "- vectorbt has no native corporate-action stream; adapters record the input CA table beside the run.",
            "- LEAN local JSON often omits a holdings time series; positions are reconstructed from fills and marked as such.",
            "- Per-share fee rounding to banker's decimals is an interpreter property. vectorbt uses binary floats.",
            "- Live `docker run quantconnect/lean:18008` is optional. The reader is first-class; a missing daemon is not a missing schema.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"
