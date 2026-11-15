"""Investigation orchestrator: runs the extraction and analysis as discrete, persisted tasks.

Every task state shown in the UI is the real state of that step in this run. The only artificial element is an
optional short pause between steps (LOANKART_DEMO_PACING_MS) so the timeline can be followed; the UI says so.
This module reads documents and extraction output only. It does not import the ground-truth dataset.
"""

import sqlite3
import time
from pathlib import Path
from typing import Any

from . import analysis, db, extraction
from .config import Settings
from .errors import Conflict
from .integrations import AIService
from .lenders import VIABLE, evaluate

TASKS = [
    ("load_documents", "Documents", "Documents loaded"),
    ("extract_bank", "Documents", "Bank transactions extracted"),
    ("extract_gst", "Documents", "GST returns analysed"),
    ("extract_other", "Documents", "Tax, loan and financial statements read"),
    ("identify_loans", "Financial picture", "Existing loans identified"),
    ("cash_flow", "Financial picture", "Cash flow calculated"),
    ("reconcile", "Consistency checks", "Financial information reconciled"),
    ("findings", "Consistency checks", "Potential rejection factors identified"),
    ("lender_criteria", "Lender criteria", "Lender criteria evaluated"),
]
VERIFICATION_LABELS = {"confirmed_in_document": "Confirmed in the supplied document",
                       "evidence_suggests": "Evidence suggests: possible factor",
                       "requires_confirmation": "Requires confirmation"}
STATE_LABELS = {"verified": "Verified from source", "extracted": "Extracted, review needed", "declared": "Told by you",
                "confirmed": "Confirmed by you", "corrected": "Corrected by advisor", "calculated": "Calculated",
                "missing": "Needs clarification", "simulated": "Demo simulation"}


class _Superseded(Exception):
    """A newer run or a reset replaced this one."""


def start(conn: sqlite3.Connection, case: dict[str, Any]) -> int:
    if not case["data"]["consents"]["analyse_documents"]:
        raise Conflict("Consent to analyse the documents is needed before the investigation can run.")
    if not db.list_documents(conn, case["id"]):
        raise Conflict("Load or upload documents before running the investigation.")
    run_id = case["data"]["investigation"]["run_id"] + 1

    def change(data: dict[str, Any]) -> None:
        data["investigation"] = {
            "status": "running", "run_id": run_id, "result": None, "lender_snapshot": None, "summary": None,
            "error": None,
            "tasks": [{"key": k, "group": g, "title": t, "status": "queued", "started_at": None, "finished_at": None,
                       "output": ""} for k, g, t in TASKS]}

    db.update_case(conn, case["id"], change)
    db.add_event(conn, "audit", "Investigation started", case_id=case["id"], actor="borrower")
    return run_id


