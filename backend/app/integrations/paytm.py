"""Paytm merchant evidence: optional, isolated, consent-gated supplementary cash-flow evidence.

Verified on 15 Nov 2026 from paytmpayments.com/docs and github.com/paytm/paytm-agent-skills:
  - Paytm's developer APIs are payment APIs (checkout, links, QR, refunds, subscriptions, settlements). There is no
    lending or underwriting API, and LoanKart does not treat any of them as one.
  - Settlement Summary API: POST https://secure.paytmpayments.com/merchant-settlement/SettlementSummary with headers
    `clientId` and `Authorization: Bearer <JWT>`, body {"request": {"head": {"reqMsgId"}, "body": {"mid", "startDate",
    "endDate", "pageNum", "pageSize"}}}. Production only, at most one week per call, six months of history, page size
    up to 50. Sibling APIs give settlement detail by batch, order and transaction.
  - Paytm MCP Server (beta) at https://mcp.paytmpayments.com/mcp: an AI assistant connects with the merchant's own
    dashboard login (OAuth 2.0 with OTP). Its tools include fetch_settlement_orders and fetch_settlements_by_date,
    plus payment-link and refund tools. It is an assistant-side connector; this backend does not call it.
  - Paytm Agent Skills: a skills bundle that teaches coding assistants the Payment Gateway integration.

What is implemented here:
  - `summarise`: analysis of a clearly labelled SYNTHETIC merchant fixture, used by the product today.
  - `LivePaytmEvidence.settlement_summary`: the documented Settlement Summary request. It has been sent to the real
    endpoint with invalid credentials only; a successful response has never been seen, so it is not wired into
    cases. Mapping real settlements into the summary is the remaining step once an authorised merchant account exists.

Paytm collections are one sales channel. They are never treated as total revenue.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from ..redact import redact
from .base import ProviderError

FIXTURE_NAME = "paytm_fixture.json"
SOURCE_LABEL = "Synthetic Paytm merchant fixture (demo data, not from Paytm)"
SETTLEMENT_SUMMARY_URL = "https://secure.paytmpayments.com/merchant-settlement/SettlementSummary"


def load_fixture(pack_dir: Path) -> dict[str, Any] | None:
    path = pack_dir / FIXTURE_NAME
    return json.loads(path.read_text()) if path.exists() else None


class LivePaytmEvidence:
    """Authorised live settlement data. Needs the merchant's consent and their own Paytm credentials."""

    def __init__(self, merchant_id: str, client_id: str, access_token: str) -> None:
        self.merchant_id, self.client_id, self.access_token = merchant_id, client_id, access_token

    def settlement_summary(self, start_date: str, end_date: str | None = None, page: int = 1) -> dict[str, Any]:
        """One page of payout summaries for a date range of at most a week (dates as YYYY-MM-DD)."""
        body: dict[str, Any] = {"mid": self.merchant_id, "startDate": start_date, "pageNum": page, "pageSize": 50}
        if end_date:
            body["endDate"] = end_date
        try:
            response = httpx.post(
                SETTLEMENT_SUMMARY_URL, timeout=30,
                headers={"Content-Type": "application/json", "clientId": self.client_id,
                         "Authorization": f"Bearer {self.access_token}"},
                json={"request": {"head": {"reqMsgId": str(uuid.uuid4())}, "body": body}})
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach the Paytm settlement API.") from exc
        if response.status_code in (401, 403):
            raise ProviderError("Paytm rejected the credentials. Check PAYTM_CLIENT_ID and PAYTM_ACCESS_TOKEN.")
        if response.status_code != 200:
            raise ProviderError(f"Paytm settlement API returned HTTP {response.status_code}: {redact(response.text)[:200]}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("Paytm settlement API returned a response that is not JSON.") from exc


def summarise(fixture: dict[str, Any], bank_months: list[dict[str, Any]]) -> dict[str, Any]:
    """Collections, settlement frequency, trend, refunds, seasonality and gross-vs-net, cross-checked against the
    Paytm settlement credits the investigation found in the bank statements."""
    bank = {m["month"]: m for m in bank_months}
    months = [{**m, "bank_credits_matched": bank.get(m["month"], {}).get("paytm_settlements", 0)} for m in fixture["monthly"]]
    active = [m for m in months if m["gross_collections"]] or months
    gross, net = sum(m["gross_collections"] for m in months), sum(m["net_settlements"] for m in months)
    refunds = sum(m["refunds"] for m in months)
    receipts = sum(m.get("business_receipts", 0) for m in bank_months)
    first, last = active[:3], active[-3:]
    avg = lambda rows: sum(r["net_settlements"] for r in rows) / len(rows)  # noqa: E731
    peak, low = max(active, key=lambda m: m["net_settlements"]), min(active, key=lambda m: m["net_settlements"])
    reconciles = all(m["net_settlements"] == m["bank_credits_matched"] for m in months)
    return {
        "source": SOURCE_LABEL, "simulated": True, "merchant_id": fixture["merchant_id"], "months": months,
        "total_gross": gross, "total_net": net, "total_refunds": refunds,
        "avg_net_settlements": round(net / len(active)),
        "settlements_per_month": round(sum(m["settlement_count"] for m in active) / len(active), 1),
        "refund_rate_pct": round(refunds / gross * 100, 2) if gross else 0.0,
        "share_of_bank_receipts_pct": round(net / receipts * 100, 2) if receipts else 0.0,
        "trend_pct": round((avg(last) - avg(first)) / avg(first) * 100, 2) if len(active) >= 6 and avg(first) else None,
        "peak_month": peak["month"], "low_month": low["month"], "reconciles_with_bank": reconciles,
        "notes": [
            "Collections through Paytm are one channel. They are not total business revenue and are not treated as such.",
            "Net settlements are gross payments less fees and refunds.",
            "Every settlement was matched to a credit in the bank statement." if reconciles
            else "Some settlements could not be matched to bank credits; this needs review.",
        ],
    }
