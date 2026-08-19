from __future__ import annotations

import json
from pathlib import Path

from parity.cases import case_by_id
from parity.engines.lean_adapter import ledger_to_lean_json, lean_json_to_ledger, read_lean_raw
from parity.ledger import as_utc
from parity.model import EventKind


def test_lean_reader_round_trips_fills(tmp_path: Path) -> None:
    case = case_by_id("fill-price-matched")
    ledger = case.left_ledger()
    result, events = ledger_to_lean_json(ledger)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "123.json").write_text(json.dumps(result), encoding="utf-8")
    (raw / "123-order-events.json").write_text(json.dumps(events), encoding="utf-8")
    bars = [dict(row) for row in case.bars_left.iter_rows(named=True)]
    restored = lean_json_to_ledger(result, events, bars)
    src = (
        ledger.frame(EventKind.FILL)
        .select("instrument_id", "qty", "price", "side")
        .sort(["qty", "price"])
    )
    dst = (
        restored.frame(EventKind.FILL)
        .select("instrument_id", "qty", "price", "side")
        .sort(["qty", "price"])
    )
    assert src.to_dicts() == dst.to_dicts()
    assert restored.frame(EventKind.BAR).height == case.bars_left.height
    assert as_utc(restored.frame(EventKind.FILL)["ts_utc"][0])


def test_lean_reader_loads_checked_in_fixture() -> None:
    case = case_by_id("fill-price-matched")
    fixture = (
        Path(__file__).resolve().parents[1]
        / "cases"
        / "fixtures"
        / "lean"
        / "fill-price-matched"
    )
    run = read_lean_raw(
        fixture,
        [dict(row) for row in case.bars_left.iter_rows(named=True)],
    )
    assert run.ledger.frame(EventKind.FILL).height >= 1
    assert run.engine_id.value == "lean"
