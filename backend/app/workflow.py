"""Case workflow after the investigation: restructuring, recommendations, proposal, simulated application,
escalation. Every figure comes from calculations.py via the engines; every lender outcome from lenders.evaluate.
AI text is added through AIService and stored beside, never inside, the calculated data.
"""

import sqlite3
import zlib
from pathlib import Path
from typing import Any

from reportlab.platypus import Paragraph, Spacer

from . import analysis, db, docgen, environment, investigation, lenders, recommendations, restructuring
from .config import Settings
from .errors import Conflict, NotFound
from .integrations import AIService, paytm

rs = analysis.rs
PROPOSAL_DISCLAIMER = "DRAFT FOR REVIEW — NOT A SANCTION LETTER."
SIM_BANNER = ("Demo simulation: this application goes to a fictional lender run by the LoanKart lender simulator. "
              "No real lender is involved and no real decision has been made.")
STATUS_LABELS = {
    "draft": "Draft", "ready": "Ready for submission", "submitted": "Submitted (simulated)",
    "under_review": "Under review (simulated)", "query_raised": "Query raised (simulated)",
    "info_supplied": "Additional information supplied", "offer_generated": "Offer generated (simulated)",
    "rejected": "Rejected (simulated)", "human_review": "Human review required",
}
NEXT_STEP = {
    "under_review": "The simulated lender is reviewing the pack. Check for an update.",
    "query_raised": "Answer the lender's query. LoanKart can draft a reply from your documents.",
    "info_supplied": "Your reply is with the simulated lender. Check for an update.",
    "offer_generated": "Review the simulated offer. It is an illustration of what a lender response could look like.",
    "rejected": "Go back to the diagnosis with what the simulated lender said, or ask an advisor to review.",
    "human_review": "A LoanKart advisor will review this case. Nothing more is needed from you right now.",
}
CHECKPOINTS = [
    ("reviewed_figures", "I have checked the figures used in this proposal."),
    ("share_documents", "I agree to share the listed documents with {lender} for this simulated application."),
    ("understand_simulated", "I understand this is a simulated application to a fictional lender, not a real loan application."),
]
QUERY_TEMPLATES = [   # (finding id prefix, query text) in order of priority; at most two are raised
    ("emi_return", "Please explain the EMI that was returned in the last 12 months."),
    ("revenue_evidence_gap", "The sales figure stated by the applicant differs from the documents. Please confirm which "
                             "figure this application relies on."),
    ("late_gst_filings", "Please explain why GST returns were filed after the due date."),
    ("undocumented_loan", "Please confirm the status of the additional loan seen in the bank statement."),
]


# ---------------------------------------------------------------------------------------------- case

def stages(data: dict[str, Any]) -> dict[str, str]:
    inv, app = data["investigation"]["status"], data["application"]
    done = inv == "complete"
    return {
        "investigation": "complete" if done else ("in_progress" if inv == "running" else "available"),
        "diagnosis": "available" if done else "locked",
        "restructure": ("complete" if data["restructure"] else "available") if done else "locked",
        "options": ("complete" if data["selection"] else "available") if done else "locked",
        "proposal": "locked" if not data["proposal"] else ("complete" if app else "in_progress"),
        "tracking": "locked" if not app else ("complete" if app["status"] in ("offer_generated", "rejected") else "in_progress"),
    }


def case_out(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any]) -> dict[str, Any]:
    borrower = db.get_borrower(conn, case["borrower_id"])
    return {
        "id": case["id"], "borrower_id": case["borrower_id"], "scenario_id": case["scenario_id"],
        "is_synthetic": bool(borrower and borrower["is_demo"]), "intent": case["intent"],
        "borrower": environment.profile_of(conn, case), "stages": stages(case["data"]),
        "consents": case["data"]["consents"], "escalation": case["data"]["escalation"],
        "ai_mode": AIService(settings, conn).mode, "created_at": case["created_at"], "updated_at": case["updated_at"],
    }


