"""The synthetic lending environment as the application sees it: scenario cases, document packs, lender seed,
ground truth for validation, and reset. This is the only application module that reads the ground-truth dataset;
the investigation code (extraction, analysis, investigation, lenders) never imports it.
"""

import json
import re
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from . import db, docgen, extraction
from .config import Settings
from .demo_data import DEMO_BORROWER_ID
from .errors import BadInput, NotFound
from .integrations import paytm
from .lenders import load_catalogue
from .schemas import BorrowerProfile
from .synthetic import PRIMARY_SCENARIO, SCENARIOS, build_dataset, scenario_from_profile

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SEED_KNOWLEDGE = {
    "id": "kn-seed-gold-od",
    "data": {
        "problem": "Borrower's monthly surplus could not carry the EMI on an unsecured term loan of the size needed.",
        "reasoning": "A term-loan EMI repays principal every month. An overdraft against gold charges interest only on "
                     "what is drawn, so the monthly outflow is a fraction of the EMI for the same limit.",
        "lender_name": "Noyyal Valley Bank (fictional)", "product_id": "nvb-od",
        "intervention": "Moved the request from an unsecured term loan to a gold-backed overdraft sized to the "
                        "loan-to-value limit, and prepared a written explanation for the one returned EMI.",
        "outcome": "Synthetic case: limit offered at the loan-to-value cap after the explanation was accepted.",
        "conditions": ["Borrower owns unencumbered gold with a recent valuation", "At most two EMI returns in 12 months",
                       "Borrower understands the limit is reviewed every 12 months"],
        "scope": "Working-capital needs of traders with gold available. One synthetic case; not a general rule.",
        "source": "Seeded example for the demo", "case_id": None, "author": "LoanKart demo seed", "approver": "LoanKart demo seed",
        "verification_status": "Expert approved (practical experience, not lender policy)", "structured_by": "seed",
    },
}


def borrower_id_for(scenario_id: str) -> str:
    return DEMO_BORROWER_ID if scenario_id == PRIMARY_SCENARIO else f"demo-{scenario_id.replace('_', '-')}"


def case_id_for(scenario_id: str) -> str:
    return f"case-{scenario_id.replace('_', '-')}"


def new_case_data() -> dict[str, Any]:
    return {
        "consents": {"analyse_documents": False, "paytm_evidence": False, "share_with_lender": False},
        "investigation": {"status": "not_started", "run_id": 0, "tasks": [], "result": None, "lender_snapshot": None,
                          "summary": None, "error": None},
        "answers": {}, "corrections": {}, "finding_feedback": {}, "advisor_requests": [],
        "restructure": None, "priority": "balanced", "commentary": None, "selection": None, "proposal": None,
        "application": None,
        "escalation": {"status": "none", "reason": None, "summary": None, "raised_at": None, "resolution": None},
        "advisor": {"comments": [], "finding_reviews": {}, "solution_review": None, "resolved": False},
    }


def profile_of(conn: sqlite3.Connection, case: dict[str, Any]) -> dict[str, Any]:
    borrower = db.get_borrower(conn, case["borrower_id"])
    if borrower is None:
        raise NotFound(f"Borrower for case '{case['id']}' not found")
    return BorrowerProfile.model_validate(borrower["profile"]).model_dump(mode="json")   # fills defaults on old rows


# ---------------------------------------------------------------------------------------------- cases

def ensure_scenario_case(conn: sqlite3.Connection, scenario_id: str) -> dict[str, Any]:
    if scenario_id not in SCENARIOS:
        raise NotFound(f"Scenario '{scenario_id}' not found")
    borrower_id, case_id = borrower_id_for(scenario_id), case_id_for(scenario_id)
    if db.get_borrower(conn, borrower_id) is None:
        db.insert_borrower(conn, borrower_id, build_dataset(SCENARIOS[scenario_id])["profile"], is_demo=True)
    case = db.get_case(conn, case_id)
    if case is None:
        intent = "rejected" if SCENARIOS[scenario_id]["profile"]["previously_rejected"] else "new"
        case = db.insert_case(conn, case_id, borrower_id, scenario_id, intent, new_case_data())
        db.add_event(conn, "audit", "Synthetic case created", case_id=case_id, detail=SCENARIOS[scenario_id]["title"])
    return case


def ensure_case(conn: sqlite3.Connection, borrower_id: str, intent: str) -> dict[str, Any]:
    """One case per borrower. The primary demo borrower always maps to its scenario case."""
    if borrower_id == DEMO_BORROWER_ID:
        return ensure_scenario_case(conn, PRIMARY_SCENARIO)
    if db.get_borrower(conn, borrower_id) is None:
        raise NotFound(f"Borrower '{borrower_id}' not found")
    existing = db.case_for_borrower(conn, borrower_id)
    if existing:
        return existing
    case = db.insert_case(conn, f"case-{uuid.uuid4().hex[:10]}", borrower_id, None, intent, new_case_data())
    db.add_event(conn, "audit", "Case created", case_id=case["id"], actor="borrower")
    return case


