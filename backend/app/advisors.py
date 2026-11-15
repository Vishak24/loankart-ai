"""Advisor dashboard and expert knowledge capture.

Advisors review what the system found; every action is attributed and logged. A correction changes the case it is
made on, with the original value kept. It never edits lender policy. Knowledge captured from an advisor is a
candidate until an expert approves it, and stays labelled as practical experience, separate from official criteria.
"""

import sqlite3
import uuid
from typing import Any

from . import analysis, db, environment, investigation, workflow
from .config import Settings
from .errors import BadInput, Conflict, NotFound
from .integrations import AIService

STAGE_ORDER = ["tracking", "proposal", "options", "restructure", "diagnosis", "investigation"]


def _status(case: dict[str, Any]) -> str:
    data = case["data"]
    if data["escalation"]["status"] == "open":
        return "escalated"
    if data["advisor"]["resolved"]:
        return "resolved"
    app = data["application"]
    if workflow.open_items(case) or (app and app["status"] in ("rejected", "human_review")):
        return "unresolved"
    return "open"


def _blocker(case: dict[str, Any]) -> str:
    data, result = case["data"], case["data"]["investigation"]["result"]
    if data["escalation"]["status"] == "open":
        return data["escalation"]["reason"]
    if not result:
        return "Investigation not run yet"
    app = data["application"]
    if app and app["status"] in ("rejected", "human_review", "query_raised"):
        return workflow.STATUS_LABELS[app["status"]]
    top = next((f for f in result["findings"] if f["severity"] == "high"), None)
    return top["title"] if top else "No blocking finding"


def queue(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for case in db.list_cases(conn):
        borrower = db.get_borrower(conn, case["borrower_id"])
        if borrower is None:
            continue
        profile, stages = borrower["profile"], workflow.stages(case["data"])
        stage = next((s for s in STAGE_ORDER if stages[s] in ("in_progress", "complete")), "investigation")
        app = case["data"]["application"]
        row = {"case_id": case["id"], "borrower_name": profile["borrower_name"], "business_name": profile["business_name"],
               "city": profile["city"], "requested_amount": profile["requested_amount"], "is_synthetic": borrower["is_demo"],
               "stage": stage, "status": _status(case), "blocker": _blocker(case), "open_items": workflow.open_items(case),
               "application_status": workflow.STATUS_LABELS[app["status"]] if app else None, "updated_at": case["updated_at"]}
        if status in (None, "all") or row["status"] == status:
            rows.append(row)
    order = {"escalated": 0, "unresolved": 1, "open": 2, "resolved": 3}
    return sorted(rows, key=lambda r: (order[r["status"]], r["case_id"]))


def detail(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any]) -> dict[str, Any]:
    done = case["data"]["investigation"]["status"] == "complete"
    return {
        "case": workflow.case_out(conn, settings, case),
        "investigation": investigation.view(case, 0),
        "restructure": workflow.restructure_view(conn, settings, case) if done else None,
        "recommendations": workflow.recommendations_view(conn, case) if done else None,
        "application": workflow.application_view(conn, case) if case["data"]["proposal"] else None,
        "comments": case["data"]["advisor"]["comments"],
        "solution_review": case["data"]["advisor"]["solution_review"],
        "correctable": sorted(analysis.ADVISOR_CORRECTABLE),
        "audit": db.list_events(conn, case["id"], ("audit", "application", "log")),
    }


