from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from parity.ledger import EVENT_SCHEMAS, LEDGER_FILE_NAMES, empty_frame, validate_events
from parity.model import (
    CLAIMED_CATEGORIES,
    AttributionCategory,
    AuditBundleManifest,
    CaseSpec,
    Confidence,
    EngineRunMetadata,
    EventKind,
    EvidenceItem,
    ExecutionSpec,
    FeeMode,
    FeeSpec,
    FileRef,
    FillPrice,
    FillTiming,
    Finding,
    FirstDivergence,
    InputManifest,
    LookaheadPolicy,
    AdjustmentPolicy,
    CashPolicy,
    DividendPolicy,
    MissingBarPolicy,
    SessionSpec,
    SimultaneousOrderPolicy,
    TolerancePolicy,
)
from parity.scope import (
    BUNDLE_LAYOUT,
    ENGINE_PINS,
    NEVER_CUT,
    PRIMARY_ENGINES,
    RELEASE_GATES,
    RELEASE_GATE_STATEMENTS,
    SCHEMA_VERSION,
    SCOPE_CUT_ORDER,
    EngineId,
)


def _digest(payload: bytes = b"") -> str:
    return sha256(payload).hexdigest()


def _execution() -> ExecutionSpec:
    return ExecutionSpec(
        fill_timing=FillTiming.NEXT_BAR,
        fill_price=FillPrice.OPEN,
        fee=FeeSpec(mode=FeeMode.PER_SHARE, value=Decimal("0.005")),
        cash=CashPolicy.REJECT,
        simultaneous_orders=SimultaneousOrderPolicy.SYMBOL_LEXICOGRAPHIC,
        missing_bar=MissingBarPolicy.FAIL,
        session=SessionSpec(),
        adjustment=AdjustmentPolicy.RAW,
        dividend=DividendPolicy.CASH,
        lookahead=LookaheadPolicy.FORBIDDEN,
    )


def _file(path: str) -> FileRef:
    return FileRef(path=path, sha256=_digest())


def _ledger_files() -> dict[EventKind, FileRef]:
    return {
        kind: _file(f"engines/vectorbt/ledger/{LEDGER_FILE_NAMES[kind]}")
        for kind in EventKind
    }


def _engine(engine_id: EngineId) -> EngineRunMetadata:
    pin = ENGINE_PINS[engine_id]
    return EngineRunMetadata(
        engine_id=engine_id,
        engine_version=pin.version,
        image_digest=pin.image_digest,
        raw_output=(_file(f"engines/{engine_id.value}/raw/stdout.txt"),),
        ledger_files=_ledger_files(),
    )


def _divergence() -> FirstDivergence:
    return FirstDivergence(
        ts_utc=datetime(2024, 1, 3, 14, 30, tzinfo=UTC),
        event_kind=EventKind.FILL,
        field="price",
        left_engine=EngineId.VECTORBT,
        right_engine=EngineId.LEAN,
        left_value="10.0",
        right_value="10.01",
    )


def _bundle() -> AuditBundleManifest:
    return AuditBundleManifest(
        bundle_id="case-fill-timing-001",
        created_at=datetime(2026, 8, 18, tzinfo=UTC),
        case=CaseSpec(
            case_id="fill-timing-next-bar",
            title="Next-bar fill vs same-bar fill",
            isolated_variable="fill_timing",
            expected_first_divergence=AttributionCategory.FILL_TIMING,
            execution=_execution(),
            instruments=("TEST",),
        ),
        inputs=InputManifest(
            data_files=(_file("inputs/data/bars.parquet"),),
            timezone="America/New_York",
            calendar="XNYS",
            adjustment=AdjustmentPolicy.RAW,
        ),
        engines=(_engine(EngineId.VECTORBT), _engine(EngineId.LEAN)),
        tolerance=TolerancePolicy(
            price=Decimal("0.00000001"),
            qty=Decimal("0.00000001"),
            cash=Decimal("0.00000001"),
            fee=Decimal("0.00000001"),
            timestamp_ms=0,
        ),
        findings=(
            Finding(
                category=AttributionCategory.FILL_TIMING,
                confidence=Confidence.HIGH,
                engines=(EngineId.VECTORBT, EngineId.LEAN),
                evidence=(
                    EvidenceItem(
                        summary="First fill timestamp differs by one bar.",
                        event_kind=EventKind.FILL,
                    ),
                ),
                first_divergence=_divergence(),
            ),
        ),
    )