def set_consent(conn: sqlite3.Connection, case: dict[str, Any], key: str, granted: bool) -> dict[str, Any]:
    def change(data: dict[str, Any]) -> None:
        data["consents"][key] = granted
        if key == "paytm_evidence" and not granted and data["restructure"]:
            data["restructure"]["include_paytm_evidence"] = False       # revoking consent removes the evidence
    updated = db.update_case(conn, case["id"], change)
    db.add_event(conn, "audit", f"Consent {'granted' if granted else 'withdrawn'}: {key}", case_id=case["id"], actor="borrower")
    return updated


def document_out(doc: dict[str, Any]) -> dict[str, Any]:
    ex = doc["extraction"] or {}
    return {"id": doc["id"], "case_id": doc["case_id"], "doc_type": doc["doc_type"], "group": doc["grp"],
            "title": doc["title"], "period": doc["period"], "filename": doc["filename"], "source": doc["source"],
            "status": doc["status"], "url": f"/api/documents/{doc['id']}/file", "warnings": ex.get("warnings", []),
            "checks": ex.get("checks", [])}


def _result(case: dict[str, Any]) -> dict[str, Any]:
    result = case["data"]["investigation"]["result"]
    if case["data"]["investigation"]["status"] != "complete" or not result:
        raise Conflict("Run the investigation first.")
    return result


def answer(conn: sqlite3.Connection, case: dict[str, Any], clarification_id: str, value: str) -> dict[str, Any]:
    result = _result(case)
    known = {c["id"]: c for c in result["clarifications"]}
    requests = {r["id"] for r in case["data"]["advisor_requests"]}
    if clarification_id in known:
        if value not in {o["code"] for o in known[clarification_id]["options"]}:
            raise Conflict("That is not one of the available answers.")
    elif clarification_id not in requests:
        raise NotFound(f"Question '{clarification_id}' not found")

    def change(data: dict[str, Any]) -> None:
        if clarification_id in requests:
            next(r for r in data["advisor_requests"] if r["id"] == clarification_id)["answer"] = value
        else:
            data["answers"][clarification_id] = value
    db.update_case(conn, case["id"], change)
    db.add_event(conn, "audit", "Borrower answered a question", case_id=case["id"], actor="borrower", detail=clarification_id)
    investigation.recompute(conn, case["id"], environment.profile_of(conn, case))
    return environment.get_case(conn, case["id"])


def finding_feedback(conn: sqlite3.Connection, case: dict[str, Any], finding_id: str, action: str, note: str
                     ) -> dict[str, Any]:
    if finding_id not in {f["id"] for f in _result(case)["findings"]}:
        raise NotFound(f"Finding '{finding_id}' not found")
    entry = {"action": action, "note": note, "by": "borrower", "at": db._now()}
    updated = db.update_case(conn, case["id"], lambda d: d["finding_feedback"].__setitem__(finding_id, entry))
    db.add_event(conn, "audit", f"Borrower marked a finding: {action}", case_id=case["id"], actor="borrower", detail=finding_id)
    return updated


def explain_findings(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any]) -> dict[str, Any]:
    result = _result(case)
    view = investigation.view(case, 0)
    stated = next((f["evidence"][0]["value"] for f in result["findings"] if f["id"] == "stated_rejection_reason"), None)
    context = {
        "business_name": environment.profile_of(conn, case)["business_name"], "stated_reason": stated,
        "findings": [{k: f[k] for k in ("title", "severity", "verification_label", "explanation")} for f in view["findings"]],
        "headline": [{"label": h["label"], "value": rs(h["value"]) if h["unit"] == "inr" and h["value"] is not None
                      else h["value"], "state": h["state_label"]} for h in view["headline"]],
        "open_questions": sum(1 for c in view["clarifications"] if not c["answer"] or c["answer"] == "not_sure"),
    }
    summary = AIService(settings, conn).generate("diagnosis_summary", context, case["id"])
    return db.update_case(conn, case["id"], lambda d: d["investigation"].__setitem__("summary", summary))


# ---------------------------------------------------------------------------------------------- restructuring

