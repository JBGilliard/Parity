"""First-break detection and conservative attribution."""

from __future__ import annotations

from datetime import datetime

import polars as pl

from parity.ledger import KIND_ORDER, Ledger, as_utc
from parity.model import (
    AttributionCategory,
    CaseSpec,
    ComparisonResult,
    Confidence,
    EventKind,
    EvidenceItem,
    ExecutionSpec,
    Finding,
    FirstDivergence,
    TolerancePolicy,
)
from parity.scope import EngineId

_NUMERIC_FIELDS: dict[EventKind, tuple[str, ...]] = {
    EventKind.BAR: ("open", "high", "low", "close", "volume"),
    EventKind.SIGNAL: ("target_qty",),
    EventKind.ORDER: ("qty",),
    EventKind.FILL: ("qty", "price"),
    EventKind.FEE: ("amount",),
    EventKind.CASH: ("amount", "balance"),
    EventKind.POSITION: ("qty", "avg_price", "market_value"),
    EventKind.CORPORATE_ACTION: ("ratio", "cash_amount"),
}

_TEXT_FIELDS: dict[EventKind, tuple[str, ...]] = {
    EventKind.ORDER: ("status", "side"),
    EventKind.FILL: ("side",),
    EventKind.CASH: ("reason",),
    EventKind.CORPORATE_ACTION: ("action_type",),
}


def compare(
    left: Ledger,
    right: Ledger,
    *,
    left_engine: EngineId,
    right_engine: EngineId,
    left_spec: ExecutionSpec,
    right_spec: ExecutionSpec,
    tolerance: TolerancePolicy,
    case: CaseSpec,
) -> ComparisonResult:
    break_row = first_break(left, right, tolerance)
    if break_row is None:
        return ComparisonResult(
            left_engine=left_engine, right_engine=right_engine, finding=None
        )
    divergence = FirstDivergence(
        ts_utc=break_row["ts_utc"],
        event_kind=break_row["kind"],
        field=break_row["field"],
        left_engine=left_engine,
        right_engine=right_engine,
        left_value=break_row["left_value"],
        right_value=break_row["right_value"],
    )
    category, confidence, evidence, notes = attribute(
        break_row, left, right, left_spec, right_spec, case
    )
    finding = Finding(
        category=category,
        confidence=confidence,
        engines=(left_engine, right_engine),
        evidence=evidence,
        first_divergence=None if category is AttributionCategory.UNEXPLAINED else divergence,
        notes=notes,
    )
    return ComparisonResult(
        left_engine=left_engine, right_engine=right_engine, finding=finding
    )


def first_break(
    left: Ledger, right: Ledger, tolerance: TolerancePolicy
) -> dict[str, object] | None:
    joined = _flatten(left, "left").join(
        _flatten(right, "right"),
        on=["ts_utc", "kind_rank", "kind", "instrument_id", "field"],
        how="full",
        coalesce=True,
    ).sort(["ts_utc", "kind_rank", "instrument_id", "field"])
    for row in joined.iter_rows(named=True):
        if _within_tolerance(row, tolerance):
            continue
        kind = EventKind(row["kind"])
        ts = row["ts_utc"]
        if not isinstance(ts, datetime):
            continue
        return {
            "ts_utc": as_utc(ts),
            "kind": kind,
            "field": str(row["field"]),
            "instrument_id": str(row["instrument_id"]),
            "left_value": _fmt(row.get("left_num"), row.get("left_text")),
            "right_value": _fmt(row.get("right_num"), row.get("right_text")),
            "left_event_id": row.get("left_event_id"),
            "right_event_id": row.get("right_event_id"),
        }
    return None


