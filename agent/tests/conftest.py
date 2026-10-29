import pytest
from fastapi.testclient import TestClient

from agent import api, harness
from backend.main import app
from backend.tests.conftest import client, database

__all__ = ["client", "database"]


@pytest.fixture(autouse=True)
def backend(monkeypatch):
    """Send the agent's requests to the test backend."""
    monkeypatch.setattr(api, "client", lambda: TestClient(app))


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Retry failed model calls at once, so the tests stay fast."""
    monkeypatch.setattr(harness, "RETRY_DELAY_SECONDS", 0)
