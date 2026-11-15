import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PASSCODE = "test-advisor-passcode"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("LOANKART_DB_PATH", str(path))        # files are stored next to it, so tests stay in tmp_path
    monkeypatch.setenv("LOANKART_AI_MODE", "mock")
    monkeypatch.setenv("LOANKART_DEMO_PACING_MS", "0")
    monkeypatch.setenv("LOANKART_ENV", "development")
    monkeypatch.setenv("LOANKART_SECRET_KEY", "test-secret-key-for-the-test-suite-only-0123456789")
    monkeypatch.setenv("LOANKART_ADVISOR_PASSWORD", PASSCODE)
    for key in ("ANTHROPIC_API_KEY", "SARVAM_API_KEY"):      # a developer's real keys must never be used by tests
        monkeypatch.setenv(key, "")
    return path


@pytest.fixture
def client(db_path):
    """Signed in as an advisor, who may use every route. Borrower-only and anonymous behaviour is in test_security.py."""
    with TestClient(create_app()) as c:  # `with` runs lifespan: init db + seed demo
        assert c.post("/api/auth/advisor/login", json={"password": PASSCODE}).status_code == 200
        yield c


@pytest.fixture
def anon(db_path):
    """A browser with no session at all."""
    with TestClient(create_app()) as c:
        yield c
