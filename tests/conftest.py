"""Suite-wide fixtures.

The gate mode is read from the environment (tools/maestro_cli/gates.py), and a session
that runs this suite may itself run under MAESTRO_GATES=warn. Every test starts in the
default, blocking mode; a test of warn mode sets it explicitly.
"""
import pytest


@pytest.fixture(autouse=True)
def _gates_block_by_default(monkeypatch):
    monkeypatch.delenv("MAESTRO_GATES", raising=False)