def _paytm(settings: Settings, case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    if not case["data"]["consents"]["paytm_evidence"]:
        return None
    fixture = paytm.load_fixture(environment.pack_dir(settings, case["id"]))
    return paytm.summarise(fixture, result["months"]) if fixture else None


def _inputs(case: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    inputs = {**restructuring.default_inputs(profile), **(case["data"]["restructure"] or {})}
    if not case["data"]["consents"]["paytm_evidence"]:
        inputs["include_paytm_evidence"] = False
    return inputs


def _facts(conn: sqlite3.Connection, case: dict[str, Any], profile: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    result = _result(case)
    base = analysis.build_facts(result, profile)
    base["open_clarifications"] += sum(1 for r in case["data"]["advisor_requests"] if not r["answer"])
    return restructuring.apply(inputs, base, result["obligations"])


def restructure_view(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any],
                     inputs: dict[str, Any] | None = None, save: bool = False) -> dict[str, Any]:
    result, profile = _result(case), environment.profile_of(conn, case)
    if inputs is not None:
        known = {o["account_no"] for o in result["obligations"]}
        unknown = set(inputs["liability_actions"]) - known
        if unknown:
            raise Conflict(f"Unknown loan account: {', '.join(sorted(unknown))}")
        if inputs["include_paytm_evidence"] and not case["data"]["consents"]["paytm_evidence"]:
            raise Conflict("Consent to use Paytm payment data is needed before it can be added as evidence.")
        if save:
            def change(data: dict[str, Any]) -> None:
                data["restructure"] = inputs
                data["commentary"] = None
            case = db.update_case(conn, case["id"], change)
            db.add_event(conn, "audit", "Restructuring scenario saved", case_id=case["id"], actor="borrower")
    chosen = inputs if inputs is not None else _inputs(case, profile)
    base = analysis.build_facts(result, profile)
    summary = _paytm(settings, case, result)
    out = restructuring.compute(chosen, base, result, profile, db.list_products(conn), summary)
    return {**out, "saved": case["data"]["restructure"] == chosen, "paytm": summary}


# ---------------------------------------------------------------------------------------------- recommendations

def recommendations_view(conn: sqlite3.Connection, case: dict[str, Any], priority: str | None = None) -> dict[str, Any]:
    profile = environment.profile_of(conn, case)
    inputs = _inputs(case, profile)
    priority = priority or case["data"]["priority"]
    notes = [k for k in db.list_knowledge(conn) if k["status"] == "approved"]
    out = recommendations.recommend(_facts(conn, case, profile, inputs), db.list_products(conn), priority,
                                    inputs["product_categories"], notes, lenders.load_catalogue()["history"])
    commentary = case["data"]["commentary"]
    if commentary and out["options"] and out["options"][0]["product_id"] == commentary["product_id"] \
            and commentary["priority"] == priority:
        out["options"][0]["ai_commentary"] = commentary["narrative"]
    selection = case["data"]["selection"]
    return {**out, "selected_product_id": selection["product_id"] if selection else None}


def explain_recommendation(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any], priority: str
                           ) -> dict[str, Any]:
    recs = recommendations_view(conn, case, priority)
    if not recs["options"]:
        raise Conflict("There is no viable option to explain.")
    top = recs["options"][0]
    keys = ("lender_name", "product_name", "score", "score_factors", "risks", "required_changes", "status_label",
            "apr_pct", "dscr_after")
    context = {"priority_label": recs["priority_label"], "option": {k: top[k] for k in keys},
               "amounts": {"fresh_funds": rs(top["fresh_funds"]), "monthly_payment": rs(top["monthly_payment"]),
                           "total_repayment": rs(top["total_repayment"]), "fees": rs(top["fees"])},
               "runner_up": {k: recs["options"][1][k] for k in ("lender_name", "product_name", "score")}
               if len(recs["options"]) > 1 else None}
    narrative = AIService(settings, conn).generate("recommendation_commentary", context, case["id"])
    entry = {"product_id": top["product_id"], "priority": priority, "narrative": narrative}
    db.update_case(conn, case["id"], lambda d: d.__setitem__("commentary", entry))
    return recommendations_view(conn, environment.get_case(conn, case["id"]), priority)


# ---------------------------------------------------------------------------------------------- proposal

def select(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any], product_id: str, priority: str
           ) -> dict[str, Any]:
    recs = recommendations_view(conn, case, priority)
    option = next((o for o in recs["options"] if o["product_id"] == product_id), None)
    if option is None:
        raise Conflict("That product is not among the viable options for this case.")
    profile = environment.profile_of(conn, case)
    headline = {h["key"]: h for h in _result(case)["headline"]}
    facts = [f"{headline[k]['label'].lower()} {rs(headline[k]['value'])}" for k in
             ("avg_business_receipts", "avg_operating_surplus", "existing_emi") if headline[k]["value"] is not None]
    context = {"business_name": profile["business_name"], "city": profile["city"], "facts": facts,
               "option": {"lender_name": option["lender_name"], "product_name": option["product_name"],
                          "amount_text": rs(option["suggested_amount"]), "required_changes": option["required_changes"]}}
    summary = AIService(settings, conn).generate("proposal_summary", context, case["id"])

    def change(data: dict[str, Any]) -> None:
        data["priority"] = priority
        data["selection"] = {"product_id": product_id}
        data["proposal"] = {"status": "draft", "option": {**option, "ai_commentary": None}, "summary": summary,
                            "checkpoints": {key: False for key, _ in CHECKPOINTS}, "created_at": db._now()}
        data["application"] = None
    updated = db.update_case(conn, case["id"], change)
    db.add_event(conn, "audit", "Financing route selected", case_id=case["id"], actor="borrower",
                 detail=f"{option['lender_name']} {option['product_name']}")
    return updated