def test_readme_is_public_entry() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert "uv sync --group dev" in readme
    assert "Apache-2.0" in readme
    assert "founding" not in readme.lower()
    assert "$149" not in readme
    assert "release gates" not in readme.lower()


def test_primary_engines_are_vectorbt_and_lean() -> None:
    assert PRIMARY_ENGINES == (EngineId.VECTORBT, EngineId.LEAN)
    assert ENGINE_PINS[EngineId.LEAN].image_digest is not None
    assert SCOPE_CUT_ORDER[0] == "nautilustrader_adapter"
    assert "unexplained" in NEVER_CUT


def test_release_gates_are_complete() -> None:
    assert tuple(gate.gate_id for gate in RELEASE_GATE_STATEMENTS) == RELEASE_GATES
    assert set(RELEASE_GATES) <= set(NEVER_CUT) | {
        "clean_machine_reproduction",
        "positive_and_negative_controls",
        "unexplained_allowed",
        "provenance_complete",
        "two_engine_realistic_run",
    }


def test_execution_spec_and_bundle_round_trip() -> None:
    bundle = _bundle()
    restored = AuditBundleManifest.model_validate_json(bundle.model_dump_json())
    assert restored == bundle
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.case.execution.fill_timing is FillTiming.NEXT_BAR


def test_unexplained_rejects_false_certainty() -> None:
    with pytest.raises(ValidationError):
        Finding(
            category=AttributionCategory.UNEXPLAINED,
            confidence=Confidence.HIGH,
            engines=(EngineId.VECTORBT, EngineId.LEAN),
            evidence=(EvidenceItem(summary="not enough to classify"),),
        )


def test_unexplained_is_valid_with_no_divergence() -> None:
    finding = Finding(
        category=AttributionCategory.UNEXPLAINED,
        confidence=Confidence.NONE,
        engines=(EngineId.VECTORBT, EngineId.LEAN),
        evidence=(EvidenceItem(summary="conflicting fill and fee evidence"),),
    )
    assert finding.first_divergence is None


def test_lean_requires_image_digest() -> None:
    with pytest.raises(ValidationError):
        EngineRunMetadata(
            engine_id=EngineId.LEAN,
            engine_version="quantconnect/lean:18008",
            raw_output=(_file("raw.txt"),),
            ledger_files=_ledger_files(),
        )


def test_classified_finding_requires_first_divergence() -> None:
    with pytest.raises(ValidationError):
        Finding(
            category=AttributionCategory.FEE,
            confidence=Confidence.HIGH,
            engines=(EngineId.VECTORBT, EngineId.LEAN),
            evidence=(EvidenceItem(summary="fees differ"),),
        )


def test_bundle_requires_full_ledger() -> None:
    engine = _engine(EngineId.VECTORBT)
    incomplete = engine.model_copy(
        update={"ledger_files": {EventKind.FILL: _file("fills.parquet")}}
    )
    with pytest.raises(ValidationError):
        AuditBundleManifest(
            bundle_id="broken",
            created_at=datetime(2026, 8, 18, tzinfo=UTC),
            case=_bundle().case,
            inputs=_bundle().inputs,
            engines=(incomplete, _engine(EngineId.LEAN)),
            tolerance=_bundle().tolerance,
            findings=_bundle().findings,
        )


def test_claimed_categories_exclude_unexplained() -> None:
    assert AttributionCategory.UNEXPLAINED not in CLAIMED_CATEGORIES
    assert set(CLAIMED_CATEGORIES) | {AttributionCategory.UNEXPLAINED} == set(
        AttributionCategory
    )


def test_ledger_schemas_cover_every_event_kind() -> None:
    assert set(EVENT_SCHEMAS) == set(EventKind)
    assert set(LEDGER_FILE_NAMES) == set(EventKind)
    assert "engines/{engine_id}/raw/" in BUNDLE_LAYOUT.values()
    for kind in EventKind:
        frame = empty_frame(kind)
        validate_events(frame, kind)


def test_ledger_rejects_missing_columns() -> None:
    frame = empty_frame(EventKind.FILL).drop("price")
    with pytest.raises(ValueError, match="missing"):
        validate_events(frame, EventKind.FILL)
