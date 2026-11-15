"""Credentials never reach logs, stored events, error text or tracked files."""

import json
import logging
import os
import re
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from app import security
from app.integrations import AIService
from app.integrations.claude import ClaudeReasoningProvider
from app.main import create_app
from scripts import set_advisor_password
from tests.conftest import PASSCODE

ROOT = Path(__file__).resolve().parents[2]
SECRET_KEY = "test-secret-key-for-the-test-suite-only-0123456789"
ANTHROPIC_KEY = "fake-anthropic-value-7f3a9c1e5b2d"          # not key-shaped: only exact-value redaction can catch it
SARVAM_KEY = "fake-sarvam-value-4d8e0b6a2c9f"
CTX = {"findings": [], "open_questions": 0}
SHAPED_KEY = "sk-" + "ant-api03-FAKE0123456789abcdef"        # key-shaped: pattern redaction


@pytest.fixture
def with_keys(db_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setenv("SARVAM_API_KEY", SARVAM_KEY)
    monkeypatch.setenv("LOANKART_AI_MODE", "live")


def no_secrets_in(text: str) -> None:
    for value in (PASSCODE, SECRET_KEY, ANTHROPIC_KEY, SARVAM_KEY, SHAPED_KEY):
        assert value not in text


# ---------------------------------------------------------------------------------------------- logs

def test_startup_and_sign_in_never_log_credentials(with_keys, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app()) as c:
        c.post("/api/auth/advisor/login", json={"password": "wrong-guess-123"})  # gitleaks:allow (dummy wrong guess)
        c.post("/api/auth/advisor/login", json={"password": PASSCODE})
        c.post("/api/auth/logout")
        c.post("/api/auth/advisor/login", json={"password": SECRET_KEY})        # a secret typed into the wrong box
    out = capsys.readouterr()
    no_secrets_in(caplog.text + out.out + out.err)
    for event in ("advisor sign-in failed", "advisor signed in", "advisor signed out"):
        assert event in caplog.text


def test_without_a_configured_passcode_none_is_generated_or_shown_and_sign_in_is_closed(db_path, monkeypatch, caplog, capsys):
    monkeypatch.setenv("LOANKART_ADVISOR_PASSWORD", "")
    caplog.set_level(logging.DEBUG)
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/api/auth/advisor/login", json={"password": "anything-at-all-1"})
        assert r.status_code == 401 and "set_advisor_password" in r.json()["detail"]
        assert not security.passcode_matches(app.state.settings, "")             # an empty guess must not match an unset passcode
        assert c.get("/api/auth/me").json()["advisor"] is False
    out = capsys.readouterr()
    assert "passcode for this run" not in caplog.text + out.out + out.err
    assert "set_advisor_password.py" in caplog.text


def test_log_records_are_scrubbed_of_secret_values_headers_and_cookies(db_path, caplog):
    create_app()                                                                 # registers this process's secrets
    caplog.set_level(logging.DEBUG)
    log = logging.getLogger("loankart.test")
    log.info("value %s and %s", SECRET_KEY, PASSCODE)
    log.info("Authorization: Bearer abcdef1234567890xyz and x-api-key: %s", SHAPED_KEY)
    log.info("Cookie: lk_adv=eyJhbGciOi.payload; lk_bor=other.value")
    log.info("headers={'Authorization': 'Bearer abcdef1234567890xyz'}")
    try:
        raise RuntimeError(f"provider said no to {SECRET_KEY}")
    except RuntimeError:
        log.exception("failure")
    text = caplog.text
    no_secrets_in(text)
    for fragment in ("abcdef1234567890xyz", "eyJhbGciOi", "other.value"):
        assert fragment not in text
    assert text.count("[redacted]") >= 6


def test_scrubbing_keeps_the_log_record_shape_uvicorn_formatters_need(db_path):
    from uvicorn.logging import AccessFormatter

    create_app()
    record = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:1", "GET", f"/x?token={SECRET_KEY}", "1.1", 200), None)
    line = AccessFormatter('%(levelprefix)s %(message)s').format(record)
    assert "200" in line and SECRET_KEY not in line


def test_unhandled_error_events_are_scrubbed(db_path, monkeypatch):
    app = create_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError(f"upstream echoed {SECRET_KEY}")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
        assert r.status_code == 500 and SECRET_KEY not in r.text
        c.post("/api/auth/advisor/login", json={"password": PASSCODE})
        events = c.get("/api/demo/logs")
        assert events.status_code == 200 and "Unhandled server error" in events.text
        assert SECRET_KEY not in events.text


# ---------------------------------------------------------------------------------------------- provider errors

def test_claude_error_responses_never_carry_the_api_key(with_keys):
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = {"type": "error", "error": {"type": "invalid_request_error", "message": f"bad request, key {ANTHROPIC_KEY} / {SHAPED_KEY}"}}
        return httpx2.Response(400, json=body)

    create_app()
    provider = ClaudeReasoningProvider(ANTHROPIC_KEY, "claude-opus-5-5")
    provider.client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    with pytest.raises(Exception) as caught:
        provider.generate("diagnosis_summary", CTX)
    no_secrets_in(str(caught.value))
    assert "Claude API error 400" in str(caught.value)


def test_sarvam_error_text_never_carries_the_api_key(with_keys):
    from app.integrations.base import ProviderError
    from app.integrations.sarvam import _Sarvam

    create_app()

    def failing(**_):
        raise RuntimeError(f"upstream: invalid subscription key {SARVAM_KEY}")

    with pytest.raises(ProviderError) as caught:
        _Sarvam.__new__(_Sarvam)._guard(failing)
    no_secrets_in(str(caught.value))


def test_provider_failures_are_scrubbed_in_stored_events_and_status(with_keys, client):
    from app import db
    from app.config import get_settings

    class Failing:
        name = "failing"

        def generate(self, *_):
            raise RuntimeError(f"HTTP 401 from provider, sent key {ANTHROPIC_KEY}")

        def ping(self):
            raise RuntimeError(f"HTTP 401 from provider, sent key {SARVAM_KEY}")

    conn = db.connect(get_settings().db_path)
    try:
        ai = AIService(get_settings(), conn)
        ai._claude = Failing
        ai._sarvam_chat = Failing
        result = ai.generate("diagnosis_summary", CTX)                                   # falls back to mock, never raises
        assert result["provider"] == "mock" and result["fallback"] is True
        rows = ai.status(check=True)
        no_secrets_in(str(rows))
        events = [dict(r) for r in conn.execute("SELECT * FROM events").fetchall()]
        no_secrets_in(str(events))
        assert any("AI provider failure" in str(e) for e in events)
    finally:
        conn.close()


# ---------------------------------------------------------------------------------------------- mock mode and files

def test_mock_mode_works_with_no_provider_credentials(client):
    assert client.get("/api/ai/status").status_code == 200
    from app import db
    from app.config import get_settings
    conn = db.connect(get_settings().db_path)
    try:
        for mode in ("mock", "live"):                                           # live without keys also degrades to mock
            ai = AIService(get_settings(), conn)
            ai.set_mode(mode)
            out = ai.generate("diagnosis_summary", CTX)
            assert out["provider"] == "mock" and out["headline"]
    finally:
        conn.close()


def test_env_example_holds_no_credential_values():
    pattern = re.compile(r"^[A-Za-z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|PASSCODE)[A-Za-z0-9_]*=(.*)$")
    checked = 0
    for line in (ROOT / "backend" / ".env.example").read_text().splitlines():
        m = pattern.match(line.strip())
        if m:
            checked += 1
            assert m.group(2).strip() == "", f"{line.split('=')[0]} must be empty in .env.example"
    assert checked >= 6


def test_no_provider_credentials_in_tracked_files_or_frontend_source():
    try:
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    shaped = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}|sk_[A-Za-z0-9]{24,}|Bearer\s+eyJ[A-Za-z0-9._-]{20,}")
    for name in files:
        path = ROOT / name
        if path.suffix in (".png", ".pdf", ".ico", ".json") and name.endswith("package-lock.json"):
            continue
        text = path.read_text(errors="ignore") if path.is_file() else ""
        assert not shaped.search(text), f"credential-shaped value in {name}"
        if name.startswith("frontend/src/"):
            assert not re.search(r"ANTHROPIC|SARVAM|PAYTM|LOANKART_SECRET", text), f"provider setting named in {name}"


