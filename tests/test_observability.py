from __future__ import annotations

from pathlib import Path

from parity.engines.observability import engine_status, render_observability_markdown
from parity.reproduce import all_reproduced, reproduce_golden
from parity.scope import PRIMARY_ENGINES, EngineId


def test_observability_markdown_covers_primary_engines() -> None:
    status = engine_status()
    assert set(status) >= {EngineId.VECTORBT.value, EngineId.LEAN.value}
    markdown = render_observability_markdown()
    assert "reconstructed from fills" in markdown
    assert "optional `uv` group `vectorbt`" in markdown
    assert "always importable" in markdown
    assert "locally importable" not in markdown
    assert PRIMARY_ENGINES[0].value in markdown


def test_checked_in_observability_matches_renderer() -> None:
    path = Path(__file__).resolve().parents[1] / "docs" / "observability.md"
    assert path.read_text(encoding="utf-8") == render_observability_markdown()


def test_reproduce_golden_helper_matches_catalog() -> None:
    rows = reproduce_golden()
    assert rows
    assert all_reproduced()