def attribute(
    break_row: dict[str, object],
    left: Ledger,
    right: Ledger,
    left_spec: ExecutionSpec,
    right_spec: ExecutionSpec,
    case: CaseSpec,
) -> tuple[AttributionCategory, Confidence, tuple[EvidenceItem, ...], str]:
    votes: list[AttributionCategory] = []
    if _is_fill_timing(break_row, left, right, left_spec, right_spec):
        votes.append(AttributionCategory.FILL_TIMING)
    if _is_fill_price(break_row):
        votes.append(AttributionCategory.FILL_PRICE)
    if _is_fee(break_row):
        votes.append(AttributionCategory.FEE)
    if break_row["kind"] is EventKind.BAR:
        votes.append(AttributionCategory.BAR_SESSION_ALIGNMENT)
    if _is_cash_reject(break_row, left, right):
        votes.append(AttributionCategory.CASH_MARGIN_REJECTION)
    if break_row["kind"] is EventKind.CORPORATE_ACTION or (
        break_row["kind"] is EventKind.POSITION
        and _has_ca_at(left, right, break_row["ts_utc"])  # type: ignore[arg-type]
    ):
        votes.append(AttributionCategory.CORPORATE_ACTION)
    if _is_lookahead(break_row, left_spec, right_spec, case):
        votes.append(AttributionCategory.LOOKAHEAD)

    if left_spec.simultaneous_orders != right_spec.simultaneous_orders:
        # ordering isn't a claimed category; don't dress it up as a cash reject
        votes = [
            vote
            for vote in votes
            if vote is not AttributionCategory.CASH_MARGIN_REJECTION
        ]
    unique = list(dict.fromkeys(votes))
    evidence = (
        EvidenceItem(
            summary=(
                f"{break_row['kind'].value}.{break_row['field']} "
                f"{break_row['left_value']} vs {break_row['right_value']}"
            ),
            event_kind=break_row["kind"],  # type: ignore[arg-type]
            left_event_id=str(break_row.get("left_event_id") or "") or None,
            right_event_id=str(break_row.get("right_event_id") or "") or None,
        ),
    )
    if not unique:
        return (
            AttributionCategory.UNEXPLAINED,
            Confidence.NONE,
            evidence,
            "no rule matched",
        )
    # lookahead is a price delta; pick the more specific vote
    priority = (
        AttributionCategory.LOOKAHEAD,
        AttributionCategory.FILL_TIMING,
        AttributionCategory.CASH_MARGIN_REJECTION,
        AttributionCategory.CORPORATE_ACTION,
        AttributionCategory.BAR_SESSION_ALIGNMENT,
        AttributionCategory.FEE,
        AttributionCategory.FILL_PRICE,
    )
    category = next(item for item in priority if item in unique)
    return category, _confidence(category, left_spec, right_spec), evidence, ""


def _flatten(ledger: Ledger, side: str) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for kind, frame in ledger.events.items():
        if frame.is_empty():
            continue
        fields = list(_NUMERIC_FIELDS[kind]) + list(_TEXT_FIELDS.get(kind, ()))
        for field_name in fields:
            piece = frame.select(
                pl.col("ts_utc"),
                pl.col("instrument_id"),
                pl.col("event_id").alias(f"{side}_event_id"),
                pl.lit(KIND_ORDER[kind]).alias("kind_rank"),
                pl.lit(kind.value).alias("kind"),
                pl.lit(field_name).alias("field"),
                pl.col(field_name).cast(pl.Float64, strict=False).alias(f"{side}_num")
                if field_name in _NUMERIC_FIELDS[kind]
                else pl.lit(None).cast(pl.Float64).alias(f"{side}_num"),
                pl.col(field_name).cast(pl.String, strict=False).alias(f"{side}_text")
                if field_name in _TEXT_FIELDS.get(kind, ())
                else pl.lit(None).cast(pl.String).alias(f"{side}_text"),
            )
            frames.append(piece)
        # missing event should be a break, not a silent join skip
        presence = frame.select(
            pl.col("ts_utc"),
            pl.col("instrument_id"),
            pl.col("event_id").alias(f"{side}_event_id"),
            pl.lit(KIND_ORDER[kind]).alias("kind_rank"),
            pl.lit(kind.value).alias("kind"),
            pl.lit("presence").alias("field"),
            pl.lit(1.0).alias(f"{side}_num"),
            pl.lit(None).cast(pl.String).alias(f"{side}_text"),
        )
        frames.append(presence)
    if not frames:
        return pl.DataFrame(
            schema={
                "ts_utc": pl.Datetime(time_unit="us", time_zone="UTC"),
                "instrument_id": pl.String(),
                f"{side}_event_id": pl.String(),
                "kind_rank": pl.Int64(),
                "kind": pl.String(),
                "field": pl.String(),
                f"{side}_num": pl.Float64(),
                f"{side}_text": pl.String(),
            }
        )
    return pl.concat(frames, how="vertical")


def _within_tolerance(row: dict[str, object], tolerance: TolerancePolicy) -> bool:
    left_num = row.get("left_num")
    right_num = row.get("right_num")
    left_text = row.get("left_text")
    right_text = row.get("right_text")
    if left_num is None and right_num is None and left_text is None and right_text is None:
        return True
    if (left_num is None) != (right_num is None) and row["field"] != "presence":
        if left_text or right_text:
            return left_text == right_text
        return False
    if row["field"] == "presence":
        return (left_num or 0) == (right_num or 0)
    if left_text is not None or right_text is not None:
        if left_text != right_text:
            return False
        if left_num is None and right_num is None:
            return True
    if left_num is None or right_num is None:
        return left_num == right_num
    delta = abs(float(left_num) - float(right_num))
    field = str(row["field"])
    kind = str(row["kind"])
    limit = _limit(kind, field, tolerance)
    return delta <= limit