# ---------------------------------------------------------------------------------------------- password set-up script

def run_script(monkeypatch, env_file, *answers):
    queue = iter(answers)
    monkeypatch.setattr(set_advisor_password.getpass, "getpass", lambda *_: next(queue))
    return set_advisor_password.main(["--env-file", str(env_file)])


def test_set_advisor_password_script_writes_owner_only_file_and_prints_no_credentials(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("# keep me\nANTHROPIC_API_KEY=\nLOANKART_ADVISOR_PASSWORD=old-old-old-old\n")
    new = "a-brand-new-passcode-42"
    assert run_script(monkeypatch, env, new, new) == 0
    out = capsys.readouterr()
    text = env.read_text()
    assert f"LOANKART_ADVISOR_PASSWORD={new}" in text and "old-old" not in text and text.startswith("# keep me\n")
    key = re.search(r"LOANKART_SECRET_KEY=(\S+)", text).group(1)
    assert len(key) >= 32
    assert new not in out.out + out.err and key not in out.out + out.err
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert run_script(monkeypatch, env, new + "x", new + "x") == 0              # an existing signing key is kept
    assert f"LOANKART_SECRET_KEY={key}" in env.read_text()


@pytest.mark.parametrize("answers", [("short", "short"), ("a-long-enough-passcode", "a-different-passcode!"),
                                     (" padded-passcode-here ", " padded-passcode-here "), ("'quoted-passcode-here'", "'quoted-passcode-here'")])
def test_set_advisor_password_script_rejects_weak_or_mismatched_entries(tmp_path, monkeypatch, answers):
    env = tmp_path / ".env"
    assert run_script(monkeypatch, env, *answers) == 1
    assert not env.exists()


# ---------------------------------------------------------------------------------------------- real server, odd inputs

def test_a_real_server_logs_auth_events_without_credentials(tmp_path):
    """Plain uvicorn, no test fixtures: the INFO auth events must actually appear, and no secret may."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    passcode = "throwaway-passcode-for-live-run"
    env = {**os.environ, "LOANKART_DB_PATH": str(tmp_path / "live.db"), "LOANKART_ADVISOR_PASSWORD": passcode,
           "LOANKART_SECRET_KEY": SECRET_KEY, "ANTHROPIC_API_KEY": "", "SARVAM_API_KEY": "", "PAYTM_ACCESS_TOKEN": "",
           "PAYTM_MERCHANT_KEY": "", "LOANKART_AI_MODE": "mock", "LOANKART_ENV": "development"}
    log_file = tmp_path / "server.log"
    with log_file.open("w") as out:
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT / "backend",
                                  env=env, stdout=out, stderr=subprocess.STDOUT)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    urllib.request.urlopen(f"{base}/health", timeout=1)
                    break
                except OSError:
                    time.sleep(0.1)

            def post(path, body):
                req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
                try:
                    return urllib.request.urlopen(req, timeout=5)
                except urllib.error.HTTPError as err:
                    return err

            post("/api/auth/advisor/login", {"password": "not-the-passcode-1"})
            ok = post("/api/auth/advisor/login", {"password": passcode})
            cookie = ok.headers["Set-Cookie"].split(";")[0]
            req = urllib.request.Request(base + "/api/auth/logout", b"", {"Cookie": cookie})
            urllib.request.urlopen(req, timeout=5)
        finally:
            server.terminate()
            server.wait(10)
    text = log_file.read_text()
    for event in ("advisor sign-in failed", "advisor signed in", "advisor signed out"):
        assert event in text
    assert passcode not in text and SECRET_KEY not in text and "lk_adv=" not in text and "Traceback" not in text


def test_non_string_messages_and_arguments_are_scrubbed_and_keep_their_type(db_path, caplog):
    create_app()
    caplog.set_level(logging.DEBUG)
    log = logging.getLogger("loankart.test")
    log.error(RuntimeError(f"raw exception object holding {SECRET_KEY}"))
    log.info("%s rejected after %d tries, ratio %.1f", RuntimeError(f"bad key {ANTHROPIC_KEY}"), 3, 0.5)
    assert SECRET_KEY not in caplog.text and ANTHROPIC_KEY not in caplog.text and "3 tries, ratio 0.5" in caplog.text


def test_every_stored_event_is_scrubbed_and_a_key_cut_by_truncation_cannot_survive(with_keys, client):
    from app import db
    from app.config import get_settings
    from app.integrations.base import ProviderError
    from app.integrations.sarvam import _Sarvam

    padded = "x" * (200 - len(SARVAM_KEY) // 2) + SARVAM_KEY             # the key straddles the 200-character cut

    def failing(**_):
        raise RuntimeError(padded)

    with pytest.raises(ProviderError) as caught:
        _Sarvam.__new__(_Sarvam)._guard(failing)
    assert SARVAM_KEY[:8] not in str(caught.value) and SARVAM_KEY[-8:] not in str(caught.value)
    conn = db.connect(get_settings().db_path)
    try:
        db.add_event(conn, "log", f"title {ANTHROPIC_KEY}", detail=f"detail {SECRET_KEY}", payload={"k": SARVAM_KEY})
        row = str([dict(r) for r in conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")])
        no_secrets_in(row)
    finally:
        conn.close()


def test_set_advisor_password_script_leaves_every_other_setting_untouched(tmp_path, monkeypatch, capsys):
    """Provider keys, comments, blank lines, quoting and order all survive; only the two LOANKART secrets change."""
    before = ["# my settings", "", "ANTHROPIC_API_KEY=fake-anthropic-value-aaaa", "SARVAM_API_KEY='fake sarvam value bbbb'",
              "PAYTM_CLIENT_ID=fake-paytm-id-cccc", "PAYTM_ACCESS_TOKEN=\"fake-paytm-token-dddd\"", "LOANKART_AI_MODE=live",
              "LOANKART_ADVISOR_PASSWORD=old-old-old-old", "# trailing comment", "LOANKART_CORS_ORIGINS=http://localhost:5173"]
    env = tmp_path / ".env"
    env.write_text("\n".join(before) + "\n")
    env.chmod(0o644)
    new = "another-fresh-passcode-77"
    assert run_script(monkeypatch, env, new, new) == 0
    after = env.read_text().splitlines()
    replaced = {"LOANKART_ADVISOR_PASSWORD=old-old-old-old": f"LOANKART_ADVISOR_PASSWORD={new}"}
    assert after[:len(before)] == [replaced.get(line, line) for line in before]       # same lines, same order, in place
    assert len(after) == len(before) + 1 and after[-1].startswith("LOANKART_SECRET_KEY=")  # only the missing key is appended
    assert stat.S_IMODE(env.stat().st_mode) == 0o600 and not list(tmp_path.glob(".env.tmp-*"))
    out = capsys.readouterr()
    assert "fake-" not in out.out + out.err and new not in out.out + out.err
