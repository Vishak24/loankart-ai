"""HTTP routes for the case workflow. Thin: validate, call a service, shape the response. No business rules."""

import logging
import sqlite3
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

from . import advisors, calculations as calc, db, environment, investigation, schemas as s, security, services, workflow
from .config import Settings
from .demo_data import DEMO_BORROWER_ID
from .errors import BadInput, Conflict, Forbidden, NotFound, Unauthorized
from .security import (
    ai_limit, borrower_access, case_access, create_limit, document_access, get_conn, get_settings, login_limit,
    require_advisor, require_demo_admin, require_session, upload_limit,
)
from .integrations import AIService
from .integrations.base import ProviderError
from .synthetic import PRIMARY_SCENARIO, SCENARIOS

router = APIRouter(prefix="/api")
log = logging.getLogger("loankart")


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Cfg = Annotated[Settings, Depends(get_settings)]


Advisor = Annotated[str, Depends(require_advisor)]


def _inv(case: dict[str, Any], cfg: Settings) -> dict[str, Any]:
    return investigation.view(case, cfg.pacing_ms)


# ---------------------------------------------------------------------------------------------- sessions

def _session_out(cfg: Settings, advisor: bool) -> dict[str, Any]:
    return {"advisor": advisor, "environment": cfg.environment, "public_demo": cfg.public_demo, "demo_tools": cfg.demo_tools}


@router.get("/auth/me", response_model=s.SessionOut, tags=["auth"])
def whoami(request: Request, cfg: Cfg) -> Any:
    return _session_out(cfg, security.session_of(request).advisor)


@router.post("/auth/advisor/login", response_model=s.SessionOut, tags=["auth"], dependencies=[login_limit])
def advisor_login(body: s.LoginIn, request: Request, response: Response, conn: Conn, cfg: Cfg) -> Any:
    if not cfg.advisor_password:
        raise Unauthorized("Advisor sign-in is not set up on this server. Run scripts/set_advisor_password.py, then restart.")
    if not security.passcode_matches(cfg, body.password):
        log.info("advisor sign-in failed")
        db.add_event(conn, "audit", "Advisor sign-in failed", actor="unknown", detail=f"from {security.client_ip(request)}")
        raise Unauthorized("Incorrect passcode.")
    security.grant_advisor(request, response)
    log.info("advisor signed in")
    db.add_event(conn, "audit", "Advisor signed in", actor="advisor")
    return _session_out(cfg, True)


@router.post("/auth/logout", response_model=s.SessionOut, tags=["auth"])
def logout(request: Request, response: Response, conn: Conn, cfg: Cfg) -> Any:
    if security.session_of(request).advisor:
        log.info("advisor signed out")
        db.add_event(conn, "audit", "Advisor signed out", actor="advisor")
    security.clear_sessions(response)
    return _session_out(cfg, False)


# ---------------------------------------------------------------------------------------------- borrowers (milestone 1)

def _shared_demo(request: Request, response: Response, cfg: Settings) -> None:
    """The shared synthetic demo case: open to any visitor when the deployment allows it, otherwise to advisors only."""
    if security.session_of(request).advisor:
        return
    if not cfg.public_demo:
        raise Forbidden("The shared demo case is not available on this server.")
    security.grant_borrower(request, response, DEMO_BORROWER_ID)


@router.get("/demo/borrower", response_model=s.BorrowerOut, tags=["borrowers"])
def get_demo(conn: Conn, request: Request, response: Response, cfg: Cfg) -> s.BorrowerOut:
    _shared_demo(request, response, cfg)
    environment.seed(conn)
    return services.get_borrower(conn, DEMO_BORROWER_ID)


@router.post("/borrowers", response_model=s.BorrowerOut, status_code=201, tags=["borrowers"], dependencies=[create_limit])
def create_borrower(body: s.BorrowerProfile, conn: Conn, request: Request, response: Response) -> s.BorrowerOut:
    created = services.create_borrower(conn, body)
    security.grant_borrower(request, response, created.id)         # the creator, and only the creator, may use this profile
    return created


@router.get("/borrowers/{borrower_id}", response_model=s.BorrowerOut, tags=["borrowers"], dependencies=[Depends(borrower_access)])
def get_borrower(borrower_id: str, conn: Conn) -> s.BorrowerOut:
    return services.get_borrower(conn, borrower_id)


