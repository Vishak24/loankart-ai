import pytest
from fastapi.testclient import TestClient

from app.demo_data import DEMO_BORROWER_ID, DEMO_PROFILE
from app.main import create_app

VALID = {
    "borrower_name": "Asha Kumar",
    "business_name": "Asha Tiffin Centre",
    "industry": "food_hospitality",
    "city": "Madurai",
    "state": "Tamil Nadu",
    "business_vintage_years": 3,
    "requested_amount": 500000,
    "loan_purpose": "working_capital",
    "monthly_revenue": 250000,
    "monthly_expenses": 180000,
    "existing_loan_count": 1,
    "outstanding_loan_amount": 120000,
    "monthly_emi": 9000,
    "personal_monthly_income": 40000,
    "collateral": "none",
    "gst_status": "not_registered",
    "business_registration": "udyam_proprietorship",
    "previously_rejected": False,
}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


def test_demo_borrower_is_seeded_and_synthetic(client):
    r = client.get("/api/demo/borrower")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == DEMO_BORROWER_ID
    assert body["is_synthetic"] is True
    assert body["previously_rejected"] is True
    assert body["monthly_revenue"] == 650_000 and body["existing_loan_count"] == 2
    # The ground truth behind the scenario is never served on the borrower API.
    assert "synthetic_evidence" not in body and "planted_inconsistencies" not in r.text


def test_demo_reset_restores_original(client):
    changed = {**DEMO_PROFILE, "requested_amount": 99999}
    assert client.put(f"/api/borrowers/{DEMO_BORROWER_ID}", json=changed).status_code == 200
    assert client.get("/api/demo/borrower").json()["requested_amount"] == 99999

    r = client.post("/api/demo/reset")
    assert r.status_code == 200
    assert r.json()["requested_amount"] == DEMO_PROFILE["requested_amount"]


def test_create_and_get_borrower(client):
    r = client.post("/api/borrowers", json=VALID)
    assert r.status_code == 201
    created = r.json()
    assert created["is_synthetic"] is False
    assert created["collateral_value"] is None
    assert created["borrower_name"] == "Asha Kumar"

    r = client.get(f"/api/borrowers/{created['id']}")
    assert r.status_code == 200
    assert r.json() == created


def test_update_borrower(client):
    bid = client.post("/api/borrowers", json=VALID).json()["id"]
    updated = {**VALID, "requested_amount": 750000, "previously_rejected": True,
               "rejection_reason": "credit_score", "rejection_note": "Score too low, they said"}
    r = client.put(f"/api/borrowers/{bid}", json=updated)
    assert r.status_code == 200
    assert r.json()["requested_amount"] == 750000
    assert client.get(f"/api/borrowers/{bid}").json()["rejection_reason"] == "credit_score"


def test_unknown_borrower_returns_404(client):
    assert client.get("/api/borrowers/nope").status_code == 404
    r = client.put("/api/borrowers/nope", json=VALID)
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


@pytest.mark.parametrize(
    "patch, field",
    [
        ({"borrower_name": "A"}, "borrower_name"),
        ({"requested_amount": 0}, "requested_amount"),
        ({"monthly_revenue": -5}, "monthly_revenue"),
        ({"industry": "casino"}, "industry"),
        ({"unexpected": "x"}, "unexpected"),
    ],
)
def test_invalid_field_returns_422(client, patch, field):
    r = client.post("/api/borrowers", json={**VALID, **patch})
    assert r.status_code == 422
    assert any(field in err["loc"] for err in r.json()["detail"])


def test_missing_field_returns_422(client):
    body = {k: v for k, v in VALID.items() if k != "city"}
    r = client.post("/api/borrowers", json=body)
    assert r.status_code == 422
    assert any("city" in err["loc"] for err in r.json()["detail"])


@pytest.mark.parametrize(
    "patch",
    [
        {"existing_loan_count": 0},  # still has outstanding + EMI
        {"outstanding_loan_amount": 0},  # has a loan but nothing outstanding
        {"previously_rejected": True},  # no reason given
        {"rejection_reason": "credit_score"},  # reason without rejection
    ],
)
def test_inconsistent_profile_returns_422(client, patch):
    r = client.post("/api/borrowers", json={**VALID, **patch})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"][0]["msg"], str)


def test_data_persists_across_app_instances(db_path):
    with TestClient(create_app()) as c1:
        bid = c1.post("/api/borrowers", json=VALID).json()["id"]
    with TestClient(create_app()) as c2:  # fresh app, same SQLite file
        r = c2.get(f"/api/borrowers/{bid}")
        assert r.status_code == 200
        assert r.json()["business_name"] == "Asha Tiffin Centre"
        # demo seed is not duplicated or reset on restart
        assert c2.get("/api/demo/borrower").status_code == 200
    assert db_path.exists()


def test_cors_allows_vite_dev_origin(client):
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        r = client.options(
            "/api/borrowers",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "content-type"},
        )
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == origin


def test_cors_rejects_unknown_origin(client):
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
