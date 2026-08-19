"""Event ledger schemas. Rows stay in Polars; pydantic is for manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import polars as pl

from parity.model import EventKind

UTC_DTYPE = pl.Datetime(time_unit="us", time_zone="UTC")

_COMMON: dict[str, pl.DataType] = {
    "event_id": pl.String(),
    "ts_utc": UTC_DTYPE,
    "ts_source": pl.String(),
    "instrument_id": pl.String(),
    "source_payload": pl.String(),
}

EVENT_SCHEMAS: dict[EventKind, dict[str, pl.DataType]] = {
    EventKind.BAR: {
        **_COMMON,
        "open": pl.Float64(),
        "high": pl.Float64(),
        "low": pl.Float64(),
        "close": pl.Float64(),
        "volume": pl.Float64(),
        "session_id": pl.String(),
    },
    EventKind.SIGNAL: {
        **_COMMON,
        "signal_id": pl.String(),
        "side": pl.String(),
        "target_qty": pl.Float64(),
    },
    EventKind.ORDER: {
        **_COMMON,
        "order_id": pl.String(),
        "side": pl.String(),
        "qty": pl.Float64(),
        "order_type": pl.String(),
        "limit_price": pl.Float64(),
        "status": pl.String(),
        "signal_id": pl.String(),
    },
    EventKind.FILL: {
        **_COMMON,
        "fill_id": pl.String(),
        "order_id": pl.String(),
        "side": pl.String(),
        "qty": pl.Float64(),
        "price": pl.Float64(),
    },
    EventKind.FEE: {
        **_COMMON,
        "fee_id": pl.String(),
        "fill_id": pl.String(),
        "amount": pl.Float64(),
        "currency": pl.String(),
    },
    EventKind.CASH: {
        **_COMMON,
        "cash_id": pl.String(),
        "amount": pl.Float64(),
        "balance": pl.Float64(),
        "reason": pl.String(),
    },
    EventKind.POSITION: {
        **_COMMON,
        "qty": pl.Float64(),
        "avg_price": pl.Float64(),
        "market_value": pl.Float64(),
    },
    EventKind.CORPORATE_ACTION: {
        **_COMMON,
        "action_type": pl.String(),
        "ratio": pl.Float64(),
        "cash_amount": pl.Float64(),
    },
}

LEDGER_FILE_NAMES = {
    EventKind.BAR: "bars.parquet",
    EventKind.SIGNAL: "signals.parquet",
    EventKind.ORDER: "orders.parquet",
    EventKind.FILL: "fills.parquet",
    EventKind.FEE: "fees.parquet",
    EventKind.CASH: "cash.parquet",
    EventKind.POSITION: "positions.parquet",
    EventKind.CORPORATE_ACTION: "corporate_actions.parquet",
}

# bar/CA before fills so a data hole shows up before the fill that follows it
KIND_ORDER = {
    EventKind.BAR: 0,
    EventKind.CORPORATE_ACTION: 1,
    EventKind.SIGNAL: 2,
    EventKind.ORDER: 3,
    EventKind.FILL: 4,
    EventKind.FEE: 5,
    EventKind.CASH: 6,
    EventKind.POSITION: 7,
}


class LedgerSchemaError(ValueError):
    pass


def schema_for(kind: EventKind) -> dict[str, pl.DataType]:
    return EVENT_SCHEMAS[kind]


def empty_frame(kind: EventKind) -> pl.DataFrame:
    return pl.DataFrame(schema=EVENT_SCHEMAS[kind])


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


def payload_json(payload: Mapping[str, Any] | None) -> str:
    if not payload:
        return "{}"
    return json.dumps(payload, sort_keys=True, default=str)


def frame_from_rows(kind: EventKind, rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = EVENT_SCHEMAS[kind]
    if not rows:
        return empty_frame(kind)
    columns: dict[str, list[Any]] = {name: [] for name in schema}
    for row in rows:
        for name in schema:
            value = row.get(name)
            if name == "ts_utc":
                if not isinstance(value, datetime):
                    raise LedgerSchemaError(f"{kind.value}.ts_utc must be datetime")
                value = as_utc(value)
            elif name == "source_payload" and value is None:
                value = "{}"
            elif name == "instrument_id" and value is None:
                value = ""
            columns[name].append(value)
    return pl.DataFrame(columns, schema=schema)


def validate_events(frame: pl.DataFrame, kind: EventKind) -> None:
    expected = EVENT_SCHEMAS[kind]
    _assert_columns(frame, expected, kind)
    for name, dtype in expected.items():
        actual = frame.schema[name]
        if actual != dtype:
            raise LedgerSchemaError(
                f"{kind.value}.{name}: expected {dtype}, got {actual}"
            )


def _assert_columns(
    frame: pl.DataFrame, expected: Mapping[str, pl.DataType], kind: EventKind
) -> None:
    missing = [name for name in expected if name not in frame.columns]
    extra = [name for name in frame.columns if name not in expected]
    if missing or extra:
        raise LedgerSchemaError(
            f"{kind.value} schema mismatch missing={missing} extra={extra}"
        )


@dataclass
class Ledger:
    events: dict[EventKind, pl.DataFrame]

    def __post_init__(self) -> None:
        complete = {kind: self.events.get(kind, empty_frame(kind)) for kind in EventKind}
        for kind, frame in complete.items():
            validate_events(frame, kind)
        self.events = complete

    @classmethod
    def empty(cls) -> Ledger:
        return cls({kind: empty_frame(kind) for kind in EventKind})

    def frame(self, kind: EventKind) -> pl.DataFrame:
        return self.events[kind]

    def write(self, directory: Path) -> dict[EventKind, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        written: dict[EventKind, Path] = {}
        for kind, frame in self.events.items():
            path = directory / LEDGER_FILE_NAMES[kind]
            frame.write_parquet(path)
            written[kind] = path
        return written

    @classmethod
    def read(cls, directory: Path) -> Ledger:
        events: dict[EventKind, pl.DataFrame] = {}
        for kind, name in LEDGER_FILE_NAMES.items():
            path = directory / name
            if not path.exists():
                raise FileNotFoundError(path)
            events[kind] = pl.read_parquet(path)
        return cls(events)