@router.put("/borrowers/{borrower_id}", response_model=s.BorrowerOut, tags=["borrowers"], dependencies=[Depends(borrower_access)])
def update_borrower(borrower_id: str, body: s.BorrowerProfile, conn: Conn, cfg: Cfg) -> s.BorrowerOut:
    saved = services.update_borrower(conn, borrower_id, body)
    environment.profile_changed(conn, cfg, borrower_id)
    return saved


# ---------------------------------------------------------------------------------------------- cases and documents

@router.post("/cases", response_model=s.CaseOut, tags=["cases"], dependencies=[Depends(require_session)])
def open_case(body: s.CaseCreate, conn: Conn, cfg: Cfg, request: Request) -> Any:
    borrower_access(request, body.borrower_id)
    return workflow.case_out(conn, cfg, environment.ensure_case(conn, body.borrower_id, body.intent))


@router.get("/cases/{case_id}", response_model=s.CaseOut, tags=["cases"], dependencies=[Depends(case_access)])
def get_case(case_id: str, conn: Conn, cfg: Cfg) -> Any:
    return workflow.case_out(conn, cfg, environment.get_case(conn, case_id))


@router.post("/cases/{case_id}/consents", response_model=s.CaseOut, tags=["cases"], dependencies=[Depends(case_access)])
def set_consent(case_id: str, body: s.ConsentIn, conn: Conn, cfg: Cfg) -> Any:
    case = workflow.set_consent(conn, environment.get_case(conn, case_id), body.key, body.granted)
    return workflow.case_out(conn, cfg, case)


@router.post("/cases/{case_id}/escalate", response_model=s.CaseOut, tags=["cases"], dependencies=[Depends(case_access), ai_limit])
def escalate(case_id: str, body: s.EscalateIn, conn: Conn, cfg: Cfg) -> Any:
    return workflow.case_out(conn, cfg, workflow.escalate(conn, cfg, environment.get_case(conn, case_id), body.reason))


@router.get("/cases/{case_id}/documents", response_model=list[s.DocumentOut], tags=["documents"], dependencies=[Depends(case_access)])
def list_documents(case_id: str, conn: Conn) -> Any:
    environment.get_case(conn, case_id)
    return [workflow.document_out(d) for d in db.list_documents(conn, case_id)]


@router.post("/cases/{case_id}/documents/synthetic", response_model=list[s.DocumentOut], tags=["documents"], dependencies=[Depends(case_access)])
def load_synthetic_documents(case_id: str, conn: Conn, cfg: Cfg) -> Any:
    """Generate the synthetic document pack (real PDF files) for this case."""
    environment.load_documents(conn, cfg, environment.get_case(conn, case_id))
    return [workflow.document_out(d) for d in db.list_documents(conn, case_id)]


@router.post("/cases/{case_id}/documents", response_model=s.DocumentOut, status_code=201, tags=["documents"], dependencies=[Depends(case_access), upload_limit])
def upload_document(case_id: str, conn: Conn, cfg: Cfg, file: Annotated[UploadFile, File()]) -> Any:
    content = file.file.read(environment.MAX_UPLOAD_BYTES + 1)
    doc = environment.add_upload(conn, cfg, environment.get_case(conn, case_id), file.filename or "document.pdf", content)
    return workflow.document_out(doc)


@router.get("/documents/{doc_id}/file", tags=["documents"], response_class=FileResponse, dependencies=[Depends(document_access)])
def document_file(doc_id: str, conn: Conn, cfg: Cfg) -> FileResponse:
    path, filename = environment.document_path(conn, cfg, doc_id)
    return FileResponse(path, media_type="application/pdf", filename=filename, content_disposition_type="inline")


# ---------------------------------------------------------------------------------------------- investigation

@router.post("/cases/{case_id}/investigation/run", response_model=s.InvestigationOut, status_code=202, tags=["investigation"], dependencies=[Depends(case_access), ai_limit])
def run_investigation(case_id: str, conn: Conn, cfg: Cfg, background: BackgroundTasks) -> Any:
    case = environment.get_case(conn, case_id)
    run_id = investigation.start(conn, case)
    background.add_task(investigation.run, cfg, case_id, run_id, environment.profile_of(conn, case))
    return _inv(environment.get_case(conn, case_id), cfg)


