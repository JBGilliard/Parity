from __future__ import annotations

from typer.testing import CliRunner

from parity.cli import app
from parity.scope import CLAIM

runner = CliRunner()


def test_claim_command_prints_frozen_claim() -> None:
    result = runner.invoke(app, ["claim"])
    assert result.exit_code == 0
    assert CLAIM in result.stdout


def test_cases_command_lists_unexplained_rebalance() -> None:
    result = runner.invoke(app, ["cases"])
    assert result.exit_code == 0
    assert "rebalance-ordering" in result.stdout
    assert "unexplained" in result.stdout