def _limit(kind: str, field: str, tolerance: TolerancePolicy) -> float:
    if field in {"price", "open", "high", "low", "close", "avg_price", "market_value"}:
        return float(tolerance.price)
    if field in {"qty", "target_qty", "volume", "ratio"}:
        return float(tolerance.qty)
    if field in {"amount", "balance"} and kind == EventKind.FEE.value:
        return float(tolerance.fee)
    if field in {"amount", "balance", "cash_amount"}:
        return float(tolerance.cash)
    return float(tolerance.price)


def _fmt(num: object, text: object) -> str:
    if text not in (None, ""):
        return str(text)
    if num is None:
        return "<missing>"
    return format(float(num), ".10g")


def _is_fill_timing(
    break_row: dict[str, object],
    left: Ledger,
    right: Ledger,
    left_spec: ExecutionSpec,
    right_spec: ExecutionSpec,
) -> bool:
    if left_spec.fill_timing != right_spec.fill_timing:
        # vectorbt's first break is often the order row, not the fill
        return break_row["kind"] in {
            EventKind.FILL,
            EventKind.ORDER,
            EventKind.POSITION,
            EventKind.CASH,
            EventKind.FEE,
        }
    if break_row["kind"] is not EventKind.FILL:
        return False
    if break_row["field"] not in {"presence", "side"} and "<missing>" not in (
        str(break_row["left_value"]),
        str(break_row["right_value"]),
    ):
        return False
    ts = break_row["ts_utc"]
    instrument_id = str(break_row["instrument_id"])
    other = right if str(break_row["right_value"]) == "<missing>" else left
    fills = other.frame(EventKind.FILL).filter(pl.col("instrument_id") == instrument_id)
    if fills.is_empty():
        return False
    later = fills.filter(pl.col("ts_utc") != ts)
    return not later.is_empty()


def _is_fill_price(break_row: dict[str, object]) -> bool:
    return break_row["kind"] is EventKind.FILL and break_row["field"] == "price" and (
        "<missing>" not in (str(break_row["left_value"]), str(break_row["right_value"]))
    )


def _is_fee(break_row: dict[str, object]) -> bool:
    return break_row["kind"] is EventKind.FEE and break_row["field"] == "amount"


def _is_cash_reject(break_row: dict[str, object], left: Ledger, right: Ledger) -> bool:
    ts = break_row["ts_utc"]
    if not isinstance(ts, datetime):
        return False
    reasons = pl.concat(
        [
            left.frame(EventKind.CASH).select("ts_utc", "reason"),
            right.frame(EventKind.CASH).select("ts_utc", "reason"),
        ]
    ).filter(pl.col("ts_utc") == ts)
    rejected = "rejected" in reasons["reason"].to_list() if not reasons.is_empty() else False
    return rejected and break_row["kind"] in {
        EventKind.FILL,
        EventKind.CASH,
        EventKind.ORDER,
        EventKind.POSITION,
    }


def _has_ca_at(left: Ledger, right: Ledger, ts: datetime) -> bool:
    for ledger in (left, right):
        frame = ledger.frame(EventKind.CORPORATE_ACTION)
        if not frame.is_empty() and frame.filter(pl.col("ts_utc") == ts).height:
            return True
    return False


def _is_lookahead(
    break_row: dict[str, object],
    left_spec: ExecutionSpec,
    right_spec: ExecutionSpec,
    case: CaseSpec,
) -> bool:
    if left_spec.lookahead != right_spec.lookahead:
        return break_row["kind"] in {EventKind.FILL, EventKind.FEE, EventKind.CASH}
    return "lookahead" in case.isolated_variable and break_row["kind"] is EventKind.FILL


def _confidence(
    category: AttributionCategory, left: ExecutionSpec, right: ExecutionSpec
) -> Confidence:
    aligned = {
        AttributionCategory.FILL_TIMING: left.fill_timing != right.fill_timing,
        AttributionCategory.FILL_PRICE: left.fill_price != right.fill_price,
        AttributionCategory.FEE: left.fee != right.fee,
        AttributionCategory.CASH_MARGIN_REJECTION: left.cash != right.cash,
        AttributionCategory.LOOKAHEAD: left.lookahead != right.lookahead,
        AttributionCategory.BAR_SESSION_ALIGNMENT: True,
        AttributionCategory.CORPORATE_ACTION: True,
    }
    return Confidence.HIGH if aligned.get(category) else Confidence.MEDIUM
