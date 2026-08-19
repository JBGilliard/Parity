"""Golden micro-cases. One isolated variable each."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import polars as pl

from parity.ledger import as_utc, frame_from_rows
from parity.model import (
    AdjustmentPolicy,
    AttributionCategory,
    CaseSpec,
    CashPolicy,
    DividendPolicy,
    EventKind,
    ExecutionSpec,
    FeeMode,
    FeeSpec,
    FillPrice,
    FillTiming,
    LookaheadPolicy,
    MissingBarPolicy,
    RoundingMode,
    SessionSpec,
    SimultaneousOrderPolicy,
)
from parity.oracle import interpret
from parity.scope import SCHEMA_VERSION

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
TEST = "TEST"


@dataclass(frozen=True)
class GoldenCase:
    spec: CaseSpec
    bars_left: pl.DataFrame
    bars_right: pl.DataFrame
    signals: pl.DataFrame
    actions_left: pl.DataFrame
    actions_right: pl.DataFrame
    execution_left: ExecutionSpec
    execution_right: ExecutionSpec

    def left_ledger(self):
        return interpret(
            self.bars_left, self.signals, self.actions_left, self.execution_left
        )

    def right_ledger(self):
        return interpret(
            self.bars_right, self.signals, self.actions_right, self.execution_right
        )


def default_execution(**updates: object) -> ExecutionSpec:
    spec = ExecutionSpec(
        fill_timing=FillTiming.NEXT_BAR,
        fill_price=FillPrice.OPEN,
        fee=FeeSpec(mode=FeeMode.PER_SHARE, value=Decimal("0.01")),
        cash=CashPolicy.REJECT,
        simultaneous_orders=SimultaneousOrderPolicy.SYMBOL_LEXICOGRAPHIC,
        missing_bar=MissingBarPolicy.SKIP,
        session=SessionSpec(),
        adjustment=AdjustmentPolicy.RAW,
        dividend=DividendPolicy.CASH,
        lookahead=LookaheadPolicy.FORBIDDEN,
        fractional_shares=False,
    )
    if not updates:
        return spec
    return spec.model_copy(update=updates)


def session_days(count: int = 8, start: datetime | None = None) -> list[datetime]:
    day = (start or datetime(2024, 1, 2, tzinfo=NY)).date()
    out: list[datetime] = []
    while len(out) < count:
        if day.weekday() < 5:
            out.append(datetime.combine(day, time(9, 30), tzinfo=NY))
        day += timedelta(days=1)
    return out


def bars_for(
    timestamps: list[datetime],
    instrument_id: str = TEST,
    base: float = 100.0,
) -> pl.DataFrame:
    rows = []
    for i, ts in enumerate(timestamps):
        close = base + i * 0.5
        open_px = close - 0.2
        rows.append(
            {
                "event_id": f"bar-{instrument_id}-{i}",
                "ts_utc": as_utc(ts),
                "ts_source": ts.isoformat(),
                "instrument_id": instrument_id,
                "source_payload": "{}",
                "open": open_px,
                "high": close + 0.3,
                "low": open_px - 0.1,
                "close": close,
                "volume": 1000.0 + i,
                "session_id": "XNYS",
            }
        )
    return frame_from_rows(EventKind.BAR, rows)


def empty_actions() -> pl.DataFrame:
    return frame_from_rows(EventKind.CORPORATE_ACTION, [])


def buy_hold_signals(timestamps: list[datetime], instrument_id: str = TEST) -> pl.DataFrame:
    rows = [
        {
            "event_id": "sig-entry",
            "ts_utc": as_utc(timestamps[0]),
            "ts_source": timestamps[0].isoformat(),
            "instrument_id": instrument_id,
            "source_payload": "{}",
            "signal_id": "entry",
            "side": "buy",
            "target_qty": 1.0,
        },
        {
            "event_id": "sig-exit",
            "ts_utc": as_utc(timestamps[4]),
            "ts_source": timestamps[4].isoformat(),
            "instrument_id": instrument_id,
            "source_payload": "{}",
            "signal_id": "exit",
            "side": "sell",
            "target_qty": 0.0,
        },
    ]
    return frame_from_rows(EventKind.SIGNAL, rows)


def _case(
    case_id: str,
    title: str,
    isolated: str,
    expected: AttributionCategory | None,
    left: ExecutionSpec,
    right: ExecutionSpec,
    notes: str = "",
    bars_left: pl.DataFrame | None = None,
    bars_right: pl.DataFrame | None = None,
    signals: pl.DataFrame | None = None,
    actions_left: pl.DataFrame | None = None,
    actions_right: pl.DataFrame | None = None,
    instruments: tuple[str, ...] = (TEST,),
) -> GoldenCase:
    stamps = session_days()
    bars = bars_for(stamps)
    spec = CaseSpec(
        schema_version=SCHEMA_VERSION,
        case_id=case_id,
        title=title,
        isolated_variable=isolated,
        expected_first_divergence=expected,
        execution=left,
        mutated_execution=None if right == left else right,
        instruments=instruments,
        notes=notes,
    )
    return GoldenCase(
        spec=spec,
        bars_left=bars_left if bars_left is not None else bars,
        bars_right=bars_right if bars_right is not None else bars,
        signals=signals if signals is not None else buy_hold_signals(stamps),
        actions_left=actions_left if actions_left is not None else empty_actions(),
        actions_right=actions_right if actions_right is not None else empty_actions(),
        execution_left=left,
        execution_right=right,
    )


def _action_rows(
    timestamps: list[datetime], action_type: str, ratio: float, cash_amount: float
) -> pl.DataFrame:
    ts = timestamps[3]
    return frame_from_rows(
        EventKind.CORPORATE_ACTION,
        [
            {
                "event_id": f"ca-{action_type}",
                "ts_utc": as_utc(ts),
                "ts_source": ts.isoformat(),
                "instrument_id": TEST,
                "source_payload": "{}",
                "action_type": action_type,
                "ratio": ratio,
                "cash_amount": cash_amount,
            }
        ],
    )


def catalog() -> tuple[GoldenCase, ...]:
    stamps = session_days()
    next_bar = default_execution(fill_timing=FillTiming.NEXT_BAR)
    same_bar = default_execution(fill_timing=FillTiming.SAME_BAR)
    open_px = default_execution(fill_timing=FillTiming.SAME_BAR, fill_price=FillPrice.OPEN)
    close_px = default_execution(fill_timing=FillTiming.SAME_BAR, fill_price=FillPrice.CLOSE)
    even = default_execution(
        fill_timing=FillTiming.SAME_BAR,
        fee=FeeSpec(
            mode=FeeMode.PER_SHARE,
            value=Decimal("0.015"),
            rounding=RoundingMode.HALF_EVEN,
            decimals=2,
        ),
    )
    trunc = even.model_copy(
        update={
            "fee": FeeSpec(
                mode=FeeMode.PER_SHARE,
                value=Decimal("0.015"),
                rounding=RoundingMode.TRUNCATE,
                decimals=2,
            )
        }
    )
    reject = default_execution(fill_timing=FillTiming.SAME_BAR, cash=CashPolicy.REJECT)
    partial = default_execution(fill_timing=FillTiming.SAME_BAR, cash=CashPolicy.PARTIAL)
    forbidden = default_execution(
        fill_timing=FillTiming.SAME_BAR,
        fill_price=FillPrice.CLOSE,
        lookahead=LookaheadPolicy.FORBIDDEN,
    )
    allowed = forbidden.model_copy(update={"lookahead": LookaheadPolicy.ALLOWED})
    lex = default_execution(fill_timing=FillTiming.SAME_BAR)
    native = default_execution(
        fill_timing=FillTiming.SAME_BAR,
        simultaneous_orders=SimultaneousOrderPolicy.ENGINE_NATIVE,
    )

    expensive = buy_hold_signals(stamps).with_columns(
        pl.when(pl.col("signal_id") == "entry")
        .then(pl.lit(2000.0))
        .otherwise(pl.col("target_qty"))
        .alias("target_qty")
    )

    missing_left = bars_for(stamps[:3] + stamps[4:])
    utc_stamps = [
        datetime.combine(ts.date(), time(9, 30), tzinfo=UTC) for ts in stamps
    ]
    two_names = bars_for(stamps, "AAA").vstack(bars_for(stamps, "ZZZ", base=50.0))
    cheap = buy_hold_signals(stamps, "AAA")
    expensive_peer = buy_hold_signals(stamps, "ZZZ").with_columns(
        pl.when(pl.col("signal_id") == "entry")
        .then(pl.lit(2000.0))
        .otherwise(pl.col("target_qty"))
        .alias("target_qty")
    )
    two_signals = expensive_peer.vstack(cheap)

    split = _action_rows(stamps, "split", 2.0, 0.0)
    dividend = _action_rows(stamps, "dividend", 1.0, 1.25)

    lookahead_signals = buy_hold_signals(stamps).with_columns(
        pl.when(pl.col("signal_id") == "entry")
        .then(pl.lit("lookahead_sentinel"))
        .otherwise(pl.col("signal_id"))
        .alias("signal_id")
    )

    return (
        _case(
            "fill-timing-next-vs-same",
            "Next-bar fill vs same-bar fill",
            "fill_timing",
            AttributionCategory.FILL_TIMING,
            next_bar,
            same_bar,
        ),
        _case(
            "fill-timing-matched",
            "Both engines next-bar (negative control)",
            "fill_timing",
            None,
            next_bar,
            next_bar,
        ),
        _case(
            "fill-price-open-vs-close",
            "Same-bar open fill vs close fill",
            "fill_price",
            AttributionCategory.FILL_PRICE,
            open_px,
            close_px,
        ),
        _case(
            "fill-price-matched",
            "Both engines same-bar open (negative control)",
            "fill_price",
            None,
            open_px,
            open_px,
        ),
        _case(
            "fee-rounding-half-even-vs-truncate",
            "Per-share fee 0.015 rounded half-even vs truncated",
            "fee",
            AttributionCategory.FEE,
            even,
            trunc,
        ),
        _case(
            "fee-matched",
            "Both engines half-even fee rounding (negative control)",
            "fee",
            None,
            even,
            even,
        ),
        _case(
            "cash-reject-vs-partial",
            "Oversized order rejected vs partially filled",
            "cash",
            AttributionCategory.CASH_MARGIN_REJECTION,
            reject,
            partial,
            signals=expensive,
        ),
        _case(
            "cash-matched",
            "Both engines reject oversized orders (negative control)",
            "cash",
            None,
            reject,
            reject,
            signals=expensive,
        ),
        _case(
            "missing-bar-left-gap",
            "Left feed drops one session bar",
            "bar_session_alignment",
            AttributionCategory.BAR_SESSION_ALIGNMENT,
            next_bar,
            next_bar,
            bars_left=missing_left,
            bars_right=bars_for(stamps),
            notes="Data hole, not a spec mutation.",
        ),
        _case(
            "bar-matched",
            "Identical session bars (negative control)",
            "bar_session_alignment",
            None,
            next_bar,
            next_bar,
        ),
        _case(
            "timezone-ny-vs-utc",
            "09:30 labeled America/New_York vs UTC",
            "bar_session_alignment",
            AttributionCategory.BAR_SESSION_ALIGNMENT,
            next_bar,
            next_bar,
            bars_left=bars_for(stamps),
            bars_right=bars_for(utc_stamps),
        ),
        _case(
            "split-applied-vs-ignored",
            "2-for-1 split applied vs omitted",
            "corporate_action",
            AttributionCategory.CORPORATE_ACTION,
            same_bar,
            same_bar,
            actions_left=split,
            actions_right=empty_actions(),
        ),
        _case(
            "split-matched",
            "Both engines apply the 2-for-1 split (negative control)",
            "corporate_action",
            None,
            same_bar,
            same_bar,
            actions_left=split,
            actions_right=split,
        ),
        _case(
            "dividend-cash-vs-omitted",
            "Cash dividend applied vs omitted",
            "corporate_action",
            AttributionCategory.CORPORATE_ACTION,
            same_bar,
            same_bar,
            actions_left=dividend,
            actions_right=empty_actions(),
        ),
        _case(
            "lookahead-sentinel",
            "Same-bar close vs next-bar close cheat",
            "lookahead",
            AttributionCategory.LOOKAHEAD,
            forbidden,
            allowed,
            signals=lookahead_signals,
        ),
        _case(
            "lookahead-matched",
            "Both engines forbid lookahead (negative control)",
            "lookahead",
            None,
            forbidden,
            forbidden,
            signals=lookahead_signals,
        ),
        _case(
            "rebalance-ordering",
            "Lexicographic vs native simultaneous-order policy",
            "simultaneous_orders",
            AttributionCategory.UNEXPLAINED,
            lex.model_copy(update={"cash": CashPolicy.PARTIAL}),
            native.model_copy(update={"cash": CashPolicy.PARTIAL}),
            bars_left=two_names,
            bars_right=two_names,
            signals=two_signals,
            instruments=("AAA", "ZZZ"),
            notes="No claimed category for fill ordering; unexplained is the correct result.",
        ),
        _case(
            "rebalance-matched",
            "Both engines lexicographic rebalance (negative control)",
            "simultaneous_orders",
            None,
            lex.model_copy(update={"cash": CashPolicy.PARTIAL}),
            lex.model_copy(update={"cash": CashPolicy.PARTIAL}),
            bars_left=two_names,
            bars_right=two_names,
            signals=two_signals,
            instruments=("AAA", "ZZZ"),
        ),
    )


def case_by_id(case_id: str) -> GoldenCase:
    for item in catalog():
        if item.spec.case_id == case_id:
            return item
    raise KeyError(case_id)
