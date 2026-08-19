"""Execution vocabulary, manifests, and finding contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parity.scope import SCHEMA_VERSION, EngineId

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FillTiming(StrEnum):
    SAME_BAR = "same_bar"
    NEXT_BAR = "next_bar"


class FillPrice(StrEnum):
    OPEN = "open"
    CLOSE = "close"
    HIGH = "high"
    LOW = "low"
    VWAP = "vwap"
    LIMIT = "limit"


class FeeMode(StrEnum):
    NONE = "none"
    PER_SHARE = "per_share"
    PER_TRADE = "per_trade"
    BPS = "bps"


class RoundingMode(StrEnum):
    HALF_EVEN = "half_even"
    HALF_UP = "half_up"
    TRUNCATE = "truncate"


class CashPolicy(StrEnum):
    REJECT = "reject"
    PARTIAL = "partial"
    MARGIN = "margin"
    IGNORE = "ignore"


class SimultaneousOrderPolicy(StrEnum):
    SYMBOL_LEXICOGRAPHIC = "symbol_lexicographic"
    ENGINE_NATIVE = "engine_native"


class MissingBarPolicy(StrEnum):
    SKIP = "skip"
    FAIL = "fail"
    FORWARD_FILL = "forward_fill"


class AdjustmentPolicy(StrEnum):
    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"
    TOTAL_RETURN = "total_return"


class DividendPolicy(StrEnum):
    CASH = "cash"
    REINVEST = "reinvest"
    IGNORE = "ignore"


class LookaheadPolicy(StrEnum):
    FORBIDDEN = "forbidden"
    ALLOWED = "allowed"


class EventKind(StrEnum):
    BAR = "bar"
    SIGNAL = "signal"
    ORDER = "order"
    FILL = "fill"
    FEE = "fee"
    CASH = "cash"
    POSITION = "position"
    CORPORATE_ACTION = "corporate_action"


class AttributionCategory(StrEnum):
    FILL_TIMING = "fill_timing"
    FILL_PRICE = "fill_price"
    FEE = "fee"
    BAR_SESSION_ALIGNMENT = "bar_session_alignment"
    CASH_MARGIN_REJECTION = "cash_margin_rejection"
    CORPORATE_ACTION = "corporate_action"
    LOOKAHEAD = "lookahead"
    UNEXPLAINED = "unexplained"


# drop from the bottom if the calendar slips. unexplained is not a claimed category.
CLAIMED_CATEGORIES = (
    AttributionCategory.FILL_TIMING,
    AttributionCategory.FILL_PRICE,
    AttributionCategory.FEE,
    AttributionCategory.BAR_SESSION_ALIGNMENT,
    AttributionCategory.CASH_MARGIN_REJECTION,
    AttributionCategory.CORPORATE_ACTION,
    AttributionCategory.LOOKAHEAD,
)

CATEGORY_CUT_ORDER = (
    AttributionCategory.LOOKAHEAD,
    AttributionCategory.CORPORATE_ACTION,
    AttributionCategory.CASH_MARGIN_REJECTION,
    AttributionCategory.BAR_SESSION_ALIGNMENT,
)


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class FeeSpec(ClosedModel):
    mode: FeeMode
    value: Decimal = Decimal("0")
    rounding: RoundingMode = RoundingMode.HALF_EVEN
    decimals: int = Field(default=2, ge=0, le=12)


class SessionSpec(ClosedModel):
    timezone: str = "America/New_York"
    calendar: str = "XNYS"
    regular_hours_only: bool = True


class ExecutionSpec(ClosedModel):
    fill_timing: FillTiming
    fill_price: FillPrice
    fee: FeeSpec
    cash: CashPolicy
    simultaneous_orders: SimultaneousOrderPolicy
    missing_bar: MissingBarPolicy
    session: SessionSpec
    adjustment: AdjustmentPolicy
    dividend: DividendPolicy
    lookahead: LookaheadPolicy
    fractional_shares: bool = False


class FileRef(ClosedModel):
    path: str
    sha256: Sha256
    media_type: str | None = None


class CaseSpec(ClosedModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    case_id: str
    title: str
    isolated_variable: str
    expected_first_divergence: AttributionCategory | None
    execution: ExecutionSpec
    instruments: tuple[str, ...]
    mutated_execution: ExecutionSpec | None = None
    notes: str = ""


class InputManifest(ClosedModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    data_files: tuple[FileRef, ...]
    timezone: str
    calendar: str
    adjustment: AdjustmentPolicy
    strategy_commit: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class EngineRunMetadata(ClosedModel):
    engine_id: EngineId
    engine_version: str
    image_digest: str | None = None
    python_version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    raw_output: tuple[FileRef, ...]
    ledger_files: dict[EventKind, FileRef]

    @model_validator(mode="after")
    def lean_records_digest(self) -> EngineRunMetadata:
        if self.engine_id is EngineId.LEAN and not self.image_digest:
            raise ValueError("LEAN runs must record the Docker image digest")
        return self


class TolerancePolicy(ClosedModel):
    price: Decimal
    qty: Decimal
    cash: Decimal
    fee: Decimal
    timestamp_ms: int = Field(ge=0)


class EvidenceItem(ClosedModel):
    summary: str
    event_kind: EventKind | None = None
    left_event_id: str | None = None
    right_event_id: str | None = None


class FirstDivergence(ClosedModel):
    ts_utc: datetime
    event_kind: EventKind
    field: str
    left_engine: EngineId
    right_engine: EngineId
    left_value: str
    right_value: str


class Finding(ClosedModel):
    category: AttributionCategory
    confidence: Confidence
    engines: tuple[EngineId, EngineId]
    evidence: tuple[EvidenceItem, ...]
    first_divergence: FirstDivergence | None = None
    notes: str = ""

    @model_validator(mode="after")
    def no_false_certainty(self) -> Finding:
        if self.category is AttributionCategory.UNEXPLAINED and self.confidence not in (
            Confidence.NONE,
            Confidence.LOW,
        ):
            raise ValueError("unexplained findings cannot claim medium or high confidence")
        if self.category is not AttributionCategory.UNEXPLAINED and self.first_divergence is None:
            raise ValueError("classified findings must attach the first divergence")
        if (
            self.category is not AttributionCategory.UNEXPLAINED
            and self.confidence is Confidence.NONE
        ):
            raise ValueError("classified findings need a confidence other than none")
        return self


class ComparisonResult(ClosedModel):
    left_engine: EngineId
    right_engine: EngineId
    finding: Finding | None


DEFAULT_TOLERANCE = TolerancePolicy(
    price=Decimal("1e-8"),
    qty=Decimal("1e-8"),
    cash=Decimal("1e-8"),
    fee=Decimal("1e-8"),
    timestamp_ms=0,
)

VECTORBT_TOLERANCE = TolerancePolicy(
    price=Decimal("1e-6"),
    qty=Decimal("1e-6"),
    cash=Decimal("1e-6"),
    fee=Decimal("1e-6"),
    timestamp_ms=0,
)


class AuditBundleManifest(ClosedModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    bundle_id: str
    created_at: datetime
    case: CaseSpec
    inputs: InputManifest
    engines: tuple[EngineRunMetadata, ...]
    tolerance: TolerancePolicy
    findings: tuple[Finding, ...]

    @model_validator(mode="after")
    def two_primary_engines_when_complete(self) -> AuditBundleManifest:
        ids = tuple(run.engine_id for run in self.engines)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate engine runs in one bundle")
        for run in self.engines:
            missing = [kind for kind in EventKind if kind not in run.ledger_files]
            if missing:
                raise ValueError(f"{run.engine_id} ledger missing {missing}")
        return self