def get_case(conn: sqlite3.Connection, case_id: str) -> dict[str, Any]:
    case = db.get_case(conn, case_id)
    if case is None:
        raise NotFound(f"Case '{case_id}' not found")
    return case


# ---------------------------------------------------------------------------------------------- documents

def pack_dir(settings: Settings, case_id: str) -> Path:
    return settings.storage_dir / "packs" / case_id


def dataset_for(conn: sqlite3.Connection, case: dict[str, Any]) -> dict[str, Any]:
    if case["scenario_id"]:
        dataset = build_dataset(SCENARIOS[case["scenario_id"]])
        dataset["profile"] = profile_of(conn, case)       # documents carry the borrower's current name and business
        return dataset
    return build_dataset(scenario_from_profile(profile_of(conn, case), case["id"]))


def reset_investigation(data: dict[str, Any]) -> None:
    """Documents changed: everything derived from them is cleared so nothing stale is shown."""
    fresh = new_case_data()
    for key in ("investigation", "answers", "corrections", "finding_feedback", "restructure", "commentary", "selection",
                "proposal", "application"):
        data[key] = fresh[key]


def load_documents(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any], force: bool = False) -> None:
    """Generate the synthetic document pack for a case (real PDF files) and register it. Idempotent unless forced."""
    existing = [d for d in db.list_documents(conn, case["id"]) if d["source"] == "synthetic"]
    if existing and not force:
        return
    folder = pack_dir(settings, case["id"])
    shutil.rmtree(folder, ignore_errors=True)
    db.delete_documents(conn, case["id"], "synthetic")
    dataset = dataset_for(conn, case)
    for entry in docgen.generate_pack(dataset, folder):
        db.insert_document(conn, {"id": f"{case['id']}--{entry['stem']}", "case_id": case["id"], "doc_type": entry["doc_type"],
                                  "grp": entry["group"], "title": entry["title"], "period": entry["period"],
                                  "filename": entry["filename"], "path": str(folder / entry["filename"]),
                                  "source": "synthetic", "status": "loaded"})
    (folder / paytm.FIXTURE_NAME).write_text(json.dumps(dataset["paytm"]))
    conn.commit()
    if existing:
        db.update_case(conn, case["id"], reset_investigation)
    db.add_event(conn, "audit", "Synthetic document pack generated", case_id=case["id"],
                 detail=f"{len(db.list_documents(conn, case['id']))} documents")


def profile_changed(conn: sqlite3.Connection, settings: Settings, borrower_id: str) -> str | None:
    """Called after a borrower's answers are edited. Returns what was refreshed, for the audit trail."""
    case = db.case_for_borrower(conn, borrower_id)
    if case is None:
        return None
    has_pack = any(d["source"] == "synthetic" for d in db.list_documents(conn, case["id"]))
    if has_pack and not case["scenario_id"]:
        load_documents(conn, settings, case, force=True)        # this pack was built from the old answers
        action = "document pack rebuilt from the new answers; investigation cleared"
    elif case["data"]["investigation"]["status"] == "complete":
        from . import investigation                              # local import: investigation never imports this module
        investigation.recompute(conn, case["id"], profile_of(conn, case))

        def clear(data: dict[str, Any]) -> None:                 # choices made on the old figures no longer stand
            if not data["application"]:
                fresh = new_case_data()
                for key in ("restructure", "commentary", "selection", "proposal"):
                    data[key] = fresh[key]
        db.update_case(conn, case["id"], clear)
        action = "findings recalculated with the new answers"
    else:
        return None
    db.add_event(conn, "audit", "Borrower answers edited", case_id=case["id"], actor="borrower", detail=action)
    return action


MAX_UPLOADS_PER_CASE = 20