@router.get("/cases/{case_id}/investigation", response_model=s.InvestigationOut, tags=["investigation"], dependencies=[Depends(case_access)])
def get_investigation(case_id: str, conn: Conn, cfg: Cfg) -> Any:
    return _inv(environment.get_case(conn, case_id), cfg)


@router.post("/cases/{case_id}/clarifications/{clarification_id}", response_model=s.InvestigationOut, tags=["investigation"], dependencies=[Depends(case_access)])
def answer_clarification(case_id: str, clarification_id: str, body: s.AnswerIn, conn: Conn, cfg: Cfg) -> Any:
    return _inv(workflow.answer(conn, environment.get_case(conn, case_id), clarification_id, body.answer), cfg)


@router.post("/cases/{case_id}/findings/{finding_id}/feedback", response_model=s.InvestigationOut, tags=["investigation"], dependencies=[Depends(case_access)])
def finding_feedback(case_id: str, finding_id: str, body: s.FeedbackIn, conn: Conn, cfg: Cfg) -> Any:
    case = workflow.finding_feedback(conn, environment.get_case(conn, case_id), finding_id, body.action, body.note)
    return _inv(case, cfg)


@router.post("/cases/{case_id}/investigation/explain", response_model=s.InvestigationOut, tags=["investigation"], dependencies=[Depends(case_access), ai_limit])
def explain_investigation(case_id: str, conn: Conn, cfg: Cfg) -> Any:
    """Ask the AI provider for a plain-language summary of the findings. Text only; no figures are changed."""
    return _inv(workflow.explain_findings(conn, cfg, environment.get_case(conn, case_id)), cfg)


# ---------------------------------------------------------------------------------------------- calculations, restructuring

@router.post("/calculations/emi", response_model=s.EmiOut, tags=["calculations"])
def calculate_emi(body: s.EmiIn) -> Any:
    try:
        cost = calc.loan_cost(body.principal, body.annual_rate_pct, body.months)
        return {**cost, "apr_pct": calc.apr(body.principal, body.annual_rate_pct, body.months, body.upfront_fees),
                "schedule": calc.amortisation_schedule(body.principal, body.annual_rate_pct, body.months)}
    except ValueError as exc:
        raise BadInput(str(exc)) from exc


@router.get("/cases/{case_id}/restructure", response_model=s.RestructureOut, tags=["restructuring"], dependencies=[Depends(case_access)])
def get_restructure(case_id: str, conn: Conn, cfg: Cfg) -> Any:
    return workflow.restructure_view(conn, cfg, environment.get_case(conn, case_id))


@router.post("/cases/{case_id}/restructure/preview", response_model=s.RestructureOut, tags=["restructuring"], dependencies=[Depends(case_access)])
def preview_restructure(case_id: str, body: s.RestructureInput, conn: Conn, cfg: Cfg) -> Any:
    """Recalculate a scenario without saving it."""
    return workflow.restructure_view(conn, cfg, environment.get_case(conn, case_id), body.model_dump(mode="json"))


@router.put("/cases/{case_id}/restructure", response_model=s.RestructureOut, tags=["restructuring"], dependencies=[Depends(case_access)])
def save_restructure(case_id: str, body: s.RestructureInput, conn: Conn, cfg: Cfg) -> Any:
    return workflow.restructure_view(conn, cfg, environment.get_case(conn, case_id), body.model_dump(mode="json"), save=True)


# ---------------------------------------------------------------------------------------------- lenders, recommendations

@router.get("/lenders", response_model=list[s.LenderProduct], tags=["lenders"])
def list_lenders(conn: Conn) -> Any:
    return db.list_products(conn)


@router.put("/lenders/{product_id}", response_model=s.LenderProduct, tags=["lenders"])
def update_lender_product(product_id: str, body: s.LenderProduct, conn: Conn, role: Advisor) -> Any:
    current = next((p for p in db.list_products(conn) if p["id"] == product_id), None)
    if current is None or body.id != product_id:
        raise NotFound(f"Lender product '{product_id}' not found")
    if body.min_amount > body.max_amount or body.min_tenure_months > body.max_tenure_months:
        raise BadInput("Minimum cannot be above maximum.")
    product = {**body.model_dump(mode="json"), "version": current["version"] + 1}    # the server owns the version
    db.put_product(conn, product)
    db.add_event(conn, "audit", "Simulated lender policy edited", actor=role, detail=f"{product_id} v{product['version']}")
    return product


