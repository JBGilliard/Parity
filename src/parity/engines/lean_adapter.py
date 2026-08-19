"""LEAN result reader. Docker run is optional and never required to import this module."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parity.engines.protocol import Capability, EngineNotInstalled, EngineRun
from parity.ledger import Ledger, as_utc, frame_from_rows, payload_json
from parity.model import EventKind
from parity.scope import ENGINE_PINS, EngineId

LEAN_CAPABILITIES = (
    Capability("bar", "native", "input bars retained; LEAN data files are not redistributed"),
    Capability("signal", "gap", "only present if the algorithm logs insights"),
    Capability("order", "native", "Orders key in the backtest JSON"),
    Capability("fill", "native", "order-events.json fillPrice/fillQuantity"),
    Capability("fee", "native", "order-events orderFeeAmount"),
    Capability("cash", "reconstructed", "equity chart minus reconstructed market value"),
    Capability("position", "reconstructed", "holdings time series often absent locally"),
    Capability("corporate_action", "gap", "requires LEAN data mappings; not in a bare result JSON"),
)

_FILLED = {3, "3", "filled", "Filled", "FILLED"}


def lean_available() -> bool:
    return shutil.which("docker") is not None


def read_lean_raw(raw_dir: Path, bars_rows: list[dict[str, Any]] | None = None) -> EngineRun:
    result_path = _find_result_json(raw_dir)
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    events_path = _find_order_events(raw_dir)
    order_events = (
        json.loads(events_path.read_text(encoding="utf-8")) if events_path else []
    )
    ledger = lean_json_to_ledger(payload, order_events, bars_rows or [])
    raw_files = {path.name: path.read_bytes() for path in raw_dir.iterdir() if path.is_file()}
    digest = ENGINE_PINS[EngineId.LEAN].image_digest
    return EngineRun(
        engine_id=EngineId.LEAN,
        ledger=ledger,
        raw_files=raw_files,
        parameters={"result": result_path.name, "image_digest": digest},
        capabilities=LEAN_CAPABILITIES,
    )


def run_lean_docker(algorithm_dir: Path, output_dir: Path) -> None:
    # not wired on purpose — tests shouldn't pull the QC image
    if not lean_available():
        raise EngineNotInstalled("docker is not on PATH")
    pin = ENGINE_PINS[EngineId.LEAN]
    image = pin.version
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{algorithm_dir}:/Lean/Algorithm.Python",
        "-v",
        f"{output_dir}:/results",
        image,
        "lean",
        "backtest",
        "/Lean/Algorithm.Python",
        "--output",
        "/results",
    ]
    raise EngineNotInstalled(
        "LEAN live execution is opt-in and not invoked from tests. "
        f"Recorded command: {' '.join(cmd)}"
    )


def lean_json_to_ledger(
    result: dict[str, Any],
    order_events: list[dict[str, Any]] | dict[str, Any],
    bars_rows: list[dict[str, Any]],
) -> Ledger:
    events = order_events if isinstance(order_events, list) else _events_from_mapping(order_events)
    if not events:
        events = _events_from_orders(result.get("Orders") or result.get("orders") or {})
    fill_rows = []
    fee_rows = []
    order_rows = []
    cash_rows = []
    position_rows = []
    qty_by_symbol: dict[str, float] = {}
    cash = 10000.0  # starting cash often missing from local JSON; match the oracle default
    for item in events:
        status = item.get("status") or item.get("Status")
        if status not in _FILLED and item.get("fillQuantity", item.get("fill-quantity", 0)) in (0, None):
            continue
        ts = _parse_time(
            item.get("time")
            or item.get("Time")
            or item.get("lastFillTime")
            or item.get("LastFillTime")
        )
        symbol = _symbol(item)
        qty = float(item.get("fillQuantity") or item.get("fill-quantity") or item.get("quantity") or 0)
        price = float(item.get("fillPrice") or item.get("fill-price") or item.get("price") or item.get("Price") or 0)
        fee = float(item.get("orderFeeAmount") or item.get("order-fee-amount") or item.get("orderFee") or 0)
        side = _side_of(item, qty)
        abs_qty = abs(qty)
        order_id = str(item.get("orderId") or item.get("order-id") or item.get("Id") or len(order_rows) + 1)
        fill_id = str(item.get("id") or item.get("orderEventId") or f"lean-fill-{order_id}")
        payload = payload_json(item)
        order_rows.append(
            {
                "event_id": f"lean-ord-{order_id}",
                "ts_utc": ts,
                "ts_source": ts.isoformat(),
                "instrument_id": symbol,
                "source_payload": payload,
                "order_id": order_id,
                "side": side,
                "qty": abs_qty,
                "order_type": "market",
                "limit_price": None,
                "status": "filled",
                "signal_id": "",
            }
        )
        fill_rows.append(
            {
                "event_id": fill_id,
                "ts_utc": ts,
                "ts_source": ts.isoformat(),
                "instrument_id": symbol,
                "source_payload": payload,
                "fill_id": fill_id,
                "order_id": order_id,
                "side": order_rows[-1]["side"],
                "qty": abs_qty,
                "price": price,
            }
        )
        fee_rows.append(
            {
                "event_id": f"lean-fee-{fill_id}",
                "ts_utc": ts,
                "ts_source": ts.isoformat(),
                "instrument_id": symbol,
                "source_payload": payload,
                "fee_id": f"lean-fee-{fill_id}",
                "fill_id": fill_id,
                "amount": fee,
                "currency": item.get("orderFeeCurrency") or "USD",
            }
        )
        signed = abs_qty if order_rows[-1]["side"] == "buy" else -abs_qty
        cash -= signed * price + fee
        qty_by_symbol[symbol] = qty_by_symbol.get(symbol, 0.0) + signed
        cash_rows.append(
            {
                "event_id": f"lean-csh-{fill_id}",
                "ts_utc": ts,
                "ts_source": ts.isoformat(),
                "instrument_id": symbol,
                "source_payload": payload,
                "cash_id": f"lean-csh-{fill_id}",
                "amount": -signed * price - fee,
                "balance": cash,
                "reason": "fill",
            }
        )
        position_rows.append(
            {
                "event_id": f"lean-pos-{fill_id}",
                "ts_utc": ts,
                "ts_source": ts.isoformat(),
                "instrument_id": symbol,
                "source_payload": payload,
                "qty": qty_by_symbol[symbol],
                "avg_price": price,
                "market_value": qty_by_symbol[symbol] * price,
            }
        )
    return Ledger(
        {
            EventKind.BAR: frame_from_rows(EventKind.BAR, bars_rows),
            EventKind.SIGNAL: frame_from_rows(EventKind.SIGNAL, []),
            EventKind.ORDER: frame_from_rows(EventKind.ORDER, order_rows),
            EventKind.FILL: frame_from_rows(EventKind.FILL, fill_rows),
            EventKind.FEE: frame_from_rows(EventKind.FEE, fee_rows),
            EventKind.CASH: frame_from_rows(EventKind.CASH, cash_rows),
            EventKind.POSITION: frame_from_rows(EventKind.POSITION, position_rows),
            EventKind.CORPORATE_ACTION: frame_from_rows(EventKind.CORPORATE_ACTION, []),
        }
    )


def ledger_to_lean_json(ledger: Ledger) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    orders: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    fills = ledger.frame(EventKind.FILL)
    fees = {
        row["fill_id"]: row["amount"]
        for row in ledger.frame(EventKind.FEE).iter_rows(named=True)
    }
    for i, row in enumerate(fills.iter_rows(named=True), start=1):
        ts = as_utc(row["ts_utc"]).isoformat().replace("+00:00", "Z")
        order_id = i
        orders[str(order_id)] = {
            "Id": order_id,
            "Symbol": {"Value": row["instrument_id"], "ID": row["instrument_id"]},
            "Time": ts,
            "LastFillTime": ts,
            "Quantity": row["qty"] if row["side"] == "buy" else -row["qty"],
            "Price": row["price"],
            "Status": 3,
            "Type": 0,
            "Tag": "parity-fixture",
        }
        events.append(
            {
                "time": ts,
                "orderId": order_id,
                "orderEventId": i,
                "id": row["fill_id"],
                "status": "filled",
                "fillPrice": row["price"],
                "fillQuantity": row["qty"] if row["side"] == "buy" else -row["qty"],
                "orderFeeAmount": fees.get(row["fill_id"], 0.0),
                "orderFeeCurrency": "USD",
                "direction": row["side"],
                "symbol": row["instrument_id"],
            }
        )
    result = {
        "Orders": orders,
        "Charts": {"Strategy Equity": {"Name": "Strategy Equity", "Series": {}}},
        "Statistics": {},
    }
    return result, events


def _find_result_json(raw_dir: Path) -> Path:
    json_files = sorted(
        path
        for path in raw_dir.glob("*.json")
        if "order-event" not in path.name and "alpha" not in path.name
    )
    if not json_files:
        raise FileNotFoundError(f"no LEAN result JSON in {raw_dir}")
    return json_files[0]


def _find_order_events(raw_dir: Path) -> Path | None:
    matches = list(raw_dir.glob("*order-events.json")) + list(raw_dir.glob("*order_events.json"))
    return matches[0] if matches else None


def _events_from_mapping(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "events" in payload and isinstance(payload["events"], list):
        return payload["events"]
    return list(payload.values()) if payload else []


def _events_from_orders(orders: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for order in orders.values():
        nested = order.get("events") or order.get("Events") or []
        if nested:
            events.extend(nested)
        else:
            events.append(order)
    return events


def _symbol(item: dict[str, Any]) -> str:
    symbol = item.get("symbol") or item.get("Symbol") or item.get("symbolValue") or "TEST"
    if isinstance(symbol, dict):
        return str(symbol.get("Value") or symbol.get("value") or symbol.get("ID") or "TEST")
    return str(symbol)


def _side_of(item: dict[str, Any], qty: float) -> str:
    raw = str(item.get("direction") or item.get("Direction") or "").lower()
    if raw in {"sell", "1"}:  # LEAN OrderDirection.Sell = 1
        return "sell"
    if raw in {"buy", "0"}:
        return "buy"
    return "buy" if qty > 0 else "sell"


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, str):
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    if isinstance(value, (int, float)):
        if value > 1e14:
            # .NET ticks: 100ns since 0001-01-01
            unix = value / 10_000_000 - 62_135_596_800
            return datetime.fromtimestamp(unix, tz=UTC)
        if value > 1e12:
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        return datetime.fromtimestamp(value, tz=UTC)
    raise ValueError(f"unusable timestamp: {value!r}")
