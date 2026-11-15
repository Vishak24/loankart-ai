"""Authentication, authorisation, rate limiting, upload hardening and production-mode restrictions."""

import io
import re

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app import environment, extraction, security
from app.main import create_app
from tests.conftest import PASSCODE
from tests.test_api import VALID
from tests.test_journey import CASE, ok

SECRET = "test-secret-key-for-the-test-suite-only-0123456789"
PROD_PASSCODE = "a-long-production-passcode"
PROD_ORIGIN = "https://loankart.example"

# The only routes an anonymous browser may call. Everything else must answer 401.
PUBLIC = {("GET", "/health"), ("GET", "/api/auth/me"), ("POST", "/api/auth/logout"), ("POST", "/api/auth/advisor/login"),
          ("POST", "/api/borrowers"), ("GET", "/api/demo/borrower"), ("POST", "/api/demo/load"),
          ("POST", "/api/calculations/emi"), ("GET", "/api/lenders")}


def pdf(pages: int = 1, extra: bytes = b"") -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for n in range(pages):
        c.drawString(72, 720, f"page {n}")
        c.showPage()
    c.save()
    data = buf.getvalue()
    return data.replace(b"%%EOF", extra + b"\n%%EOF") if extra else data


def borrower_browser(app_client: TestClient) -> tuple[str, str]:
    """Create a borrower and open its case; the client's cookie jar now holds that borrower's session."""
    b = ok(app_client.post("/api/borrowers", json=VALID), 201)
    return b["id"], ok(app_client.post("/api/cases", json={"borrower_id": b["id"], "intent": "new"}))["id"]


@pytest.fixture
def second(db_path, anon):
    """A second, unrelated browser talking to the same server."""
    return TestClient(anon.app)


# ---------------------------------------------------------------------------------------------- authentication

def test_every_route_requires_a_session_unless_it_is_on_the_public_list(anon):
    checked = 0
    for path, methods in anon.app.openapi()["paths"].items():
        for method in methods:
            if (method.upper(), path) in PUBLIC:
                continue
            r = anon.request(method.upper(), re.sub(r"\{[^}]+\}", "x", path))
            assert r.status_code == 401, f"{method.upper()} {path} answered {r.status_code} to an anonymous request"
            checked += 1
    assert checked > 40            # the walk really covered the API, not an empty table


def test_the_old_role_header_grants_nothing(anon):
    for role in ("advisor", "demo"):
        assert anon.get("/api/advisor/cases", headers={"X-LoanKart-Role": role}).status_code == 401
        assert anon.post("/api/demo/reset", headers={"X-LoanKart-Role": role}).status_code == 401


def test_advisor_sign_in_and_sign_out(anon):
    wrong = anon.post("/api/auth/advisor/login", json={"password": "not-the-passcode"})
    assert wrong.status_code == 401 and "set-cookie" not in wrong.headers
    assert anon.get("/api/advisor/cases").status_code == 401
    good = anon.post("/api/auth/advisor/login", json={"password": PASSCODE})
    assert good.status_code == 200 and good.json()["advisor"] is True
    cookie = good.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert anon.get("/api/advisor/cases").status_code == 200
    assert anon.get("/api/auth/me").json()["advisor"] is True
    assert anon.post("/api/auth/logout").json()["advisor"] is False
    assert anon.get("/api/advisor/cases").status_code == 401


def test_forged_expired_and_tampered_sessions_are_refused(anon):
    anon.cookies.set("lk_adv", security.sign(SECRET, {"r": "advisor"}, 1))
    assert anon.get("/api/advisor/cases").status_code == 200                       # the signing mechanism itself works
    for name, token in (("expired", security.sign(SECRET, {"r": "advisor"}, -1)),
                        ("wrong key", security.sign("some-other-secret-entirely-0123456789ab", {"r": "advisor"}, 1)),
                        ("tampered", security.sign(SECRET, {"r": "advisor"}, 1)[:-3] + "AAA"),
                        ("no signature", "eyJyIjoiYWR2aXNvciJ9"), ("garbage", "!!!")):
        anon.cookies.clear()
        anon.cookies.set("lk_adv", token)
        assert anon.get("/api/advisor/cases").status_code == 401, name