def _proposal(case: dict[str, Any]) -> dict[str, Any]:
    if not case["data"]["proposal"]:
        raise Conflict("Select a financing option first.")
    return case["data"]["proposal"]


def proposal_view(conn: sqlite3.Connection, case: dict[str, Any]) -> dict[str, Any]:
    proposal, result = _proposal(case), _result(case)
    option = proposal["option"]
    product = next((p for p in db.list_products(conn) if p["id"] == option["product_id"]), None)
    required = set(product["required_documents"]) if product else set()
    on_file = result["document_types"]
    it = investigation.view(case, 0)

    def item(group: str, doc_type: str, label: str) -> dict[str, Any]:
        n = on_file.get(doc_type, 0)
        return {"id": doc_type, "group": group, "label": label, "status": "on_file" if n else "missing",
                "detail": f"{n} on file" if n else ("Needed by this lender." if doc_type in required
                                                    else "Not on file. Not required by this lender."),
                "required_by_lender": doc_type in required}

    checklist = [
        {"id": "kyc", "group": "Identity", "label": "PAN and Aadhaar of the proprietor", "status": "to_provide",
         "detail": "Not collected by LoanKart in this demo. You would hand these to the lender directly.",
         "required_by_lender": True},
        item("Business proof", "udyam_certificate", "Udyam registration certificate"),
        item("Business proof", "gst_certificate", "GST registration certificate"),
        item("Banking and cash flow", "bank_statement", "Bank statements, 12 months"),
        item("Banking and cash flow", "gstr3b", "GST returns (GSTR-3B)"),
        item("Existing loan statements", "loan_statement", "Statements for running loans"),
        item("Existing loan statements", "repayment_history", "EMI repayment history"),
        item("Additional evidence", "itr", "Income-tax returns"),
        item("Additional evidence", "pnl", "Profit and loss account"),
        item("Additional evidence", "balance_sheet", "Balance sheet"),
        item("Additional evidence", "collateral_valuation", "Valuation of the security"),
    ]
    payment = (f"Interest of {rs(option['monthly_payment'])} a month; the amount drawn stays owed"
               if option["repayment_type"] == "interest_only" else f"EMI of {rs(option['monthly_payment'])}")
    structure = [("Lender", option["lender_name"]), ("Product", option["product_name"]),
                 ("Loan amount", rs(option["suggested_amount"])), ("Fresh funds to the business", rs(option["fresh_funds"])),
                 ("Existing loans closed with it", rs(option["takeover_amount"])),
                 ("Tenure", f"{option['tenure_months']} months"), ("Interest rate", f"{option['rate_pct']}% a year"),
                 ("Repayment", payment), ("Fees and charges", rs(option["fees"])),
                 ("APR including fees", f"{option['apr_pct']}%"), ("Total repayment", rs(option["total_repayment"]))]
    lender = option["lender_name"]
    return {
        "status": proposal["status"], "disclaimer": PROPOSAL_DISCLAIMER, "option": option,
        "facts_used": [h for h in it["headline"] if h["key"] in (
            "avg_business_receipts", "avg_operating_expenses", "avg_operating_surplus", "existing_emi", "itr_net_annual",
            "collateral_value")],
        "structure": [{"code": k, "label": v} for k, v in structure],
        "assumptions": ["Figures are illustrative estimates calculated by LoanKart from the documents on file.",
                        "Lender terms are fictional policy values used for simulation.",
                        f"Policy version {option['source']['policy_version']}, effective {option['source']['effective_date']}."],
        "checklist": checklist,
        "unresolved": option["unresolved_conditions"] + [c["label"] for c in checklist
                                                         if c["status"] == "missing" and c["required_by_lender"]],
        "checkpoints": [{"key": k, "label": label.format(lender=lender), "done": proposal["checkpoints"][k]}
                        for k, label in CHECKPOINTS],
        "summary": proposal["summary"], "pdf_url": f"/api/cases/{case['id']}/proposal/pdf",
        "created_at": proposal["created_at"],
    }


