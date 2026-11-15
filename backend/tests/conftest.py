import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("LOANKART_DB_PATH", str(path))        # files are stored next to it, so tests stay in tmp_path
    monkeypatch.setenv("LOANKART_AI_MODE", "mock")
    monkeypatch.setenv("LOANKART_DEMO_PACING_MS", "0")
    for key in ("ANTHROPIC_API_KEY", "SARVAM_API_KEY"):      # a developer's real keys must never be used by tests
        monkeypatch.setenv(key, "")
    return path


@pytest.fixture
def client(db_path):
    with TestClient(create_app()) as c:  # `with` runs lifespan: init db + seed demo
        yield c