def _docs_for_analysis(conn: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    return [{"id": d["id"], "title": d["title"], "extraction": d["extraction"]} for d in db.list_documents(conn, case_id)
            if d["extraction"]]


def lender_snapshot(conn: sqlite3.Connection, result: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    products = db.list_products(conn)
    facts = analysis.build_facts(result, profile)
    results = [evaluate(p, facts) for p in products]
    full = sum(r["decision"] == "eligible" for r in results)
    viable = sum(r["decision"] in VIABLE for r in results)
    lenders = len({p["lender_id"] for p in products})
    return {"lenders_evaluated": lenders, "products_evaluated": len(products), "viable": viable, "fit_in_full": full,
            "text": f"As requested, {full} of {len(products)} products from {lenders} simulated lenders fit in full; "
                    f"{viable} could work with changes."}


def _analyse(conn: sqlite3.Connection, case: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    return analysis.analyse(_docs_for_analysis(conn, case["id"]), profile, case["data"]["answers"],
                            case["data"]["corrections"])


def _task_outputs(result: dict[str, Any]) -> dict[str, tuple[str, str]]:
    m, rs = result["metrics"], analysis.rs
    active = [o for o in result["obligations"] if o["status"] == "active"]
    recon = result["reconciliation"]
    count = lambda status: sum(r["status"] == status for r in recon)  # noqa: E731
    open_q = sum(1 for c in result["clarifications"] if not c["answer"] or c["answer"] == "not_sure")
    high = sum(f["severity"] == "high" for f in result["findings"])
    return {
        "identify_loans": ("complete", f"{len(active)} running loan(s) with EMIs of {rs(m['existing_emi'])} a month; "
                                       f"{len(result['obligations']) - len(active)} ended."),
        "cash_flow": ("complete", f"Sales receipts average {rs(m['avg_business_receipts'])} a month, running costs "
                                  f"{rs(m['avg_operating_expenses'])}, leaving {rs(m['avg_operating_surplus'])}."),
        "reconcile": ("complete", f"{count('matched')} of {len(recon)} cross-checks matched, {count('variance')} show a "
                                  f"difference, {count('missing')} could not be made."),
        "findings": ("needs_input" if open_q else "complete",
                     f"{len(result['findings'])} findings, {high} of them significant."
                     + (f" {open_q} question(s) need your input." if open_q else "")),
    }


def run(settings: Settings, case_id: str, run_id: int, profile: dict[str, Any]) -> None:
    """Background task. Opens its own connection; a failure marks the task and the run as failed, nothing else."""
    conn = db.connect(settings.db_path)
    current = {"key": TASKS[0][0]}

    def mark(key: str, status: str, output: str = "") -> None:
        def change(data: dict[str, Any]) -> None:
            inv = data["investigation"]
            if inv["run_id"] != run_id:
                raise _Superseded()
            task = next(t for t in inv["tasks"] if t["key"] == key)
            task["status"], task["output"] = status, output or task["output"]
            task["started_at" if status == "running" else "finished_at"] = db._now()
        db.update_case(conn, case_id, change)

    def begin(key: str) -> None:
        current["key"] = key
        mark(key, "running")

    def finish(key: str, output: str, status: str = "complete") -> None:
        time.sleep(settings.pacing_ms / 1000)
        mark(key, status, output)

    def extract(docs: list[dict[str, Any]], ai: AIService) -> list[dict[str, Any]]:
        out = []
        for doc in docs:
            lines = ai.document_text(Path(doc["path"]))
            if lines is not None:
                result = extraction.parse_text(lines)
            elif doc["source"] == "upload":           # files from outside are never parsed inside the server process
                try:
                    result = extraction.extract_upload(Path(doc["path"]))
                except ValueError as exc:
                    result = {"doc_type": None, "issuer": None, "fields": {}, "rows": [], "checks": [],
                              "warnings": [f"Could not read this file: {exc}"]}
            else:
                result = extraction.extract_document(Path(doc["path"]))
            status = "extracted" if result["doc_type"] else ("failed" if "Could not read" in " ".join(result["warnings"])
                                                             else "unrecognised")
            db.set_extraction(conn, doc["id"], result, status)
            out.append(result)
        conn.commit()
        return out

    try:
        ai = AIService(settings, conn)
        begin("load_documents")
        docs = db.list_documents(conn, case_id)
        groups = len({d["grp"] for d in docs})
        finish("load_documents", f"{len(docs)} documents in {groups} groups.")

        is_type = lambda d, *types: d["doc_type"] in types  # noqa: E731
        begin("extract_bank")
        bank = extract([d for d in docs if is_type(d, "bank_statement")], ai)
        rows = sum(len(r["rows"]) for r in bank)
        clean = sum(1 for r in bank if r["checks"] and all(c["ok"] for c in r["checks"]))
        finish("extract_bank", f"{rows} transactions read from {len(bank)} statements; running balances and totals "
                               f"reconcile in {clean} of {len(bank)}.")

        begin("extract_gst")
        gst = extract([d for d in docs if is_type(d, "gstr3b", "gstr1")], ai)
        n3b = sum(r["doc_type"] == "gstr3b" for r in gst)
        finish("extract_gst", f"{n3b} GSTR-3B and {len(gst) - n3b} GSTR-1 returns read." if gst
               else "No GST returns were supplied.")

        begin("extract_other")
        other = extract([d for d in docs if not is_type(d, "bank_statement", "gstr3b", "gstr1")], ai)
        unknown = sum(1 for r in other if not r["doc_type"])
        finish("extract_other", f"{len(other) - unknown} other documents read"
               + (f"; {unknown} could not be recognised and were set aside." if unknown else "."))

        case = db.get_case(conn, case_id)
        if case is None:
            raise _Superseded()
        begin("identify_loans")
        result = _analyse(conn, case, profile)
        outputs = _task_outputs(result)
        finish("identify_loans", outputs["identify_loans"][1])
        for key in ("cash_flow", "reconcile", "findings"):
            begin(key)
            finish(key, outputs[key][1], outputs[key][0])

        begin("lender_criteria")
        snapshot = lender_snapshot(conn, result, profile)
        finish("lender_criteria", snapshot["text"])

        def done(data: dict[str, Any]) -> None:
            if data["investigation"]["run_id"] != run_id:
                raise _Superseded()
            data["investigation"].update(status="complete", result=result, lender_snapshot=snapshot)
        db.update_case(conn, case_id, done)
        db.add_event(conn, "audit", "Investigation completed", case_id=case_id,
                     detail=f"{len(result['findings'])} findings")
    except (_Superseded, KeyError):
        pass
    except Exception as exc:
        message = f"{exc.__class__.__name__}: {exc}"

        def failed(data: dict[str, Any]) -> None:
            inv = data["investigation"]
            if inv["run_id"] != run_id:
                return
            inv.update(status="failed", error=f"The step '{current['key']}' failed. You can run the investigation again.")
            for task in inv["tasks"]:
                if task["key"] == current["key"]:
                    task.update(status="failed", output=message[:200], finished_at=db._now())
        try:
            db.update_case(conn, case_id, failed)
            db.add_event(conn, "log", "Investigation failed", case_id=case_id, detail=message[:600])
        except Exception:
            pass
    finally:
        conn.close()


def recompute(conn: sqlite3.Connection, case_id: str, profile: dict[str, Any]) -> None:
    """Re-run the analysis from stored extractions after an answer or a correction. Documents are not re-read."""
    case = db.get_case(conn, case_id)
    if case is None or case["data"]["investigation"]["status"] != "complete":
        return
    result = _analyse(conn, case, profile)
    snapshot = lender_snapshot(conn, result, profile)
    outputs = _task_outputs(result)

    def change(data: dict[str, Any]) -> None:
        inv = data["investigation"]
        inv.update(result=result, lender_snapshot=snapshot, summary=None)     # the AI summary described the old result
        for task in inv["tasks"]:
            if task["key"] in outputs:
                task["status"], task["output"] = outputs[task["key"]]
            if task["key"] == "lender_criteria":
                task["output"] = snapshot["text"]
    db.update_case(conn, case_id, change)


def view(case: dict[str, Any], pacing_ms: int) -> dict[str, Any]:
    """InvestigationOut: the stored result with labels, borrower feedback and advisor reviews merged in."""
    data = case["data"]
    inv, result = data["investigation"], data["investigation"]["result"]
    out: dict[str, Any] = {
        "status": inv["status"], "tasks": inv["tasks"], "summary": inv["summary"], "error": inv["error"],
        "lender_snapshot": inv["lender_snapshot"],
        "pacing_note": ("Each step is real work on the documents. A short pause is added between steps so they can "
                        "be followed." if pacing_ms else "Each step is real work on the documents."),
    }
    if not result:
        return out
    findings = [{**f, "verification_label": VERIFICATION_LABELS[f["verification_state"]],
                 "feedback": data["finding_feedback"].get(f["id"]),
                 "advisor_review": data["advisor"]["finding_reviews"].get(f["id"])} for f in result["findings"]]
    clarifications = result["clarifications"] + [
        {"id": r["id"], "question": r["question"], "why": "Asked by your LoanKart advisor.", "options": [],
         "answer": r["answer"], "finding_id": None, "free_text": True} for r in data["advisor_requests"]]
    headline = [{**h, "state_label": STATE_LABELS[h["state"]]} for h in result["headline"]]
    out.update(headline=headline, metrics=result["metrics"], months=result["months"],
               reconciliation=result["reconciliation"], findings=findings, clarifications=clarifications,
               obligations=result["obligations"], missing_documents=result["missing_documents"],
               unusual=result["unusual"])
    return out