def set_checkpoint(conn: sqlite3.Connection, case: dict[str, Any], key: str, done: bool) -> dict[str, Any]:
    proposal = _proposal(case)
    if key not in proposal["checkpoints"]:
        raise NotFound(f"Checkpoint '{key}' not found")
    if proposal["status"] == "submitted":
        raise Conflict("The application has already been submitted.")

    def change(data: dict[str, Any]) -> None:
        p = data["proposal"]
        p["checkpoints"][key] = done
        p["status"] = "ready" if all(p["checkpoints"].values()) else "draft"
        if key == "share_documents":
            data["consents"]["share_with_lender"] = done
    updated = db.update_case(conn, case["id"], change)
    db.add_event(conn, "audit", f"Approval checkpoint {'confirmed' if done else 'cleared'}: {key}", case_id=case["id"],
                 actor="borrower")
    return updated


def proposal_pdf(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any]) -> Path:
    view, profile = proposal_view(conn, case), environment.profile_of(conn, case)
    plain = lambda text: str(text).replace("₹", "INR ").replace("—", "-")  # noqa: E731  base PDF fonts have no rupee glyph
    story: list[Any] = [
        Paragraph(plain(PROPOSAL_DISCLAIMER), docgen.H1),
        Paragraph("Financing proposal prepared by LoanKart.ai for a simulated application to a fictional lender. "
                  "It is not an offer, an approval or a sanction.", docgen.SMALL), Spacer(1, 8),
        Paragraph("Applicant", docgen.H2),
        docgen.kv([("Business", profile["business_name"]), ("Proprietor", profile["borrower_name"]),
                   ("Location", f"{profile['city']}, {profile['state']}"), ("Case reference", case["id"])]),
        Paragraph("Proposed financing structure", docgen.H2),
        docgen.kv([(row["code"], plain(row["label"])) for row in view["structure"]]),
        Paragraph("Documented figures used", docgen.H2),
        docgen.kv([(h["label"], f"{plain(rs(h['value'])) if h['value'] is not None else 'Not available'} ({h['state_label']})")
                   for h in view["facts_used"]]),
    ]
    if view["summary"]:
        story += [Paragraph("Summary", docgen.H2), Paragraph(plain(view["summary"]["body"]), docgen.BODY)]
    for title, lines in (("What the borrower would need to do", view["option"]["required_changes"]),
                         ("Risks", view["option"]["risks"]), ("Still unresolved", view["unresolved"]),
                         ("Assumptions", view["assumptions"])):
        if lines:
            story.append(Paragraph(title, docgen.H2))
            story += [Paragraph("- " + plain(line), docgen.BODY) for line in lines]
    story.append(Paragraph("Document checklist", docgen.H2))
    story.append(docgen.grid(["Group", "Document", "Status"],
                             [[c["group"], c["label"], c["status"].replace("_", " ")] for c in view["checklist"]],
                             [150, 260, 110], right_from=3))
    path = settings.storage_dir / "proposals" / f"{case['id']}.pdf"
    docgen.write_pdf(path, "LoanKart draft proposal", story)
    return path


