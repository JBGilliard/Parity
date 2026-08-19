"""Frozen claim, engine scope, license pins, and release gates.

Calendar can slip. These cannot.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


CLAIM = (
    "Given immutable inputs and an explicit execution specification, Parity "
    "finds the first causal divergence between backtests, classifies it when "
    "evidence supports the classification, and emits a reproducible audit bundle."
)

SCHEMA_VERSION = "0.1.0"  # bundle/contract version, not the PyPI number

# bump PINNED_AS_OF when any pin below moves; don't edit pins silently
PINNED_AS_OF = "2026-08-18"


class EngineId(StrEnum):
    VECTORBT = "vectorbt"
    LEAN = "lean"
    BACKTRADER = "backtrader"
    NAUTILUS = "nautilustrader"
    ORACLE = "oracle"
    ORACLE_MUTATED = "oracle_mutated"


PRIMARY_ENGINES = (EngineId.VECTORBT, EngineId.LEAN)
THIRD_TARGET = EngineId.BACKTRADER
STRETCH_ENGINE = EngineId.NAUTILUS
SPEC_INTERPRETERS = (EngineId.ORACLE, EngineId.ORACLE_MUTATED)


class EnginePin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine_id: EngineId
    role: str
    version: str
    license: str
    constraint: str
    image_digest: str | None = None


ENGINE_PINS: dict[EngineId, EnginePin] = {
    EngineId.VECTORBT: EnginePin(
        engine_id=EngineId.VECTORBT,
        role="primary",
        version="1.1.0",
        license="Apache-2.0 WITH Commons-Clause",
        constraint="optional extra only; do not redistribute or sell vectorbt",
    ),
    EngineId.LEAN: EnginePin(
        engine_id=EngineId.LEAN,
        role="primary",
        version="quantconnect/lean:18008",
        license="Apache-2.0",
        constraint="run inside the official Docker image; record digest on every run",
        image_digest="sha256:0e497f4248d57b2a1a4625f4eea2203ee94ab409cdd3ff8ef898242512c127c6",
    ),
    EngineId.BACKTRADER: EnginePin(
        engine_id=EngineId.BACKTRADER,
        role="third_target",
        version="1.9.78.123",
        license="GPL-3.0-or-later",
        constraint="optional extra only; GPL code does not enter the core tree",
    ),
    EngineId.NAUTILUS: EnginePin(
        engine_id=EngineId.NAUTILUS,
        role="stretch",
        version="1.231.0",
        license="LGPL-3.0-or-later",
        constraint="optional extra only; add only if Backtrader does not threaten report quality",
    ),
    EngineId.ORACLE: EnginePin(
        engine_id=EngineId.ORACLE,
        role="spec_interpreter",
        version=SCHEMA_VERSION,
        license="Apache-2.0",
        constraint="not a backtester; golden-corpus interpreter only",
    ),
    EngineId.ORACLE_MUTATED: EnginePin(
        engine_id=EngineId.ORACLE_MUTATED,
        role="spec_interpreter",
        version=SCHEMA_VERSION,
        license="Apache-2.0",
        constraint="not a backtester; single-variable mutant of the spec interpreter",
    ),
}

DATA_CONSTRAINTS = (
    "Never redistribute vendor data.",
    "Pin a sha256 for every input file in the bundle.",
    "Databento samples stay local; publish hashes and synthetic bundles only.",
)

# cut in this order when the calendar slips. don't reorder without revisiting the claim.
SCOPE_CUT_ORDER = (
    "nautilustrader_adapter",
    "backtrader_adapter",
    "minute_data_experiment",
    "mean_reversion_showcase",
    "lower_priority_attribution_categories",
)

NEVER_CUT = (
    "immutable_inputs",
    "raw_output_retention",
    "provenance",
    "explicit_tolerances",
    "unexplained",
    "negative_controls",
    "independent_reproduction",
)

RELEASE_GATES = (
    "clean_machine_reproduction",
    "positive_and_negative_controls",
    "unexplained_allowed",
    "provenance_complete",
    "two_engine_realistic_run",
    "independent_reproduction",
)

OUT_OF_V01 = (
    "strategy_dsl",
    "new_backtester",
    "cross_vendor_reconciliation",
    "hosted_service",
    "guessed_attribution",
    "ai_classifier",
    "promised_pro_features",
)

BUNDLE_LAYOUT = {
    "manifest": "manifest.json",
    "case": "inputs/case.json",
    "input_data": "inputs/data/",
    "checksums": "inputs/checksums.json",
    "engine_raw": "engines/{engine_id}/raw/",
    "engine_ledger": "engines/{engine_id}/ledger/",
    "engine_meta": "engines/{engine_id}/engine.json",
    "tolerance": "policy/tolerance.json",
    "findings": "findings.json",
}


class ReleaseGate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str
    required: bool = True
    statement: str


RELEASE_GATE_STATEMENTS: tuple[ReleaseGate, ...] = (
    ReleaseGate(
        gate_id="clean_machine_reproduction",
        statement="A clean machine reproduces the same normalized ledgers and findings from one documented command.",
    ),
    ReleaseGate(
        gate_id="positive_and_negative_controls",
        statement="Every claimed attribution category has a deliberate positive case and a nearby negative control.",
    ),
    ReleaseGate(
        gate_id="unexplained_allowed",
        statement="Unknown causes stay unexplained; the golden corpus contains no false certainty.",
    ),
    ReleaseGate(
        gate_id="provenance_complete",
        statement="Every bundle includes raw output, normalized output, config, versions, checksums, and the tolerance policy.",
    ),
    ReleaseGate(
        gate_id="two_engine_realistic_run",
        statement="vectorbt and LEAN complete the realistic strategy run.",
    ),
    ReleaseGate(
        gate_id="independent_reproduction",
        statement="One person other than the author reproduces a published case.",
    ),
)