def test_a_forged_borrower_grant_is_refused(anon, second):
    _, case_id = borrower_browser(second)
    anon.cookies.set("lk_bor", security.sign("wrong-secret-wrong-secret-wrong-secret-12", {"b": ["anything"]}, 1))
    assert anon.get(f"/api/cases/{case_id}").status_code == 401


# ---------------------------------------------------------------------------------------------- authorisation

def test_borrowers_can_only_reach_their_own_case_documents_and_profile(anon, second, client):
    a_id, a_case = borrower_browser(anon)
    ok(anon.post(f"/api/cases/{a_case}/documents/synthetic"))
    doc_url = ok(anon.get(f"/api/cases/{a_case}/documents"))[0]["url"]
    b_id, b_case = borrower_browser(second)
    assert anon.get(f"/api/borrowers/{a_id}").status_code == 200 and anon.get(doc_url).status_code == 200
    for r in (second.get(f"/api/cases/{a_case}"), second.get(f"/api/cases/{a_case}/investigation"), second.get(doc_url),
              second.get(f"/api/borrowers/{a_id}"), second.put(f"/api/borrowers/{a_id}", json=VALID),
              second.post(f"/api/cases/{a_case}/consents", json={"key": "analyse_documents", "granted": True}),
              second.post("/api/cases", json={"borrower_id": a_id, "intent": "new"})):
        assert r.status_code == 403, r.request.url
    # a case that does not exist looks exactly like one that is not yours: IDs cannot be probed
    assert second.get("/api/cases/case-does-not-exist").status_code == second.get(f"/api/cases/{a_case}").status_code == 403
    assert second.get(f"/api/cases/{b_case}").status_code == 200
    assert client.get(f"/api/cases/{a_case}").status_code == 200 and client.get(f"/api/borrowers/{b_id}").status_code == 200


def test_borrowers_cannot_use_advisor_or_demo_control_routes(anon):
    borrower_browser(anon)
    for method, path in (("GET", "/api/advisor/cases"), ("GET", f"/api/advisor/cases/{CASE}"), ("GET", "/api/knowledge"),
                         ("POST", "/api/demo/reset"), ("GET", "/api/demo/logs"), ("GET", "/api/demo/state"),
                         ("POST", "/api/ai/check"), ("PUT", "/api/ai/mode"), ("GET", f"/api/demo/ground-truth/{CASE}"),
                         ("POST", f"/api/demo/regenerate-documents/{CASE}")):
        assert anon.request(method, path).status_code == 401, path
    assert anon.post("/api/demo/load", json={"scenario_id": "kirana_store"}).status_code in (401, 422)


def test_a_borrower_session_alone_can_complete_the_journey(anon):
    _, case_id = borrower_browser(anon)
    ok(anon.post(f"/api/cases/{case_id}/documents/synthetic"))
    ok(anon.post(f"/api/cases/{case_id}/consents", json={"key": "analyse_documents", "granted": True}))
    ok(anon.post(f"/api/cases/{case_id}/investigation/run"), 202)
    assert ok(anon.get(f"/api/cases/{case_id}/investigation"))["status"] == "complete"
    ok(anon.get(f"/api/cases/{case_id}/restructure"))
    ok(anon.get(f"/api/cases/{case_id}/recommendations"))
    ok(anon.post(f"/api/cases/{case_id}/investigation/explain"))
    ok(anon.post("/api/ai/translate", json={"text": "hello", "target_language": "ta-IN"}))
    assert anon.get("/api/ai/status").status_code == 200


def test_the_shared_demo_case_is_open_to_visitors_in_development(anon):
    case = ok(anon.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
    assert case["id"] == CASE and anon.get(f"/api/cases/{CASE}/documents").status_code == 200
    assert anon.post("/api/demo/reset").status_code == 401           # but never the controls


# ---------------------------------------------------------------------------------------------- rate limiting

def test_advisor_sign_in_is_rate_limited(db_path, monkeypatch):
    monkeypatch.setenv("LOANKART_RATE_LOGIN", "3")
    with TestClient(create_app()) as c:
        codes = [c.post("/api/auth/advisor/login", json={"password": f"guess-{i}"}).status_code for i in range(5)]
        assert codes == [401, 401, 401, 429, 429]
        blocked = c.post("/api/auth/advisor/login", json={"password": PASSCODE})
        assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) >= 1     # even the right one waits


