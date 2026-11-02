import pytest
from fastapi.testclient import TestClient
from langfuse import Langfuse, get_client
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from agent import api, harness
from backend.main import app
from backend.tests.conftest import client, database

__all__ = ["client", "database"]


@pytest.fixture(scope="session", autouse=True)
def traces():
    """Keep the agent's Langfuse traces in memory, so the tests never send them."""
    exporter = InMemorySpanExporter()
    with pytest.MonkeyPatch.context() as env:
        env.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        env.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        Langfuse(span_exporter=exporter)
        yield exporter


@pytest.fixture
def spans(traces):
    """Return a function giving the spans traced during the test."""
    traces.clear()

    def traced():
        get_client().flush()
        return traces.get_finished_spans()

    return traced


@pytest.fixture(autouse=True)
def backend(monkeypatch):
    """Send the agent's requests to the test backend."""
    monkeypatch.setattr(api, "client", lambda: TestClient(app))


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Retry failed model calls at once, so the tests stay fast."""
    monkeypatch.setattr(harness, "RETRY_DELAY_SECONDS", 0)
