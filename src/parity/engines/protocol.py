from __future__ import annotations

from dataclasses import dataclass

from parity.ledger import Ledger
from parity.scope import EngineId


class EngineNotInstalled(RuntimeError):
    pass


@dataclass(frozen=True)
class Capability:
    event: str
    status: str  # native | reconstructed | unavailable | gap
    notes: str


@dataclass(frozen=True)
class EngineRun:
    engine_id: EngineId
    ledger: Ledger
    raw_files: dict[str, bytes]
    parameters: dict[str, object]
    capabilities: tuple[Capability, ...]
