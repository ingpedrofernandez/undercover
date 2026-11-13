import pytest
from fastapi.testclient import TestClient
from langfuse import Langfuse, get_client
from langgraph.checkpoint.memory import InMemorySaver
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from agent import api, harness
from backend.main import app
from backend.tests.conftest import client, database, resumed

__all__ = ["client", "database", "resumed"]


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
    get_client().flush()
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
def checkpointer(monkeypatch):
    """Save the claim graph's steps in memory, in one saver for the whole test.

    A restart is a new graph on the same saver.
    """
    saver = InMemorySaver()
    monkeypatch.setattr(harness, "checkpointer", lambda: saver)
    return saver


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Retry failed model calls at once, so the tests stay fast."""
    monkeypatch.setattr(harness, "RETRY_DELAY_SECONDS", 0)