# ---------------------------------------------------------------------------------------------- simulated application

def _event(conn: sqlite3.Connection, case_id: str, title: str, detail: str = "", actor: str = "lender-simulator") -> None:
    db.add_event(conn, "application", f"{title} (simulated)", case_id=case_id, actor=actor, detail=detail, simulated=True)


def _application(case: dict[str, Any]) -> dict[str, Any]:
    if not case["data"]["application"]:
        raise Conflict("The application has not been submitted yet.")
    return case["data"]["application"]


def submit(conn: sqlite3.Connection, case: dict[str, Any]) -> dict[str, Any]:
    proposal = _proposal(case)
    if case["data"]["application"]:
        raise Conflict("This application has already been submitted.")
    if proposal["status"] != "ready":
        raise Conflict("Confirm every approval checkpoint before submitting.")
    option = proposal["option"]
    lender_id = option["product_id"].split("-")[0].upper()
    seed = f"{case['id']}:{option['product_id']}".encode()
    reference = f"SIM-{lender_id}-{zlib.crc32(seed) % 10**6:06d}"      # derived, so a reset reproduces it

    def change(data: dict[str, Any]) -> None:
        data["proposal"]["status"] = "submitted"
        data["application"] = {"status": "under_review", "reference": reference, "product_id": option["product_id"],
                               "lender_name": option["lender_name"], "product_name": option["product_name"],
                               "queries": [], "offer": None, "decision_label": None, "decision_explanation": None,
                               "failed_rules": [], "round": 0}
    updated = db.update_case(conn, case["id"], change)
    _event(conn, case["id"], "Application pack prepared", "Proposal and document checklist assembled.", "loankart")
    _event(conn, case["id"], f"Submitted to {option['lender_name']}", f"Simulated reference {reference}.", "borrower")
    _event(conn, case["id"], "Under review")
    return updated


def _offer(product: dict[str, Any], amount: int, tenure: int, label: str, conditions: list[str]) -> dict[str, Any]:
    t = lenders.terms(product, amount, tenure)
    return {"label": label, "amount": amount, "rate_pct": product["interest_rate_pct"], "tenure_months": tenure,
            "monthly_payment": t["monthly_payment"], "repayment_type": product["repayment_type"], "fees": t["fees"],
            "apr_pct": t["apr_pct"], "total_repayment": t["total_repayment"],
            "validity": "Illustration only. A real offer would carry the lender's own Key Facts Statement and validity.",
            "conditions": conditions + ["Subject to the lender verifying original documents (simulated)."]}