@router.get("/cases/{case_id}/recommendations", response_model=s.RecommendationsOut, tags=["recommendations"], dependencies=[Depends(case_access)])
def get_recommendations(case_id: str, conn: Conn, priority: Annotated[s.Priority | None, Query()] = None) -> Any:
    return workflow.recommendations_view(conn, environment.get_case(conn, case_id), priority)


@router.post("/cases/{case_id}/recommendations/explain", response_model=s.RecommendationsOut, tags=["recommendations"], dependencies=[Depends(case_access), ai_limit])
def explain_recommendations(case_id: str, conn: Conn, cfg: Cfg, priority: Annotated[s.Priority, Query()] = "balanced") -> Any:
    return workflow.explain_recommendation(conn, cfg, environment.get_case(conn, case_id), priority)


@router.post("/cases/{case_id}/selection", response_model=s.ProposalOut, tags=["proposal"], dependencies=[Depends(case_access)])
def select_option(case_id: str, body: s.SelectionIn, conn: Conn, cfg: Cfg) -> Any:
    case = workflow.select(conn, cfg, environment.get_case(conn, case_id), body.product_id, body.priority)
    return workflow.proposal_view(conn, case)


# ---------------------------------------------------------------------------------------------- proposal, application

@router.get("/cases/{case_id}/proposal", response_model=s.ProposalOut, tags=["proposal"], dependencies=[Depends(case_access)])
def get_proposal(case_id: str, conn: Conn) -> Any:
    return workflow.proposal_view(conn, environment.get_case(conn, case_id))


@router.post("/cases/{case_id}/proposal/checkpoints", response_model=s.ProposalOut, tags=["proposal"], dependencies=[Depends(case_access)])
def set_checkpoint(case_id: str, body: s.CheckpointIn, conn: Conn) -> Any:
    return workflow.proposal_view(conn, workflow.set_checkpoint(conn, environment.get_case(conn, case_id), body.key, body.done))


@router.get("/cases/{case_id}/proposal/pdf", tags=["proposal"], response_class=FileResponse, dependencies=[Depends(case_access)])
def proposal_pdf(case_id: str, conn: Conn, cfg: Cfg) -> FileResponse:
    path = workflow.proposal_pdf(conn, cfg, environment.get_case(conn, case_id))
    return FileResponse(path, media_type="application/pdf", filename=f"loankart-draft-proposal-{case_id}.pdf",
                        content_disposition_type="inline")


@router.get("/cases/{case_id}/application", response_model=s.ApplicationOut, tags=["application"], dependencies=[Depends(case_access)])
def get_application(case_id: str, conn: Conn) -> Any:
    return workflow.application_view(conn, environment.get_case(conn, case_id))


@router.post("/cases/{case_id}/application/submit", response_model=s.ApplicationOut, tags=["application"], dependencies=[Depends(case_access)])
def submit_application(case_id: str, conn: Conn) -> Any:
    return workflow.application_view(conn, workflow.submit(conn, environment.get_case(conn, case_id)))


@router.post("/cases/{case_id}/application/advance", response_model=s.ApplicationOut, tags=["application"], dependencies=[Depends(case_access)])
def advance_application(case_id: str, conn: Conn) -> Any:
    """Ask the lender simulator for its next step."""
    return workflow.application_view(conn, workflow.advance(conn, environment.get_case(conn, case_id)))


@router.post("/cases/{case_id}/application/queries/{query_id}/draft", response_model=s.ApplicationOut, tags=["application"], dependencies=[Depends(case_access), ai_limit])
def draft_query_response(case_id: str, query_id: str, conn: Conn, cfg: Cfg) -> Any:
    return workflow.application_view(conn, workflow.draft_query(conn, cfg, environment.get_case(conn, case_id), query_id))


@router.post("/cases/{case_id}/application/queries/{query_id}/respond", response_model=s.ApplicationOut, tags=["application"], dependencies=[Depends(case_access)])
def respond_to_query(case_id: str, query_id: str, body: s.QueryResponseIn, conn: Conn) -> Any:
    return workflow.application_view(conn, workflow.respond_query(conn, environment.get_case(conn, case_id), query_id, body.text))


