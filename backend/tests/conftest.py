import pytest
from fastapi.testclient import TestClient

from backend import agent_client
from backend.main import app
from backend.seed import seed


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    """Give every test its own freshly seeded database."""
    path = tmp_path / "undercover.db"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("UNDERCOVER_DB", str(path))
    seed()
    return path


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def resumed(monkeypatch):
    """Record the claims the backend asks the agent's service to resume."""
    claims = []
    monkeypatch.setattr(agent_client, "resume_claim", claims.append)
    return claims