def advance(conn: sqlite3.Connection, case: dict[str, Any]) -> dict[str, Any]:
    """One step of the lender simulator. Deterministic: the same case state always produces the same next event."""
    app = _application(case)
    if app["status"] not in ("under_review", "info_supplied", "query_raised"):
        raise Conflict("There is nothing further for the simulated lender to do on this application.")
    if any(q["status"] == "open" for q in app["queries"]):
        raise Conflict("Answer the open query before checking for an update.")
    result, profile = _result(case), environment.profile_of(conn, case)
    product = next(p for p in db.list_products(conn) if p["id"] == app["product_id"])
    finding_ids = [f["id"] for f in result["findings"]]

    if app["round"] == 0:
        raised = [(fid, text) for prefix, text in QUERY_TEMPLATES for fid in finding_ids if fid.startswith(prefix)][:2]
        if raised:
            def change(data: dict[str, Any]) -> None:
                a = data["application"]
                a["round"], a["status"] = 1, "query_raised"
                a["queries"] = [{"id": f"q{i}", "text": text, "routine": True, "status": "open", "draft": None,
                                 "response": None, "raised_at": db._now(), "finding_id": fid}
                                for i, (fid, text) in enumerate(raised, 1)]
            updated = db.update_case(conn, case["id"], change)
            for _, text in raised:
                _event(conn, case["id"], "Query raised", text)
            return updated

    facts = {**_facts(conn, case, profile, _inputs(case, profile)), "open_clarifications": 0}   # queries are answered
    decision = lenders.evaluate(product, facts)
    failed = [r for r in decision["rules"] if r["status"] == "fail"]
    conditions = product["exclusions"][:2]

    def change(data: dict[str, Any]) -> None:
        a = data["application"]
        a["round"] += 1
        a["decision_label"], a["decision_explanation"] = decision["decision_label"], decision["explanation"]
        if decision["decision"] in ("eligible", "alternative_amount_offered"):
            label = ("Simulated lender offer" if decision["decision"] == "eligible"
                     else "Simulated lender offer at an alternative amount")
            a["status"], a["offer"] = "offer_generated", _offer(product, decision["suggested_amount"],
                                                                decision["tenure_months"], label, conditions)
        elif decision["decision"] == "additional_documents_required" and a["round"] <= 2:
            a["status"] = "query_raised"
            a["queries"].append({"id": f"q{len(a['queries']) + 1}", "routine": False, "status": "open", "draft": None,
                                 "response": None, "raised_at": db._now(), "finding_id": "documentation_gaps",
                                 "text": "Please provide: " + ", ".join(decision["missing_documents"]) + "."})
        elif decision["decision"] in ("additional_documents_required", "clarification_required"):
            a["status"] = "human_review"
        else:
            a["status"], a["failed_rules"] = "rejected", failed
    updated = db.update_case(conn, case["id"], change)
    status = updated["data"]["application"]["status"]
    _event(conn, case["id"], {"offer_generated": "Offer generated", "query_raised": "Query raised",
                              "human_review": "Referred for human review", "rejected": "Application rejected"}[status],
           decision["explanation"])
    return updated


def _query(app: dict[str, Any], query_id: str) -> dict[str, Any]:
    query = next((q for q in app["queries"] if q["id"] == query_id), None)
    if query is None:
        raise NotFound(f"Query '{query_id}' not found")
    return query


def draft_query(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any], query_id: str) -> dict[str, Any]:
    query, result = _query(_application(case), query_id), _result(case)
    fid, m = query.get("finding_id") or "", result["metrics"]
    linked = [f["explanation"] for f in result["findings"] if fid and f["id"].startswith(fid)]
    if fid == "revenue_evidence_gap":     # the application always rests on documented figures, never on the estimate
        linked = [f"This application relies on the documented figures: bank statements show average sales receipts of "
                  f"{rs(m['avg_business_receipts'])} a month. My earlier estimate of {rs(m['declared_monthly_revenue'])} "
                  "was approximate."]
    label = lambda c: next((o["label"] for o in c["options"] if o["code"] == c["answer"]), c["answer"])  # noqa: E731
    answers = ["I have told LoanKart: " + label(c) + "." for c in result["clarifications"]
               if c["finding_id"] == fid and c["answer"] and c["answer"] != "not_sure"]
    context = {"query": query["text"], "business_name": environment.profile_of(conn, case)["business_name"],
               "evidence": linked + answers}
    draft = AIService(settings, conn).generate("query_response", context, case["id"])
    return db.update_case(conn, case["id"], lambda d: _query(d["application"], query_id).__setitem__("draft", draft))


def respond_query(conn: sqlite3.Connection, case: dict[str, Any], query_id: str, text: str) -> dict[str, Any]:
    if _query(_application(case), query_id)["status"] != "open":
        raise Conflict("This query has already been answered.")

    def change(data: dict[str, Any]) -> None:
        a = data["application"]
        _query(a, query_id).update(status="answered", response=text)
        if all(q["status"] == "answered" for q in a["queries"]):
            a["status"] = "info_supplied"
    updated = db.update_case(conn, case["id"], change)
    _event(conn, case["id"], "Reply sent to the lender", text[:200], "borrower")
    return updated


