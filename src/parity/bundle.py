from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from parity.hashutil import sha256_file
from parity.ledger import LEDGER_FILE_NAMES, Ledger
from parity.model import (
    AuditBundleManifest,
    CaseSpec,
    EngineRunMetadata,
    EventKind,
    FileRef,
    Finding,
    InputManifest,
    TolerancePolicy,
)
from parity.scope import BUNDLE_LAYOUT, SCHEMA_VERSION, EngineId, ENGINE_PINS


def write_engine_tree(
    bundle_dir: Path,
    engine_id: EngineId,
    ledger: Ledger,
    raw_files: dict[str, bytes],
    parameters: dict[str, object] | None = None,
    python_version: str | None = None,
) -> EngineRunMetadata:
    pin = ENGINE_PINS[engine_id]
    raw_dir = bundle_dir / "engines" / engine_id.value / "raw"
    ledger_dir = bundle_dir / "engines" / engine_id.value / "ledger"
    raw_dir.mkdir(parents=True, exist_ok=True)
    written = ledger.write(ledger_dir)
    raw_refs: list[FileRef] = []
    for name, payload in raw_files.items():
        path = raw_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        rel = path.relative_to(bundle_dir).as_posix()
        raw_refs.append(FileRef(path=rel, sha256=sha256_file(path)))
    ledger_refs = {
        kind: FileRef(
            path=path.relative_to(bundle_dir).as_posix(),
            sha256=sha256_file(path),
        )
        for kind, path in written.items()
    }
    meta = EngineRunMetadata(
        engine_id=engine_id,
        engine_version=pin.version,
        image_digest=pin.image_digest,
        python_version=python_version,
        parameters=parameters or {},
        raw_output=tuple(raw_refs),
        ledger_files=ledger_refs,
    )
    engine_json = bundle_dir / "engines" / engine_id.value / "engine.json"
    engine_json.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return meta


def write_inputs(bundle_dir: Path, case: CaseSpec, data_files: Iterable[Path]) -> InputManifest:
    data_dir = bundle_dir / "inputs" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    refs: list[FileRef] = []
    checksums: dict[str, str] = {}
    for src in data_files:
        dest = data_dir / src.name
        dest.write_bytes(src.read_bytes())
        digest = sha256_file(dest)
        rel = dest.relative_to(bundle_dir).as_posix()
        refs.append(FileRef(path=rel, sha256=digest))
        checksums[rel] = digest
    (bundle_dir / "inputs" / "case.json").write_text(
        case.model_dump_json(indent=2), encoding="utf-8"
    )
    (bundle_dir / "inputs" / "checksums.json").write_text(
        json.dumps(checksums, indent=2, sort_keys=True), encoding="utf-8"
    )
    return InputManifest(
        schema_version=SCHEMA_VERSION,
        data_files=tuple(refs),
        timezone=case.execution.session.timezone,
        calendar=case.execution.session.calendar,
        adjustment=case.execution.adjustment,
        parameters={"case_id": case.case_id},
    )


def write_bundle(
    bundle_dir: Path,
    *,
    bundle_id: str,
    case: CaseSpec,
    inputs: InputManifest,
    engines: tuple[EngineRunMetadata, ...],
    tolerance: TolerancePolicy,
    findings: tuple[Finding, ...],
) -> AuditBundleManifest:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "policy").mkdir(exist_ok=True)
    (bundle_dir / "policy" / "tolerance.json").write_text(
        tolerance.model_dump_json(indent=2), encoding="utf-8"
    )
    manifest = AuditBundleManifest(
        schema_version=SCHEMA_VERSION,
        bundle_id=bundle_id,
        created_at=datetime.now(tz=UTC),
        case=case,
        inputs=inputs,
        engines=engines,
        tolerance=tolerance,
        findings=findings,
    )
    (bundle_dir / "manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    (bundle_dir / "findings.json").write_text(
        json.dumps(
            [json.loads(item.model_dump_json()) for item in findings],
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


def read_bundle(bundle_dir: Path) -> tuple[AuditBundleManifest, dict[EngineId, Ledger]]:
    manifest = AuditBundleManifest.model_validate_json(
        (bundle_dir / "manifest.json").read_text(encoding="utf-8")
    )
    verify_bundle(bundle_dir, manifest)
    ledgers = {
        run.engine_id: Ledger.read(bundle_dir / "engines" / run.engine_id.value / "ledger")
        for run in manifest.engines
    }
    return manifest, ledgers


def verify_bundle(bundle_dir: Path, manifest: AuditBundleManifest) -> None:
    for ref in manifest.inputs.data_files:
        _check(bundle_dir, ref)
    for run in manifest.engines:
        for ref in run.raw_output:
            _check(bundle_dir, ref)
        for kind in EventKind:
            _check(bundle_dir, run.ledger_files[kind])
            expected = LEDGER_FILE_NAMES[kind]
            if not run.ledger_files[kind].path.endswith(expected):
                raise ValueError(f"{run.engine_id} ledger file for {kind} is not {expected}")
    required = (
        BUNDLE_LAYOUT["manifest"],
        BUNDLE_LAYOUT["case"],
        BUNDLE_LAYOUT["checksums"],
        BUNDLE_LAYOUT["tolerance"],
        BUNDLE_LAYOUT["findings"],
    )
    for rel in required:
        if not (bundle_dir / rel).exists():
            raise FileNotFoundError(bundle_dir / rel)


def _check(bundle_dir: Path, ref: FileRef) -> None:
    path = bundle_dir / ref.path
    if not path.exists():
        raise FileNotFoundError(path)
    digest = sha256_file(path)
    if digest != ref.sha256:
        raise ValueError(f"checksum mismatch for {ref.path}")
