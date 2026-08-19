"""vectorbt runner. Import is optional; missing extra raises EngineNotInstalled."""

from __future__ import annotations

import io
import sys

import polars as pl

from parity.engines.protocol import Capability, EngineNotInstalled, EngineRun
from parity.ledger import Ledger, as_utc, frame_from_rows, payload_json
from parity.model import (
    CashPolicy,
    EventKind,
    ExecutionSpec,
    FeeMode,
    FillPrice,
    FillTiming,
)
from parity.scope import EngineId

VECTORBT_CAPABILITIES = (
    Capability("bar", "native", "input bars retained in the ledger"),
    Capability("signal", "native", "Parity signal table is retained, not a vectorbt object"),
    Capability("order", "native", "filled orders via Portfolio.orders; rejects via logs"),
    Capability("fill", "native", "order records are fills"),
    Capability("fee", "native", "orders.Fees column"),
    Capability("cash", "native", "logs New Cash and pf.cash()"),
    Capability("position", "native", "logs New Position and pf.assets()"),
    Capability("corporate_action", "unavailable", "no native CA stream; input table stored as raw"),
)


def vectorbt_available() -> bool:
    try:
        import vectorbt  # noqa: F401
    except ImportError:
        return False
    return True


def run_vectorbt(
    bars: pl.DataFrame,
    signals: pl.DataFrame,
    spec: ExecutionSpec,
    *,
    initial_cash: float = 10_000.0,
) -> EngineRun:
    if not vectorbt_available():
        raise EngineNotInstalled("vectorbt extra is not installed")
    import vectorbt as vbt

    close, open_px, size = _order_arrays(bars, signals, spec)
    price = open_px if spec.fill_price is FillPrice.OPEN else close
    if spec.fill_price is FillPrice.HIGH:
        price = _series(bars, "high")
    elif spec.fill_price is FillPrice.LOW:
        price = _series(bars, "low")
    elif spec.fill_price is FillPrice.CLOSE:
        price = close
    fees, fixed_fees = _fee_params(spec, price)
    pf = vbt.Portfolio.from_orders(
        close=close,
        size=size,
        price=price,
        fees=fees,
        fixed_fees=fixed_fees,
        init_cash=initial_cash,
        freq="B",
        log=True,
        allow_partial=spec.cash is not CashPolicy.REJECT,
        direction="longonly",
    )
    raw = {
        "orders.csv": pf.orders.records_readable.to_csv(index=False).encode(),
        "logs.csv": pf.logs.records_readable.to_csv(index=False).encode(),
        "cash.csv": pf.cash().to_csv().encode(),
        "assets.csv": pf.assets().to_csv().encode(),
        "value.csv": pf.value().to_csv().encode(),
        "vectorbt_version.txt": f"{vbt.__version__}\n".encode(),
    }
    ledger = _ledger_from_portfolio(bars, signals, pf)
    return EngineRun(
        engine_id=EngineId.VECTORBT,
        ledger=ledger,
        raw_files=raw,
        parameters={
            "fill_timing": spec.fill_timing.value,
            "fill_price": spec.fill_price.value,
            "python": sys.version.split()[0],
        },
        capabilities=VECTORBT_CAPABILITIES,
    )


def read_vectorbt_raw(
    bars: pl.DataFrame,
    signals: pl.DataFrame,
    orders_csv: str,
    logs_csv: str,
) -> Ledger:
    import pandas as pd

    orders = pd.read_csv(io.StringIO(orders_csv))
    logs = pd.read_csv(io.StringIO(logs_csv))
    return _ledger_from_tables(bars, signals, orders, logs)


def _series(bars: pl.DataFrame, column: str):
    import pandas as pd

    # skip to_pandas — it wants pyarrow, which isn't a core dep
    ts = [as_utc(value) for value in bars["ts_utc"].to_list()]
    return pd.Series(bars[column].to_list(), index=pd.DatetimeIndex(ts, tz="UTC"), name=column)


def _order_arrays(bars: pl.DataFrame, signals: pl.DataFrame, spec: ExecutionSpec):
    import pandas as pd

    close = _series(bars, "close")
    open_px = _series(bars, "open")
    target = pd.Series(0.0, index=close.index)
    for row in signals.sort("ts_utc").iter_rows(named=True):
        ts = pd.Timestamp(as_utc(row["ts_utc"]))
        target.loc[target.index >= ts] = float(row["target_qty"])
    size = target.diff()
    size.iloc[0] = target.iloc[0]
    if spec.fill_timing is FillTiming.NEXT_BAR:
        size = size.shift(1).fillna(0.0)
    return close, open_px, size