# ---------------------------------------------------------------------------------------------- advisor

@router.get("/advisor/cases", response_model=list[s.AdvisorCaseRow], tags=["advisor"])
def advisor_queue(conn: Conn, role: Advisor,
                  status: Annotated[str | None, Query(pattern="^(all|open|escalated|unresolved|resolved)$")] = None) -> Any:
    return advisors.queue(conn, status)


@router.get("/advisor/cases/{case_id}", response_model=s.AdvisorCaseDetail, tags=["advisor"])
def advisor_case(case_id: str, conn: Conn, cfg: Cfg, role: Advisor) -> Any:
    return advisors.detail(conn, cfg, environment.get_case(conn, case_id))


@router.post("/advisor/cases/{case_id}/actions", response_model=s.AdvisorCaseDetail, tags=["advisor"])
def advisor_action(case_id: str, body: s.AdvisorActionIn, conn: Conn, cfg: Cfg, role: Advisor) -> Any:
    case = advisors.act(conn, environment.get_case(conn, case_id), body.model_dump())
    return advisors.detail(conn, cfg, case)


@router.get("/knowledge", response_model=list[s.KnowledgeEntry], tags=["knowledge"])
def list_knowledge(conn: Conn, role: Advisor) -> Any:
    return db.list_knowledge(conn)


@router.post("/knowledge", response_model=s.KnowledgeEntry, status_code=201, tags=["knowledge"], dependencies=[ai_limit])
def capture_knowledge(body: s.KnowledgeCaptureIn, conn: Conn, cfg: Cfg, role: Advisor) -> Any:
    return advisors.capture(conn, cfg, body.text, body.case_id, body.author, body.source)


@router.post("/knowledge/{entry_id}/review", response_model=s.KnowledgeEntry, tags=["knowledge"])
def review_knowledge(entry_id: str, body: s.KnowledgeReviewIn, conn: Conn, role: Advisor) -> Any:
    return advisors.review(conn, entry_id, body.decision, body.approver)


# ---------------------------------------------------------------------------------------------- AI providers

@router.get("/ai/status", response_model=s.AIStatus, tags=["ai"], dependencies=[Depends(require_session)])
def ai_status(conn: Conn, cfg: Cfg) -> Any:
    return AIService(cfg, conn).status()


@router.post("/ai/check", response_model=s.AIStatus, tags=["ai"], dependencies=[Depends(require_advisor), ai_limit])
def ai_check(conn: Conn, cfg: Cfg) -> Any:
    """Make one real, minimal call to each configured provider and report the result. Nothing is faked."""
    return AIService(cfg, conn).status(check=True)


@router.put("/ai/mode", response_model=s.AIStatus, tags=["ai"], dependencies=[Depends(require_advisor)])
def ai_mode(body: s.AIModeIn, conn: Conn, cfg: Cfg) -> Any:
    service = AIService(cfg, conn)
    service.set_mode(body.mode)
    return service.status()


@router.post("/ai/transcribe", response_model=s.TranscriptOut, tags=["ai"], dependencies=[ai_limit])
def transcribe(conn: Conn, cfg: Cfg, role: Advisor, file: Annotated[UploadFile, File()]) -> Any:
    audio = file.file.read(8 * 1024 * 1024 + 1)
    if len(audio) > 8 * 1024 * 1024:
        raise BadInput("The recording is larger than 8 MB.")
    return AIService(cfg, conn).transcribe(audio, file.filename or "note.wav")


@router.post("/ai/translate", response_model=s.TranscriptOut, tags=["ai"], dependencies=[Depends(require_session), ai_limit])
def translate(body: s.TranslateIn, conn: Conn, cfg: Cfg) -> Any:
    return AIService(cfg, conn).translate(body.text, body.target_language)


@router.post("/ai/speak", tags=["ai"], responses={200: {"content": {"audio/wav": {}}}}, response_class=Response,
             dependencies=[Depends(require_session), ai_limit])
def speak(body: s.TranslateIn, conn: Conn, cfg: Cfg) -> Response:
    try:
        return Response(AIService(cfg, conn).synthesize(body.text, body.target_language), media_type="audio/wav")
    except ProviderError as exc:
        raise Conflict(str(exc)) from exc


