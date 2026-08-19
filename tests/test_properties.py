from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from parity.audit import write_comparison_bundle
from parity.bundle import read_bundle
from parity.cases import (
    _case,
    bars_for,
    buy_hold_signals,
    default_execution,
    empty_actions,
    session_days,
)
from parity.diff import compare
from parity.ledger import as_utc, frame_from_rows
from parity.model import DEFAULT_TOLERANCE, EventKind, FillTiming
from parity.oracle import interpret
from parity.scope import EngineId

NY_STAMPS = session_days()


def test_split_then_reverse_restores_qty() -> None:
    stamps = NY_STAMPS
    bars = bars_for(stamps)
    signals = buy_hold_signals(stamps)
    spec = default_execution(fill_timing=FillTiming.SAME_BAR)
    actions = frame_from_rows(
        EventKind.CORPORATE_ACTION,
        [
            _ca("split", stamps[2], 2.0, 0.0),
            _ca("split", stamps[3], 0.5, 0.0),
        ],
    )
    with_ca = interpret(bars, signals, actions, spec)
    without = interpret(bars, signals, empty_actions(), spec)
    assert _last_qty(with_ca) == _last_qty(without)


def test_cash_matches_fills_and_fees() -> None:
    spec = default_execution(fill_timing=FillTiming.SAME_BAR)
    ledger = interpret(
        bars_for(NY_STAMPS), buy_hold_signals(NY_STAMPS), empty_actions(), spec
    )
    cash = Decimal("10000")
    fills = list(ledger.frame(EventKind.FILL).iter_rows(named=True))
    fees = {
        row["fill_id"]: Decimal(str(row["amount"]))
        for row in ledger.frame(EventKind.FEE).iter_rows(named=True)
    }
    for fill in fills:
        signed = Decimal(str(fill["qty"])) * Decimal(str(fill["price"]))
        fee = fees[fill["fill_id"]]
        if fill["side"] == "buy":
            cash -= signed + fee
        else:
            cash += signed - fee
    final = Decimal(str(ledger.frame(EventKind.CASH)["balance"].to_list()[-1]))
    assert abs(final - cash) < Decimal("0.0000001")


@given(st.integers(min_value=6, max_value=10))
@settings(max_examples=15, deadline=None)
def test_bundle_round_trip_preserves_ledger_height(n: int) -> None:
    stamps = session_days(n)
    spec = default_execution()
    bars = bars_for(stamps)
    case = _case(
        "prop-roundtrip",
        "property roundtrip",
        "fill_timing",
        None,
        spec,
        spec,
        bars_left=bars,
        bars_right=bars,
        signals=buy_hold_signals(stamps),
    )
    left = case.left_ledger()
    result = compare(
        left,
        case.right_ledger(),
        left_engine=EngineId.ORACLE,
        right_engine=EngineId.ORACLE_MUTATED,
        left_spec=case.execution_left,
        right_spec=case.execution_right,
        tolerance=DEFAULT_TOLERANCE,
        case=case.spec,
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bundle"
        write_comparison_bundle(path, case, left, case.right_ledger(), result)
        manifest, ledgers = read_bundle(path)
        assert manifest.case.case_id == case.spec.case_id
        assert ledgers[EngineId.ORACLE].frame(EventKind.FILL).height == left.frame(
            EventKind.FILL
        ).height


def _last_qty(ledger) -> float:
    frame = ledger.frame(EventKind.POSITION)
    return float(frame["qty"].to_list()[-1])


def _ca(action_type: str, ts: datetime, ratio: float, cash_amount: float) -> dict:
    return {
        "event_id": f"ca-{action_type}-{ts.isoformat()}",
        "ts_utc": as_utc(ts),
        "ts_source": ts.isoformat(),
        "instrument_id": "TEST",
        "source_payload": "{}",
        "action_type": action_type,
        "ratio": ratio,
        "cash_amount": cash_amount,
    }