def _fee_params(spec: ExecutionSpec, price):
    if spec.fee.mode is FeeMode.NONE:
        return 0.0, 0.0
    if spec.fee.mode is FeeMode.BPS:
        return float(spec.fee.value) / 10_000.0, 0.0
    if spec.fee.mode is FeeMode.PER_TRADE:
        return 0.0, float(spec.fee.value)
    if spec.fee.mode is FeeMode.PER_SHARE:
        # vbt fees are a fraction of notional
        return (float(spec.fee.value) / price), 0.0
    return 0.0, 0.0


def _ledger_from_portfolio(bars: pl.DataFrame, signals: pl.DataFrame, pf) -> Ledger:
    return _ledger_from_tables(
        bars, signals, pf.orders.records_readable, pf.logs.records_readable
    )


def _ledger_from_tables(bars: pl.DataFrame, signals: pl.DataFrame, orders, logs) -> Ledger:
    import pandas as pd

    bar_rows = [dict(row) for row in bars.iter_rows(named=True)]
    signal_rows = [dict(row) for row in signals.iter_rows(named=True)]
    fill_rows = []
    fee_rows = []
    order_rows = []
    for _, order in orders.iterrows():
        ts = pd.Timestamp(order["Timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts = as_utc(ts.to_pydatetime())
        order_id = str(order["Order Id"])
        side = str(order["Side"]).lower()
        qty = float(order["Size"])
        price = float(order["Price"])
        fee = float(order["Fees"])
        fill_id = f"vbt-fill-{order_id}"
        payload = payload_json(order.to_dict())
        instrument_id = _instrument(order.get("Column"), bars)
        order_rows.append(
            {
                "event_id": f"vbt-ord-{order_id}",
                "ts_utc": ts,
                "ts_source": ts.isoformat(),
                "instrument_id": instrument_id,
                "source_payload": payload,
                "order_id": order_id,
                "side": side,
                "qty": qty,
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
                "instrument_id": instrument_id,
                "source_payload": payload,
                "fill_id": fill_id,
                "order_id": order_id,
                "side": side,
                "qty": qty,
                "price": price,
            }
        )
        fee_rows.append(
            {
                "event_id": f"vbt-fee-{order_id}",
                "ts_utc": ts,
                "ts_source": ts.isoformat(),
                "instrument_id": instrument_id,
                "source_payload": payload,
                "fee_id": f"vbt-fee-{order_id}",
                "fill_id": fill_id,
                "amount": fee,
                "currency": "USD",
            }
        )
    cash_rows = []
    position_rows = []
    for _, log in logs.iterrows():
        ts = pd.Timestamp(log["Timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        ts = as_utc(ts.to_pydatetime())
        instrument_id = _instrument(log.get("Column"), bars)
        payload = payload_json(log.to_dict())
        cash_rows.append(
            {
                "event_id": f"vbt-csh-{log['Log Id']}",
                "ts_utc": ts,
                "ts_source": ts.isoformat(),
                "instrument_id": instrument_id,
                "source_payload": payload,
                "cash_id": f"vbt-csh-{log['Log Id']}",
                "amount": float(log["New Cash"]) - float(log["Cash"]),
                "balance": float(log["New Cash"]),
                "reason": str(log.get("Result Status") or "log"),
            }
        )
        position_rows.append(
            {
                "event_id": f"vbt-pos-{log['Log Id']}",
                "ts_utc": ts,
                "ts_source": ts.isoformat(),
                "instrument_id": instrument_id,
                "source_payload": payload,
                "qty": float(log["New Position"]),
                "avg_price": 0.0,
                "market_value": float(log["New Value"]) - float(log["New Cash"]),
            }
        )
    return Ledger(
        {
            EventKind.BAR: frame_from_rows(EventKind.BAR, bar_rows),
            EventKind.SIGNAL: frame_from_rows(EventKind.SIGNAL, signal_rows),
            EventKind.ORDER: frame_from_rows(EventKind.ORDER, order_rows),
            EventKind.FILL: frame_from_rows(EventKind.FILL, fill_rows),
            EventKind.FEE: frame_from_rows(EventKind.FEE, fee_rows),
            EventKind.CASH: frame_from_rows(EventKind.CASH, cash_rows),
            EventKind.POSITION: frame_from_rows(EventKind.POSITION, position_rows),
            EventKind.CORPORATE_ACTION: frame_from_rows(EventKind.CORPORATE_ACTION, []),
        }
    )


def _instrument(column: object, bars: pl.DataFrame) -> str:
    names = bars.get_column("instrument_id").unique().to_list()
    if str(column) in names:
        return str(column)
    try:
        index = int(column)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(names[0]) if names else "TEST"
    if 0 <= index < len(names):
        return str(names[index])
    return str(names[0]) if names else "TEST"