# ---------------------------------------------------------------------------------------------- demo control

@router.post("/demo/reset", response_model=s.BorrowerOut, tags=["demo"], dependencies=[Depends(require_demo_admin)])
def reset_demo(conn: Conn, cfg: Cfg) -> s.BorrowerOut:
    """One-click return to the known initial state."""
    environment.reset_all(conn, cfg)
    return services.get_borrower(conn, DEMO_BORROWER_ID)


@router.get("/demo/scenarios", response_model=list[s.ScenarioOut], tags=["demo"], dependencies=[Depends(require_demo_admin)])
def demo_scenarios(conn: Conn) -> Any:
    return [{"id": sid, "title": sc["title"], "tests": sc["tests"], "primary": sid == PRIMARY_SCENARIO,
             "case_id": environment.case_id_for(sid), "loaded": db.get_case(conn, environment.case_id_for(sid)) is not None,
             "borrower_name": sc["profile"]["borrower_name"], "business_name": sc["profile"]["business_name"]}
            for sid, sc in SCENARIOS.items()]


@router.post("/demo/load", response_model=s.CaseOut, tags=["demo"])
def demo_load(body: s.DemoLoadIn, conn: Conn, cfg: Cfg, request: Request, response: Response) -> Any:
    if body.scenario_id == PRIMARY_SCENARIO:
        _shared_demo(request, response, cfg)         # the landing page's "Open the demo case"
    else:
        require_demo_admin(request)                  # other scenarios are the presenter's tools
    case = environment.ensure_scenario_case(conn, body.scenario_id)
    environment.load_documents(conn, cfg, case)
    return workflow.case_out(conn, cfg, case)


@router.post("/demo/regenerate-documents/{case_id}", response_model=list[s.DocumentOut], tags=["demo"], dependencies=[Depends(require_demo_admin)])
def demo_regenerate(case_id: str, conn: Conn, cfg: Cfg) -> Any:
    environment.load_documents(conn, cfg, environment.get_case(conn, case_id), force=True)
    return [workflow.document_out(d) for d in db.list_documents(conn, case_id)]


@router.post("/demo/trigger", response_model=s.ApplicationOut, tags=["demo"], dependencies=[Depends(require_demo_admin)])
def demo_trigger(body: s.DemoTriggerIn, conn: Conn) -> Any:
    return workflow.application_view(conn, workflow.trigger(conn, environment.get_case(conn, body.case_id), body.action))


@router.get("/demo/state", response_model=s.DemoState, tags=["demo"], dependencies=[Depends(require_demo_admin)])
def demo_state(conn: Conn, cfg: Cfg) -> Any:
    cases = []
    for case in db.list_cases(conn):
        borrower = db.get_borrower(conn, case["borrower_id"])
        app = case["data"]["application"]
        cases.append({"case_id": case["id"], "business_name": borrower["profile"]["business_name"] if borrower else "?",
                      "scenario_id": case["scenario_id"], "investigation_status": case["data"]["investigation"]["status"],
                      "tasks": case["data"]["investigation"]["tasks"], "documents": len(db.list_documents(conn, case["id"])),
                      "application_status": workflow.STATUS_LABELS[app["status"]] if app else None,
                      "escalation": case["data"]["escalation"]["status"]})
    products = db.list_products(conn)
    return {"ai_mode": AIService(cfg, conn).mode, "cases": cases,
            "application_events": db.list_events(conn, kinds=("application",), limit=60),
            "lenders": len({p["lender_id"] for p in products}), "products": len(products),
            "knowledge_entries": len(db.list_knowledge(conn))}


@router.get("/demo/logs", response_model=list[s.EventOut], tags=["demo"], dependencies=[Depends(require_demo_admin)])
def demo_logs(conn: Conn, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> Any:
    return db.list_events(conn, kinds=("log", "audit"), limit=limit)


@router.get("/demo/ground-truth/{case_id}", response_model=s.GroundTruthOut, tags=["demo"], dependencies=[Depends(require_demo_admin)])
def demo_ground_truth(case_id: str, conn: Conn) -> Any:
    """Layer B against Layer C. For validating the investigation; the investigation itself never reads this."""
    return environment.ground_truth(conn, environment.get_case(conn, case_id))