def test_a_client_cannot_dodge_the_limit_with_a_forged_forwarding_header(db_path, monkeypatch):
    monkeypatch.setenv("LOANKART_RATE_LOGIN", "2")
    with TestClient(create_app()) as c:
        codes = [c.post("/api/auth/advisor/login", json={"password": "x"}, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
                 for i in range(4)]
        assert codes == [401, 401, 429, 429]


def test_behind_a_trusted_proxy_the_proxy_appended_address_is_used(db_path, monkeypatch):
    monkeypatch.setenv("LOANKART_RATE_LOGIN", "1")
    monkeypatch.setenv("LOANKART_TRUST_PROXY", "1")
    with TestClient(create_app()) as c:
        first = c.post("/api/auth/advisor/login", json={"password": "x"}, headers={"X-Forwarded-For": "6.6.6.6, 10.0.0.1"})
        other = c.post("/api/auth/advisor/login", json={"password": "x"}, headers={"X-Forwarded-For": "6.6.6.6, 10.0.0.2"})
        again = c.post("/api/auth/advisor/login", json={"password": "x"}, headers={"X-Forwarded-For": "1.1.1.1, 10.0.0.1"})
        assert (first.status_code, other.status_code, again.status_code) == (401, 401, 429)


def test_ai_endpoints_have_a_per_client_and_a_daily_ceiling(db_path, monkeypatch):
    monkeypatch.setenv("LOANKART_RATE_AI", "2")
    monkeypatch.setenv("LOANKART_RATE_AI_DAILY", "3")
    translate = {"text": "hello", "target_language": "ta-IN"}
    with TestClient(create_app()) as a, TestClient(create_app()) as unused:
        ok(a.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
        assert [a.post("/api/ai/translate", json=translate).status_code for _ in range(3)] == [200, 200, 429]
        assert a.post("/api/ai/translate", json=translate).headers["retry-after"]
    monkeypatch.setenv("LOANKART_RATE_AI", "100")
    with TestClient(create_app()) as b:
        ok(b.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
        assert [b.post("/api/ai/translate", json=translate).status_code for _ in range(4)] == [200, 200, 200, 429]   # daily cap


def test_every_provider_spending_route_is_limited(db_path, monkeypatch):
    monkeypatch.setenv("LOANKART_RATE_AI", "1")
    with TestClient(create_app()) as c:
        assert c.post("/api/auth/advisor/login", json={"password": PASSCODE}).status_code == 200
        ok(c.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
        spending = [("POST", f"/api/cases/{CASE}/investigation/explain"), ("POST", f"/api/cases/{CASE}/recommendations/explain"),
                    ("POST", "/api/ai/check"), ("POST", "/api/ai/translate"), ("POST", "/api/ai/speak"),
                    ("POST", f"/api/cases/{CASE}/escalate"), ("POST", "/api/knowledge"),
                    ("POST", f"/api/cases/{CASE}/application/queries/q1/draft"), ("POST", f"/api/cases/{CASE}/investigation/run")]
        for method, path in spending:
            c.app.state.limiter = security.RateLimiter()        # fresh window for each route
            c.request(method, path, json={})
            assert c.request(method, path, json={}).status_code == 429, path


def test_uploads_and_profile_creation_are_rate_limited(db_path, monkeypatch):
    monkeypatch.setenv("LOANKART_RATE_UPLOAD", "1")
    monkeypatch.setenv("LOANKART_RATE_CREATE", "2")
    with TestClient(create_app()) as c:
        codes = [c.post("/api/borrowers", json=VALID).status_code for _ in range(3)]
        assert codes == [201, 201, 429]
        ok(c.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
        first = upload(c, pdf(), "a.pdf")
        second_try = upload(c, pdf(), "b.pdf")
        assert (first.status_code, second_try.status_code) == (201, 429)


def test_a_general_ceiling_applies_to_all_api_routes(db_path, monkeypatch):
    monkeypatch.setenv("LOANKART_RATE_DEFAULT", "3")
    with TestClient(create_app()) as c:
        assert [c.get("/api/auth/me").status_code for _ in range(5)] == [200, 200, 200, 429, 429]
        assert c.get("/health").status_code == 200                      # health checks are never throttled


# ---------------------------------------------------------------------------------------------- uploads and request limits

def upload(c, data, name="doc.pdf"):
    return c.post(f"/api/cases/{CASE}/documents", files={"file": (name, data, "application/pdf")})


def stored_uploads(db_path):
    folder = db_path.parent / "files" / "uploads" / CASE
    return list(folder.iterdir()) if folder.exists() else []


def test_a_clean_pdf_is_accepted_and_hostile_ones_are_refused_and_not_kept(client, db_path):
    ok(client.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
    assert upload(client, pdf()).status_code == 201
    kept = len(stored_uploads(db_path))
    for name, data in (("truncated", pdf()[:-20]), ("javascript", pdf(extra=b"/S /JavaScript /JS (app.alert(1))")),
                       ("launch", pdf(extra=b"/Launch")), ("attachment", pdf(extra=b"/EmbeddedFile")),
                       ("encrypted", pdf(extra=b"/Encrypt 9 0 R")), ("empty", b""), ("not a pdf", b"MZ" + b"0" * 500),
                       ("too many pages", pdf(pages=extraction.MAX_PDF_PAGES + 1))):
        r = upload(client, data)
        assert r.status_code == 422, name
        assert len(stored_uploads(db_path)) == kept, f"{name}: a refused file was left on disk"


def test_a_bare_js_byte_pattern_in_scan_data_is_not_mistaken_for_a_script(client):
    """Compressed image streams contain "/JS" by chance about once per 15 MB; only a real "/S /JavaScript" action counts."""
    ok(client.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
    assert upload(client, pdf(extra=b"/Junk (\x00/JS \x01/JS)\x02")).status_code == 201
    assert upload(client, pdf(extra=b"/S /JavaScript /JS (app.alert(1))")).status_code == 422


def test_parsing_is_time_limited_and_a_timeout_removes_the_file(client, db_path, monkeypatch):
    ok(client.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
    monkeypatch.setattr(extraction, "WORKER_TIMEOUT_S", 0.01)
    r = upload(client, pdf())
    assert r.status_code == 422 and "too long" in r.json()["detail"] and not stored_uploads(db_path)


def test_a_case_can_only_hold_so_many_uploads(client, monkeypatch):
    ok(client.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}))
    monkeypatch.setattr(environment, "MAX_UPLOADS_PER_CASE", 1)
    assert (upload(client, pdf()).status_code, upload(client, pdf()).status_code) == (201, 422)


def test_oversized_and_unframed_bodies_are_refused_before_parsing(client, anon):
    big_json = b"{" + b" " * (1024 * 1024 + 1) + b"}"
    assert client.post("/api/calculations/emi", content=big_json, headers={"content-type": "application/json"}).status_code == 413
    huge = b"%PDF-" + b"0" * (environment.MAX_UPLOAD_BYTES + 300 * 1024)
    assert upload(client, huge).status_code == 413
    assert client.post("/api/calculations/emi", content=(b"{}" for _ in range(1)),
                       headers={"content-type": "application/json"}).status_code == 411       # chunked would dodge the cap
    assert upload(anon, b"%PDF-" + b"0" * 200_000).status_code == 401                          # no session: refused unread


def test_cross_site_writes_are_refused(client):
    body = {"principal": 100000, "annual_rate_pct": 12, "months": 12}
    assert client.post("/api/calculations/emi", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/calculations/emi", json=body, headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert client.post("/api/calculations/emi", json=body).status_code == 200                     # non-browser clients send none


def test_cors_allows_listed_origins_with_credentials_and_no_role_header(anon):
    ok_pre = anon.options("/api/cases", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                                 "Access-Control-Request-Headers": "content-type"})
    assert ok_pre.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert ok_pre.headers["access-control-allow-credentials"] == "true"
    evil = anon.options("/api/cases", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in evil.headers
    role = anon.options("/api/cases", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                               "Access-Control-Request-Headers": "x-loankart-role"})
    assert role.status_code == 400


def test_security_headers_and_generic_server_errors(db_path, monkeypatch):
    def boom(*_):
        raise RuntimeError("internal-detail-that-must-not-leak")
    monkeypatch.setattr("app.routes.advisors.queue", boom)
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        c.post("/api/auth/advisor/login", json={"password": PASSCODE})
        r = c.get("/api/advisor/cases")
        assert r.status_code == 500 and "internal-detail" not in r.text and "RuntimeError" not in r.text
        h = c.get("/api/auth/me").headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in h["content-security-policy"]


# ---------------------------------------------------------------------------------------------- production mode

@pytest.fixture
def prod_env(db_path, monkeypatch):
    for key, value in (("LOANKART_ENV", "production"), ("LOANKART_SECRET_KEY", "p" * 48),
                       ("LOANKART_ADVISOR_PASSWORD", PROD_PASSCODE), ("LOANKART_CORS_ORIGINS", PROD_ORIGIN)):
        monkeypatch.setenv(key, value)
    return monkeypatch


def prod_client():
    return TestClient(create_app(), base_url=PROD_ORIGIN, raise_server_exceptions=False)


@pytest.mark.parametrize("change", [
    {"LOANKART_SECRET_KEY": ""}, {"LOANKART_SECRET_KEY": "short"}, {"LOANKART_ADVISOR_PASSWORD": ""},
    {"LOANKART_ADVISOR_PASSWORD": "short"}, {"LOANKART_CORS_ORIGINS": "*"}, {"LOANKART_CORS_ORIGINS": ""},
    {"LOANKART_CORS_ORIGINS": "http://loankart.example"}, {"LOANKART_CORS_ORIGINS": f"{PROD_ORIGIN},*"},
])
def test_production_refuses_to_start_with_unsafe_configuration(prod_env, change):
    for key, value in change.items():
        prod_env.setenv(key, value)
    with pytest.raises(RuntimeError, match="Unsafe production configuration") as err:
        create_app()
    assert PROD_PASSCODE not in str(err.value)            # the message names the setting, never a value


def test_an_unknown_environment_name_is_an_error_not_a_silent_development_mode(db_path, monkeypatch):
    monkeypatch.setenv("LOANKART_ENV", "prod")
    with pytest.raises(RuntimeError, match="LOANKART_ENV"):
        create_app()


def test_production_hides_api_docs_and_sets_secure_cookies_and_hsts(prod_env):
    with prod_client() as c:
        assert [c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")] == [404, 404, 404]
        login = c.post("/api/auth/advisor/login", json={"password": PROD_PASSCODE}, headers={"Origin": PROD_ORIGIN})
        assert login.status_code == 200 and "secure" in login.headers["set-cookie"].lower()
        assert "strict-transport-security" in login.headers
        assert c.get("/api/advisor/cases").status_code == 200


def test_production_disables_demo_controls_and_the_shared_demo_by_default(prod_env):
    with prod_client() as c:
        assert c.get("/api/demo/borrower").status_code == 403
        assert c.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}).status_code == 403
        assert c.post("/api/auth/advisor/login", json={"password": PROD_PASSCODE}).status_code == 200
        for method, path in (("POST", "/api/demo/reset"), ("GET", "/api/demo/state"), ("GET", "/api/demo/logs"),
                             ("GET", "/api/demo/scenarios"), ("POST", f"/api/demo/regenerate-documents/{CASE}"),
                             ("GET", f"/api/demo/ground-truth/{CASE}"), ("POST", "/api/demo/trigger")):
            assert c.request(method, path).status_code == 404, f"{method} {path} must not exist in production"
        assert c.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}).status_code == 200      # advisors only
        assert c.get("/api/advisor/cases").status_code == 200


def test_production_demo_controls_can_be_enabled_but_stay_advisor_only(prod_env):
    prod_env.setenv("LOANKART_ENABLE_DEMO_TOOLS", "1")
    prod_env.setenv("LOANKART_PUBLIC_DEMO", "1")
    with prod_client() as c:
        assert c.post("/api/demo/reset").status_code == 401
        assert c.post("/api/demo/load", json={"scenario_id": "tiruppur_textile"}).status_code == 200      # opted-in public demo
        assert c.post("/api/demo/reset").status_code == 401                                                # a visitor, not an advisor
        assert c.post("/api/auth/advisor/login", json={"password": PROD_PASSCODE}).status_code == 200
        assert c.post("/api/demo/reset").status_code == 200


def test_production_still_isolates_borrowers_and_keeps_the_borrower_journey(prod_env):
    with prod_client() as a, prod_client() as b:
        _, case_id = borrower_browser(a)
        ok(a.post(f"/api/cases/{case_id}/documents/synthetic"))
        assert b.get(f"/api/cases/{case_id}").status_code == 401
        borrower_browser(b)
        assert b.get(f"/api/cases/{case_id}").status_code == 403
        assert a.get(f"/api/cases/{case_id}/documents").status_code == 200
