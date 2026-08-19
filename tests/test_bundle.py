from __future__ import annotations

from pathlib import Path

from parity.audit import audit_case
from parity.bundle import read_bundle
from parity.cases import case_by_id
from parity.model import EventKind
from parity.scope import EngineId, NEVER_CUT


def test_bundle_contains_raw_ledger_manifest_and_policy(tmp_path: Path) -> None:
    case = case_by_id("fill-timing-next-vs-same")
    _, path = audit_case(case, tmp_path / "bundle")
    manifest, ledgers = read_bundle(path)
    assert (path / "manifest.json").exists()
    assert (path / "findings.json").exists()
    assert (path / "policy" / "tolerance.json").exists()
    assert (path / "inputs" / "checksums.json").exists()
    for engine_id in (EngineId.ORACLE, EngineId.ORACLE_MUTATED):
        assert (path / "engines" / engine_id.value / "raw" / "spec.json").exists()
        assert engine_id in ledgers
        assert ledgers[engine_id].frame(EventKind.FILL).height >= 1
    assert manifest.findings
    assert "provenance" in NEVER_CUT