def act(conn: sqlite3.Connection, case: dict[str, Any], action: dict[str, Any], advisor: str = "advisor") -> dict[str, Any]:
    kind, target, note = action["type"], action.get("target"), action.get("note", "")
    stamp = {"note": note, "by": advisor, "at": db._now()}
    result = case["data"]["investigation"]["result"]
    recompute = False

    if kind in ("review_finding", "review_solution") and not action.get("decision"):
        raise BadInput("A decision (accept or reject) is required.")
    if kind == "review_finding" and (not result or target not in {f["id"] for f in result["findings"]}):
        raise NotFound(f"Finding '{target}' not found")
    if kind == "correct_value":
        if target not in analysis.ADVISOR_CORRECTABLE:
            raise BadInput(f"'{target}' cannot be corrected. Correctable: {', '.join(sorted(analysis.ADVISOR_CORRECTABLE))}")
        if action.get("value") is None or action["value"] < 0 or not note:
            raise BadInput("A correction needs a non-negative value and a note explaining the source.")
        if not result:
            raise Conflict("Run the investigation first.")
        recompute = True
    if kind in ("comment", "request_clarification", "resolve") and not note:
        raise BadInput("Write a note.")

    def change(data: dict[str, Any]) -> None:
        adv = data["advisor"]
        if kind == "review_finding":
            adv["finding_reviews"][target] = {**stamp, "action": action["decision"]}
        elif kind == "review_solution":
            adv["solution_review"] = {**stamp, "action": action["decision"]}
        elif kind == "correct_value":
            data["corrections"][target] = {"value": int(action["value"]), **stamp}
        elif kind == "request_clarification":
            data["advisor_requests"].append({"id": f"advisor-{len(data['advisor_requests']) + 1}", "question": note,
                                             "answer": None, "at": stamp["at"]})
        elif kind == "resolve":
            adv["resolved"] = True
            if data["escalation"]["status"] == "open":
                data["escalation"].update(status="resolved", resolution=note)
        adv["comments"].append({**stamp, "kind": kind if kind != "comment" else "comment",
                                "note": note or f"{kind.replace('_', ' ')}: {action.get('decision') or target}"})
    db.update_case(conn, case["id"], change)
    db.add_event(conn, "audit", f"Advisor action: {kind.replace('_', ' ')}", case_id=case["id"], actor=advisor,
                 detail=f"{target or ''} {action.get('decision') or ''} {note}".strip()[:300])
    if recompute:
        investigation.recompute(conn, case["id"], environment.profile_of(conn, case))
    return environment.get_case(conn, case["id"])


# ---------------------------------------------------------------------------------------------- knowledge

def capture(conn: sqlite3.Connection, settings: Settings, text: str, case_id: str | None, author: str, source: str
            ) -> dict[str, Any]:
    """Structure an advisor's explanation into a reusable candidate. It is inactive until approved."""
    context: dict[str, Any] = {"text": text, "case": None}
    product_id = None
    if case_id:
        case = environment.get_case(conn, case_id)
        profile = environment.profile_of(conn, case)
        proposal, result = case["data"]["proposal"], case["data"]["investigation"]["result"]
        top = next((f["title"] for f in result["findings"] if f["severity"] == "high"), None) if result else None
        product_id = proposal["option"]["product_id"] if proposal else None
        context["case"] = {"business_name": profile["business_name"], "condition": top,
                           "lender_name": proposal["option"]["lender_name"] if proposal else None,
                           "product_name": proposal["option"]["product_name"] if proposal else None}
    draft = AIService(settings, conn).generate("knowledge_candidate", context, case_id)
    entry_id = f"kn-{uuid.uuid4().hex[:8]}"
    data = {"problem": draft["problem"], "reasoning": draft["reasoning"], "lender_name": draft["lender_name"],
            "product_id": product_id, "intervention": draft["intervention"], "outcome": draft["outcome"],
            "conditions": draft["conditions"], "scope": draft["scope"],
            "source": "Advisor voice note" if source == "voice" else "Advisor written note", "case_id": case_id,
            "author": author, "approver": None, "verification_status": "Awaiting expert approval",
            "structured_by": draft["provider"], "raw_text": text}
    db.put_knowledge(conn, entry_id, data, "candidate", 1)
    db.add_event(conn, "audit", "Knowledge candidate captured", case_id=case_id, actor=author, detail=entry_id)
    return next(k for k in db.list_knowledge(conn) if k["id"] == entry_id)


def review(conn: sqlite3.Connection, entry_id: str, decision: str, approver: str) -> dict[str, Any]:
    entry = next((k for k in db.list_knowledge(conn) if k["id"] == entry_id), None)
    if entry is None:
        raise NotFound(f"Knowledge entry '{entry_id}' not found")
    status = "approved" if decision == "approve" else "rejected"
    meta = ("id", "status", "version", "created_at", "updated_at")
    data = {k: v for k, v in entry.items() if k not in meta}
    data["approver"] = approver
    data["verification_status"] = ("Expert approved (practical experience, not lender policy)" if status == "approved"
                                   else "Rejected by expert")
    version = entry["version"] + (0 if entry["status"] == "candidate" else 1)
    db.put_knowledge(conn, entry_id, data, status, version)
    db.add_event(conn, "audit", f"Knowledge entry {status}", actor=approver, detail=entry_id)
    return next(k for k in db.list_knowledge(conn) if k["id"] == entry_id)