def add_upload(conn: sqlite3.Connection, settings: Settings, case: dict[str, Any], filename: str, content: bytes
               ) -> dict[str, Any]:
    if not filename.lower().endswith(".pdf") or not content:
        raise BadInput("Only PDF files are accepted.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise BadInput("The file is larger than 10 MB.")
    if sum(d["source"] == "upload" for d in db.list_documents(conn, case["id"])) >= MAX_UPLOADS_PER_CASE:
        raise BadInput(f"A case can hold at most {MAX_UPLOADS_PER_CASE} uploaded documents.")
    try:
        extraction.validate_pdf_bytes(content)
    except ValueError as exc:
        raise BadInput(str(exc)) from exc
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[-80:]      # never trust a client path
    doc_id = f"{case['id']}--upload-{uuid.uuid4().hex[:8]}"
    folder = settings.storage_dir / "uploads" / case["id"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc_id.rsplit('--', 1)[1]}_{safe}"
    path.write_bytes(content)
    try:
        result = extraction.extract_upload(path)
    except ValueError as exc:
        path.unlink(missing_ok=True)                                         # never keep a file we refused
        raise BadInput(str(exc)) from exc
    db.insert_document(conn, {"id": doc_id, "case_id": case["id"], "doc_type": result["doc_type"], "grp": "Uploaded by you",
                              "title": safe, "period": None, "filename": safe, "path": str(path), "source": "upload",
                              "status": "extracted" if result["doc_type"] else "unrecognised", "extraction": result})
    conn.commit()
    db.add_event(conn, "audit", "Document uploaded", case_id=case["id"], actor="borrower", detail=safe)
    return db.get_document(conn, doc_id)  # type: ignore[return-value]


def document_path(conn: sqlite3.Connection, settings: Settings, doc_id: str) -> tuple[Path, str]:
    doc = db.get_document(conn, doc_id)
    if doc is None:
        raise NotFound(f"Document '{doc_id}' not found")
    path = Path(doc["path"]).resolve()
    if settings.storage_dir.resolve() not in path.parents or not path.exists():   # only files this app stored
        raise NotFound(f"Document '{doc_id}' not found")
    return path, doc["filename"]


# ---------------------------------------------------------------------------------------------- seed, reset, truth

def seed(conn: sqlite3.Connection) -> None:
    """Idempotent: lender catalogue, one example knowledge entry, and the primary synthetic case."""
    if not db.list_products(conn):
        for product in load_catalogue()["products"]:
            db.put_product(conn, product)
    if not db.list_knowledge(conn):
        db.put_knowledge(conn, SEED_KNOWLEDGE["id"], SEED_KNOWLEDGE["data"], "approved", 1)
    ensure_scenario_case(conn, PRIMARY_SCENARIO)


def reset_all(conn: sqlite3.Connection, settings: Settings) -> None:
    """One-click return to the known initial state. Borrowers created through onboarding are kept; their cases,
    like every other case, document, event and knowledge entry, are rebuilt from seed."""
    db.wipe_demo(conn)
    shutil.rmtree(settings.storage_dir, ignore_errors=True)
    conn.execute("DELETE FROM settings")
    conn.commit()
    seed(conn)
    db.add_event(conn, "audit", "Demo reset to initial state", actor="demo-control")


def ground_truth(conn: sqlite3.Connection, case: dict[str, Any]) -> dict[str, Any]:
    """Layer B against Layer C, for validation in the demo control centre. Never used by the investigation."""
    truth = dataset_for(conn, case)["truth"]
    result = case["data"]["investigation"]["result"]
    corrected = result.get("corrected_from", {}) if result else {}
    # Compare what was read from the PDFs: an advisor's correction is reported beside the row, not used to match.
    metrics = {**result["metrics"], **corrected} if result else {}
    keys = {"Average monthly sales receipts": "avg_business_receipts", "Average monthly running costs": "avg_operating_expenses",
            "Existing EMIs": "existing_emi", "EMI returns in 12 months": "emi_returns_12m", "Late GST filings": "late_gst_filings"}

    def same(t: float, i: float) -> bool:
        return i == t if abs(t) < 1000 else abs(i - t) <= abs(t) * 0.001      # counts must be exact; amounts to 0.1%
    active = [m for m in truth["monthly"] if m["business_receipts"]] or truth["monthly"]
    avg = lambda key: round(sum(m[key] for m in active) / len(active))  # noqa: E731
    pairs = [
        ("Average monthly sales receipts", avg("business_receipts"), metrics.get("avg_business_receipts")),
        ("Average monthly total credits", avg("total_credits"), metrics.get("avg_total_credits")),
        ("Average monthly running costs", avg("operating_expenses"), metrics.get("avg_operating_expenses")),
        ("Average monthly GST turnover", truth["avg_gst_turnover"], metrics.get("avg_gst_turnover")),
        ("Existing EMIs", truth["active_emi_total"], metrics.get("existing_emi")),
        ("Outstanding on running loans", truth["active_outstanding_total"], metrics.get("outstanding_total")),
        ("EMI returns in 12 months", truth["emi_returns"], metrics.get("emi_returns_12m")),
        ("Late GST filings", truth["late_gst_filings"], metrics.get("late_gst_filings")),
    ]
    return {
        "case_id": case["id"], "scenario_id": case["scenario_id"],
        "note": "Ground truth is the synthetic dataset the PDFs were generated from. The investigation only reads the "
                "PDFs. Credits it could not identify are left out of sales until the borrower confirms them.",
        "deliberate_discrepancies": truth["deliberate_discrepancies"],
        "comparison": [{"metric": name, "ground_truth": t, "investigated": i,
                        "match": None if i is None or t is None else same(t, i),
                        "note": (f"An advisor later corrected this to {result['metrics'][keys[name]]}."
                                 if keys.get(name) in corrected else None)}
                       for name, t, i in pairs],
    }
