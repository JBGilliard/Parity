"""SMA crossover signals. Manual engine ports live in teardown/ports."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from parity.ledger import as_utc, frame_from_rows
from parity.model import EventKind

NY = ZoneInfo("America/New_York")


def synthetic_daily_bars(
    instrument_id: str = "SYN",
    n: int = 80,
    seed: int = 7,
    start: datetime | None = None,
) -> pl.DataFrame:
    day = (start or datetime(2022, 1, 3, tzinfo=NY)).date()
    stamps: list[datetime] = []
    while len(stamps) < n:
        if day.weekday() < 5:
            stamps.append(datetime.combine(day, time(9, 30), tzinfo=NY))
        day += timedelta(days=1)
    price = 100.0
    rows = []
    state = seed
    for i, ts in enumerate(stamps):
        state = (1103515245 * state + 12345) % (2**31)  # glibc LCG so the walk is pinned without numpy
        shock = (state / 2**31 - 0.5) * 1.4
        open_px = price
        close = max(1.0, price + shock)
        high = max(open_px, close) + 0.15
        low = min(open_px, close) - 0.15
        rows.append(
            {
                "event_id": f"syn-{i}",
                "ts_utc": as_utc(ts),
                "ts_source": ts.isoformat(),
                "instrument_id": instrument_id,
                "source_payload": "{}",
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": 10_000.0 + i,
                "session_id": "XNYS",
            }
        )
        price = close
    return frame_from_rows(EventKind.BAR, rows)


def sma_crossover_signals(bars: pl.DataFrame, fast: int = 20, slow: int = 50) -> pl.DataFrame:
    frame = bars.sort("ts_utc").with_columns(
        pl.col("close").rolling_mean(fast).alias("fast"),
        pl.col("close").rolling_mean(slow).alias("slow"),
    )
    rows = []
    position = 0.0
    for i, row in enumerate(frame.iter_rows(named=True)):
        fast_v, slow_v = row["fast"], row["slow"]
        if fast_v is None or slow_v is None:
            continue
        target = 1.0 if fast_v > slow_v else 0.0
        if target == position:
            continue
        rows.append(
            {
                "event_id": f"sma-{i}",
                "ts_utc": as_utc(row["ts_utc"]),
                "ts_source": row["ts_source"],
                "instrument_id": row["instrument_id"],
                "source_payload": "{}",
                "signal_id": f"sma-{'entry' if target else 'exit'}-{i}",
                "side": "buy" if target else "sell",
                "target_qty": target,
            }
        )
        position = target
    return frame_from_rows(EventKind.SIGNAL, rows)