def trigger(conn: sqlite3.Connection, case: dict[str, Any], action: str) -> dict[str, Any]:
    """Demo control: force a lender event so each path can be shown on demand. Labelled as forced in the timeline."""
    app = _application(case)
    product = next(p for p in db.list_products(conn) if p["id"] == app["product_id"])
    option = case["data"]["proposal"]["option"]
    note = "Triggered from the demo control centre."

    def change(data: dict[str, Any]) -> None:
        a = data["application"]
        if action == "query":
            a["status"] = "query_raised"
            a["queries"].append({"id": f"q{len(a['queries']) + 1}", "routine": False, "status": "open", "draft": None,
                                 "response": None, "raised_at": db._now(), "finding_id": None,
                                 "text": "The credit team asks for a signed stock statement and the source of margin money. "
                                         "This is outside the documents on file."})
        elif action == "rejection":
            a.update(status="rejected", offer=None, decision_label="Application rejected",
                     decision_explanation=f"{note} Used to demonstrate the path back to diagnosis.", failed_rules=[])
        else:
            amount = max(product["min_amount"], option["suggested_amount"] * 7 // 10 // 10_000 * 10_000)
            a.update(status="offer_generated", decision_label="Alternative amount offered", decision_explanation=note,
                     offer=_offer(product, amount, option["tenure_months"],
                                  "Simulated lender offer at an alternative amount", [note]))
    updated = db.update_case(conn, case["id"], change)
    _event(conn, case["id"], {"query": "Query raised", "rejection": "Application rejected",
                              "alternative_offer": "Alternative offer generated"}[action], note, "demo-control")
    return updated


def application_view(conn: sqlite3.Connection, case: dict[str, Any]) -> dict[str, Any]:
    app, proposal = case["data"]["application"], case["data"]["proposal"]
    events = db.list_events(conn, case["id"], ("application",))
    if not app:
        status = proposal["status"] if proposal and proposal["status"] in ("draft", "ready") else "draft"
        option = proposal["option"] if proposal else None
        return {"status": status, "status_label": STATUS_LABELS[status], "simulated": True, "banner": SIM_BANNER,
                "reference": None, "lender_name": option and option["lender_name"],
                "product_name": option and option["product_name"], "queries": [], "offer": None,
                "decision_label": None, "decision_explanation": None, "failed_rules": [],
                "next_step": "Confirm the approval checkpoints on the proposal, then submit the simulated application.",
                "events": events}
    return {"status": app["status"], "status_label": STATUS_LABELS[app["status"]], "simulated": True,
            "banner": SIM_BANNER, "reference": app["reference"], "lender_name": app["lender_name"],
            "product_name": app["product_name"], "queries": app["queries"], "offer": app["offer"],
            "decision_label": app["decision_label"], "decision_explanation": app["decision_explanation"],
            "failed_rules": app["failed_rules"], "next_step": NEXT_STEP[app["status"]], "events": events}


# ---------------------------------------------------------------------------------------------- escalation

def open_items(case: dict[str, Any]) -> int:
    result = case["data"]["investigation"]["result"]
    if not result:
        return 0
    return (sum(1 for c in result["clarifications"] if not c["answer"] or c["answer"] == "not_sure")
            + len(result["missing_documents"]) + sum(1 for r in case["data"]["advisor_requests"] if not r["answer"]))


def escalate(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any], reason: str) -> dict[str, Any]:
    result, app = case["data"]["investigation"]["result"], case["data"]["application"]
    context = {"business_name": environment.profile_of(conn, case)["business_name"], "reason": reason,
               "investigation_status": case["data"]["investigation"]["status"],
               "findings": [f["title"] for f in result["findings"] if f["severity"] in ("high", "medium")] if result else [],
               "open_items": open_items(case),
               "application_status": STATUS_LABELS[app["status"]] if app else "not submitted"}
    summary = AIService(settings, conn).generate("escalation_summary", context, case["id"])

    def change(data: dict[str, Any]) -> None:
        data["escalation"] = {"status": "open", "reason": reason, "summary": summary, "raised_at": db._now(),
                              "resolution": None}
        data["advisor"]["resolved"] = False
        a = data["application"]
        if a and a["status"] in ("under_review", "query_raised", "info_supplied"):
            a["status"] = "human_review"
    updated = db.update_case(conn, case["id"], change)
    db.add_event(conn, "audit", "Case escalated to an advisor", case_id=case["id"], actor="borrower", detail=reason)
    if updated["data"]["application"] and updated["data"]["application"]["status"] == "human_review":
        _event(conn, case["id"], "Referred for human review", reason, "borrower")
    return updated
