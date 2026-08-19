"""Spec interpreter for the golden corpus.

Not a backtester and not under audit. A one-knob mutation needs a known
first break; this is how we get one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Any

import polars as pl

from parity.ledger import Ledger, as_utc, frame_from_rows, payload_json
from parity.model import (
    CashPolicy,
    EventKind,
    ExecutionSpec,
    FeeMode,
    FillPrice,
    FillTiming,
    LookaheadPolicy,
    MissingBarPolicy,
    RoundingMode,
    SimultaneousOrderPolicy,
)

INITIAL_CASH = Decimal("10000")
CASH_INSTRUMENT = "_"


@dataclass
class _Position:
    qty: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")


@dataclass
class _Pending:
    signal_id: str
    instrument_id: str
    side: str
    qty: Decimal
    order_id: str


@dataclass
class _Books:
    cash: Decimal
    positions: dict[str, _Position] = field(default_factory=dict)
    seq: int = 0
    rows: dict[EventKind, list[dict[str, Any]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rows:
            self.rows = {kind: [] for kind in EventKind}

    def next_id(self, prefix: str) -> str:
        self.seq += 1
        return f"{prefix}-{self.seq:04d}"


def interpret(
    bars: pl.DataFrame,
    signals: pl.DataFrame,
    actions: pl.DataFrame,
    spec: ExecutionSpec,
    initial_cash: Decimal = INITIAL_CASH,
) -> Ledger:
    books = _Books(cash=initial_cash)
    _emit_cash(books, _bar_start(bars), CASH_INSTRUMENT, initial_cash, "init")
    bar_index = _index_bars(bars)
    action_index = _index_actions(actions)
    pending: list[_Pending] = []

    timestamps = sorted({as_utc(ts) for ts in bars["ts_utc"].to_list()})
    for ts in timestamps:
        instruments = _instruments_at(bars, ts, spec)
        for instrument_id in instruments:
            bar = bar_index[(instrument_id, ts)]
            _emit_bar(books, bar)
        for instrument_id in instruments:
            for action in action_index.get((instrument_id, ts), []):
                _apply_action(books, ts, instrument_id, action, bar_index)
        still_pending: list[_Pending] = []
        for order in pending:
            if (order.instrument_id, ts) in bar_index:
                _fill_pending(books, spec, ts, order, bar_index)
            else:
                still_pending.append(order)
        pending = still_pending
        queued = _signals_at(signals, ts, spec)
        for signal in queued:
            _handle_signal(books, spec, ts, signal, bar_index, pending)
        for instrument_id in instruments:
            _snapshot_position(books, ts, instrument_id, bar_index)

    _apply_missing_signals(spec, signals, bar_index)
    return Ledger({kind: frame_from_rows(kind, rows) for kind, rows in books.rows.items()})


def _bar_start(bars: pl.DataFrame) -> datetime:
    return as_utc(min(bars["ts_utc"].to_list()))


def _index_bars(bars: pl.DataFrame) -> dict[tuple[str, datetime], dict[str, Any]]:
    index: dict[tuple[str, datetime], dict[str, Any]] = {}
    for row in bars.iter_rows(named=True):
        ts = as_utc(row["ts_utc"])
        index[(row["instrument_id"], ts)] = {**row, "ts_utc": ts}
    return index


def _index_actions(actions: pl.DataFrame) -> dict[tuple[str, datetime], list[dict[str, Any]]]:
    if actions.is_empty():
        return {}
    grouped: dict[tuple[str, datetime], list[dict[str, Any]]] = {}
    for row in actions.iter_rows(named=True):
        key = (row["instrument_id"], as_utc(row["ts_utc"]))
        grouped.setdefault(key, []).append(row)
    return grouped


def _signals_at(
    signals: pl.DataFrame, ts: datetime, spec: ExecutionSpec
) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in signals.iter_rows(named=True)
        if as_utc(row["ts_utc"]) == ts
    ]
    if spec.simultaneous_orders is SimultaneousOrderPolicy.SYMBOL_LEXICOGRAPHIC:
        rows.sort(key=lambda row: (row["instrument_id"], row["signal_id"]))
    # ENGINE_NATIVE keeps dataframe order on purpose
    return rows


def _instruments_at(bars: pl.DataFrame, ts: datetime, spec: ExecutionSpec) -> list[str]:
    names = (
        bars.filter(pl.col("ts_utc") == ts)
        .get_column("instrument_id")
        .to_list()
    )
    if spec.simultaneous_orders is SimultaneousOrderPolicy.SYMBOL_LEXICOGRAPHIC:
        return sorted(set(names))
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def _apply_missing_signals(
    spec: ExecutionSpec,
    signals: pl.DataFrame,
    bar_index: dict[tuple[str, datetime], dict[str, Any]],
) -> None:
    if spec.missing_bar is MissingBarPolicy.SKIP:
        return
    # FORWARD_FILL is in the spec but not implemented; skip is the corpus default
    for row in signals.iter_rows(named=True):
        key = (row["instrument_id"], as_utc(row["ts_utc"]))
        if key not in bar_index and spec.missing_bar is MissingBarPolicy.FAIL:
            raise ValueError(
                f"missing bar for {row['instrument_id']} at {key[1].isoformat()}"
            )


def _emit_bar(books: _Books, bar: dict[str, Any]) -> None:
    ts = bar["ts_utc"]
    instrument_id = bar["instrument_id"]
    books.rows[EventKind.BAR].append(
        _common(books, "bar", ts, instrument_id, bar)
        | {
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "volume": float(bar["volume"]),
            "session_id": str(bar.get("session_id") or "XNYS"),
        }
    )


def _apply_action(
    books: _Books,
    ts: datetime,
    instrument_id: str,
    action: dict[str, Any],
    bar_index: dict[tuple[str, datetime], dict[str, Any]],
) -> None:
    action_type = str(action["action_type"])
    ratio = Decimal(str(action.get("ratio") or 1))
    cash_amount = Decimal(str(action.get("cash_amount") or 0))
    books.rows[EventKind.CORPORATE_ACTION].append(
        _common(books, "ca", ts, instrument_id, action)
        | {
            "action_type": action_type,
            "ratio": float(ratio),
            "cash_amount": float(cash_amount),
        }
    )
    position = books.positions.setdefault(instrument_id, _Position())
    if action_type == "split" and position.qty != 0:
        position.qty *= ratio
        position.avg_price = position.avg_price / ratio if ratio else position.avg_price
    elif action_type == "dividend" and position.qty != 0:
        credited = position.qty * cash_amount
        books.cash += credited
        _emit_cash(books, ts, instrument_id, credited, "dividend")
    _snapshot_position(books, ts, instrument_id, bar_index)


def _handle_signal(
    books: _Books,
    spec: ExecutionSpec,
    ts: datetime,
    signal: dict[str, Any],
    bar_index: dict[tuple[str, datetime], dict[str, Any]],
    pending: list[_Pending],
) -> None:
    instrument_id = signal["instrument_id"]
    target = Decimal(str(signal["target_qty"]))
    current = books.positions.setdefault(instrument_id, _Position()).qty
    delta = target - current
    books.rows[EventKind.SIGNAL].append(
        _common(books, "sig", ts, instrument_id, signal)
        | {
            "signal_id": signal["signal_id"],
            "side": _side(delta),
            "target_qty": float(target),
        }
    )
    if delta == 0:
        return
    order_id = books.next_id("ord")
    side = _side(delta)
    qty = abs(delta)
    if not spec.fractional_shares:
        qty = qty.to_integral_value(rounding=ROUND_DOWN)
        if qty == 0:
            return
    books.rows[EventKind.ORDER].append(
        _common(books, "ord", ts, instrument_id, signal)
        | {
            "order_id": order_id,
            "side": side,
            "qty": float(qty),
            "order_type": "market",
            "limit_price": None,
            "status": "submitted",
            "signal_id": signal["signal_id"],
        }
    )
    item = _Pending(
        signal_id=str(signal["signal_id"]),
        instrument_id=instrument_id,
        side=side,
        qty=qty,
        order_id=order_id,
    )
    if spec.fill_timing is FillTiming.SAME_BAR:
        _fill_pending(books, spec, ts, item, bar_index)
    else:
        pending.append(item)


def _fill_pending(
    books: _Books,
    spec: ExecutionSpec,
    ts: datetime,
    order: _Pending,
    bar_index: dict[tuple[str, datetime], dict[str, Any]],
) -> None:
    bar = bar_index[(order.instrument_id, ts)]
    next_bar = _next_bar(bar_index, order.instrument_id, ts)
    price = _fill_price(spec, bar, next_bar)
    qty = order.qty
    fee = _fee(spec, qty, price)
    cost = qty * price
    if order.side == "buy":
        needed = cost + fee
        if needed > books.cash:
            qty = _affordable(spec, books.cash, price)
            if qty <= 0 or spec.cash is CashPolicy.REJECT:
                _reject(books, ts, order)
                return
            fee = _fee(spec, qty, price)
            cost = qty * price
        books.cash -= cost + fee
        _buy(books.positions[order.instrument_id], qty, price)
        cash_delta = -(cost + fee)
    else:
        books.cash += cost - fee
        books.positions[order.instrument_id].qty -= qty
        if books.positions[order.instrument_id].qty == 0:
            books.positions[order.instrument_id].avg_price = Decimal("0")
        cash_delta = cost - fee
    fill_id = books.next_id("fll")
    books.rows[EventKind.FILL].append(
        _common(books, "fll", ts, order.instrument_id, {"order_id": order.order_id})
        | {
            "fill_id": fill_id,
            "order_id": order.order_id,
            "side": order.side,
            "qty": float(qty),
            "price": float(price),
        }
    )
    books.rows[EventKind.FEE].append(
        _common(books, "fee", ts, order.instrument_id, {"fill_id": fill_id})
        | {
            "fee_id": books.next_id("fee"),
            "fill_id": fill_id,
            "amount": float(fee),
            "currency": "USD",
        }
    )
    _emit_cash(books, ts, order.instrument_id, cash_delta, "fill")


def _reject(books: _Books, ts: datetime, order: _Pending) -> None:
    _emit_cash(books, ts, order.instrument_id, Decimal("0"), "rejected")
    for row in reversed(books.rows[EventKind.ORDER]):
        if row["order_id"] == order.order_id:
            row["status"] = "rejected"
            break


def _affordable(spec: ExecutionSpec, cash: Decimal, price: Decimal) -> Decimal:
    if spec.cash not in (CashPolicy.PARTIAL, CashPolicy.IGNORE, CashPolicy.MARGIN):
        return Decimal("0")
    if spec.fee.mode is FeeMode.PER_SHARE:
        denom = price + spec.fee.value
    elif spec.fee.mode is FeeMode.PER_TRADE:
        denom = price
        cash -= spec.fee.value
    elif spec.fee.mode is FeeMode.BPS:
        denom = price * (Decimal("1") + spec.fee.value / Decimal("10000"))
    else:
        denom = price
    if denom <= 0 or cash <= 0:
        return Decimal("0")
    qty = cash / denom
    if not spec.fractional_shares:
        qty = qty.to_integral_value(rounding=ROUND_DOWN)
    return qty


def _buy(position: _Position, qty: Decimal, price: Decimal) -> None:
    total = position.qty * position.avg_price + qty * price
    position.qty += qty
    position.avg_price = total / position.qty if position.qty else Decimal("0")


def _fee(spec: ExecutionSpec, qty: Decimal, price: Decimal) -> Decimal:
    if spec.fee.mode is FeeMode.NONE:
        amount = Decimal("0")
    elif spec.fee.mode is FeeMode.PER_SHARE:
        amount = spec.fee.value * qty
    elif spec.fee.mode is FeeMode.PER_TRADE:
        amount = spec.fee.value
    else:
        amount = spec.fee.value / Decimal("10000") * qty * price
    quant = Decimal("1").scaleb(-spec.fee.decimals)
    rounding = {
        RoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
        RoundingMode.HALF_UP: ROUND_HALF_UP,
        RoundingMode.TRUNCATE: ROUND_DOWN,
    }[spec.fee.rounding]
    return amount.quantize(quant, rounding=rounding)


def _fill_price(
    spec: ExecutionSpec,
    bar: dict[str, Any],
    next_bar: dict[str, Any] | None,
) -> Decimal:
    if spec.lookahead is LookaheadPolicy.ALLOWED and next_bar is not None:
        # ALLOWED is the cheat: fill this bar at next bar's close.
        return Decimal(str(next_bar["close"]))
    if spec.fill_price is FillPrice.VWAP:
        # no volume-weighted series in these micro-cases; typical HLC/3 stand-in
        return (
            Decimal(str(bar["high"]))
            + Decimal(str(bar["low"]))
            + Decimal(str(bar["close"]))
        ) / Decimal("3")
    field = {
        FillPrice.OPEN: "open",
        FillPrice.CLOSE: "close",
        FillPrice.HIGH: "high",
        FillPrice.LOW: "low",
        FillPrice.LIMIT: "close",  # no limit book in the micro-cases
    }[spec.fill_price]
    return Decimal(str(bar[field]))


def _next_bar(
    bar_index: dict[tuple[str, datetime], dict[str, Any]],
    instrument_id: str,
    ts: datetime,
) -> dict[str, Any] | None:
    later = [key[1] for key in bar_index if key[0] == instrument_id and key[1] > ts]
    if not later:
        return None
    return bar_index[(instrument_id, min(later))]


def _snapshot_position(
    books: _Books,
    ts: datetime,
    instrument_id: str,
    bar_index: dict[tuple[str, datetime], dict[str, Any]],
) -> None:
    position = books.positions.setdefault(instrument_id, _Position())
    mark = Decimal(str(bar_index[(instrument_id, ts)]["close"]))
    books.rows[EventKind.POSITION].append(
        _common(books, "pos", ts, instrument_id, {"qty": str(position.qty)})
        | {
            "qty": float(position.qty),
            "avg_price": float(position.avg_price),
            "market_value": float(position.qty * mark),
        }
    )


def _emit_cash(
    books: _Books,
    ts: datetime,
    instrument_id: str,
    amount: Decimal,
    reason: str,
) -> None:
    books.rows[EventKind.CASH].append(
        _common(books, "csh", ts, instrument_id, {"reason": reason})
        | {
            "cash_id": books.next_id("csh"),
            "amount": float(amount),
            "balance": float(books.cash),
            "reason": reason,
        }
    )


def _side(delta: Decimal) -> str:
    if delta > 0:
        return "buy"
    if delta < 0:
        return "sell"
    return "flat"


def _common(
    books: _Books,
    prefix: str,
    ts: datetime,
    instrument_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    ts = as_utc(ts)
    return {
        "event_id": books.next_id(prefix),
        "ts_utc": ts,
        "ts_source": ts.isoformat(),
        "instrument_id": instrument_id,
        "source_payload": payload_json(dict(payload)),
    }
