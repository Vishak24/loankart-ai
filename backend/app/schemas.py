"""Pydantic API schemas. Enum values are stable codes; display labels live in the frontend i18n layer."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_AMOUNT = 1_000_000_000  # ₹100 crore: sanity ceiling against typos, not a lending rule


class Industry(str, Enum):
    retail_trading = "retail_trading"
    wholesale_distribution = "wholesale_distribution"
    manufacturing = "manufacturing"
    services = "services"
    food_hospitality = "food_hospitality"
    transport_logistics = "transport_logistics"
    construction = "construction"
    agriculture = "agriculture"
    healthcare = "healthcare"
    other = "other"


class LoanPurpose(str, Enum):
    working_capital = "working_capital"
    inventory = "inventory"
    machinery_equipment = "machinery_equipment"
    business_expansion = "business_expansion"
    debt_consolidation = "debt_consolidation"
    other = "other"


class Collateral(str, Enum):
    none = "none"
    residential_property = "residential_property"
    commercial_property = "commercial_property"
    machinery = "machinery"
    gold = "gold"
    fixed_deposit = "fixed_deposit"
    other = "other"


class GstStatus(str, Enum):
    registered = "registered"
    not_registered = "not_registered"
    not_sure = "not_sure"


class BusinessRegistration(str, Enum):
    unregistered = "unregistered"
    udyam_proprietorship = "udyam_proprietorship"
    partnership = "partnership"
    llp = "llp"
    private_limited = "private_limited"
    other = "other"


class RejectionReason(str, Enum):
    unknown = "unknown"
    credit_score = "credit_score"
    existing_obligations = "existing_obligations"
    insufficient_income_proof = "insufficient_income_proof"
    business_vintage = "business_vintage"
    documentation = "documentation"
    other = "other"


class BorrowerProfile(BaseModel):
    """Everything collected during onboarding. Used for both create (POST) and full replace (PUT)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    borrower_name: str = Field(min_length=2, max_length=100)
    business_name: str = Field(min_length=2, max_length=150)
    industry: Industry
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=80)
    business_vintage_years: float = Field(ge=0, le=100)
    requested_amount: int = Field(gt=0, le=MAX_AMOUNT)
    loan_purpose: LoanPurpose
    monthly_revenue: int = Field(ge=0, le=MAX_AMOUNT)
    monthly_expenses: int | None = Field(default=None, ge=0, le=MAX_AMOUNT)        # None = "I'm not sure"
    existing_loan_count: int = Field(ge=0, le=50)
    outstanding_loan_amount: int = Field(ge=0, le=MAX_AMOUNT)
    monthly_emi: int = Field(ge=0, le=MAX_AMOUNT)
    personal_monthly_income: int | None = Field(default=None, ge=0, le=MAX_AMOUNT)  # None = "I'm not sure"
    collateral: Collateral
    collateral_value: int | None = Field(default=None, ge=0, le=MAX_AMOUNT)         # None = unknown / no security
    gst_status: GstStatus
    business_registration: BusinessRegistration
    previously_rejected: bool
    rejection_reason: RejectionReason | None = None
    rejection_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_consistency(self) -> "BorrowerProfile":
        if self.existing_loan_count == 0 and (self.outstanding_loan_amount or self.monthly_emi):
            raise ValueError("outstanding_loan_amount and monthly_emi must be 0 when existing_loan_count is 0")
        if self.existing_loan_count > 0 and self.outstanding_loan_amount == 0:
            raise ValueError("outstanding_loan_amount must be greater than 0 when there are existing loans")
        if self.previously_rejected and self.rejection_reason is None:
            raise ValueError("rejection_reason is required when previously_rejected is true (use 'unknown' if not known)")
        if not self.previously_rejected and (self.rejection_reason is not None or self.rejection_note):
            raise ValueError("rejection_reason and rejection_note must be empty when previously_rejected is false")
        return self


class BorrowerOut(BorrowerProfile):
    model_config = ConfigDict(extra="ignore")

    id: str
    is_synthetic: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "BorrowerOut":
        return cls.model_validate(
            {
                **record["profile"],
                "id": record["id"],
                "is_synthetic": record["is_demo"],
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            }
        )


class HealthOut(BaseModel):
    status: str
    database: str


# ================================================================================================
# Case workflow contracts. frontend/src/api/schema.d.ts is generated from these (npm run gen:types).
# Rupee amounts are whole-rupee integers; ratios are 2-decimal numbers computed with Decimal.
# ================================================================================================

Severity = Literal["high", "medium", "low", "info"]
VerificationState = Literal["confirmed_in_document", "evidence_suggests", "requires_confirmation"]
# Source-of-truth labels shown beside every figure (blueprint trust model).
ValueState = Literal["verified", "extracted", "declared", "confirmed", "corrected", "calculated", "missing", "simulated"]


class Narrative(BaseModel):
    """AI-written text. Never a source of figures or lender decisions."""
    headline: str = Field(max_length=300)
    body: str = Field(max_length=4000)
    caveats: list[str] = Field(default_factory=list, max_length=8)
    provider: str = "mock"
    mode: Literal["mock", "live"] = "mock"
    fallback: bool = False            # True when a live provider failed and the safe mock text was used
    generated_at: str | None = None


class Consents(BaseModel):
    analyse_documents: bool = False
    paytm_evidence: bool = False
    share_with_lender: bool = False


class ConsentIn(BaseModel):
    key: Literal["analyse_documents", "paytm_evidence", "share_with_lender"]
    granted: bool


class Escalation(BaseModel):
    status: Literal["none", "open", "resolved"] = "none"
    reason: str | None = None
    summary: Narrative | None = None
    raised_at: str | None = None
    resolution: str | None = None


class CaseCreate(BaseModel):
    borrower_id: str
    intent: Literal["new", "rejected"] = "new"


class CaseOut(BaseModel):
    id: str
    borrower_id: str
    scenario_id: str | None
    is_synthetic: bool
    intent: str
    borrower: BorrowerProfile
    stages: dict[str, Literal["locked", "available", "in_progress", "complete"]]
    consents: Consents
    escalation: Escalation
    ai_mode: Literal["mock", "live"]
    created_at: str
    updated_at: str


class Check(BaseModel):
    name: str
    ok: bool


class DocumentOut(BaseModel):
    id: str
    case_id: str
    doc_type: str | None
    group: str
    title: str
    period: str | None
    filename: str
    source: Literal["synthetic", "upload"]
    status: Literal["loaded", "extracted", "unrecognised", "failed"]
    url: str
    warnings: list[str]
    checks: list[Check]


class TaskOut(BaseModel):
    key: str
    group: str
    title: str
    status: Literal["queued", "running", "complete", "needs_input", "failed"]
    started_at: str | None = None
    finished_at: str | None = None
    output: str = ""


class EvidenceRef(BaseModel):
    document_id: str
    document_title: str
    locator: str
    value: str


class Feedback(BaseModel):
    action: str
    note: str = ""
    by: str
    at: str


class FindingOut(BaseModel):
    id: str
    category: str
    title: str
    severity: Severity
    verification_state: VerificationState
    verification_label: str
    explanation: str
    figures: dict[str, Any]
    evidence: list[EvidenceRef]
    source_documents: list[str]
    unresolved_questions: list[str]
    next_action: str
    dimension: str | None
    feedback: Feedback | None = None          # borrower: confirm / not relevant
    advisor_review: Feedback | None = None    # advisor: accept / reject


class Option(BaseModel):
    code: str
    label: str


class ClarificationOut(BaseModel):
    id: str
    question: str
    why: str
    options: list[Option]
    answer: str | None
    finding_id: str | None = None
    free_text: bool = False


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=500)


class FeedbackIn(BaseModel):
    action: Literal["confirm", "not_relevant"]
    note: str = Field(default="", max_length=500)


class HeadlineValue(BaseModel):
    key: str
    label: str
    value: float | None
    unit: Literal["inr", "count", "ratio", "pct"]
    state: ValueState
    state_label: str
    source: str
    original: float | None = None
    corrected_by: str | None = None


class ReconLine(BaseModel):
    item: str
    source_a: str
    value_a: float | None
    source_b: str
    value_b: float | None
    variance_pct: float | None
    status: Literal["matched", "variance", "missing"]
    note: str


class MonthRow(BaseModel):
    month: str
    total_credits: int | None
    total_debits: int | None
    business_receipts: int
    cash_deposits: int
    paytm_settlements: int
    non_business_credits: int
    unclassified_credits: int
    operating_expenses: int
    loan_repayments: int
    owner_drawings: int
    operating_surplus: int
    closing_balance: int | None
    gst_taxable: int | None
    gst_gross: int | None
    document_id: str


class Obligation(BaseModel):
    account_no: str
    lender: str
    product: str
    emi: int
    months_seen: int
    last_seen: str | None
    status: Literal["active", "ended"]
    documented: bool
    outstanding: int | None
    remaining_months: int | None
    rate: float | None
    secured: bool | None
    principal: int | None
    document_id: str


class MissingDocument(BaseModel):
    doc_type: str
    label: str
    reason: str


class UnusualTransaction(BaseModel):
    date: str
    narration: str
    amount: int
    why: str
    document_id: str


class LenderSnapshot(BaseModel):
    lenders_evaluated: int
    products_evaluated: int
    viable: int
    fit_in_full: int
    text: str


class InvestigationOut(BaseModel):
    status: Literal["not_started", "running", "complete", "failed"]
    tasks: list[TaskOut]
    pacing_note: str
    headline: list[HeadlineValue] = []
    metrics: dict[str, Any] = {}
    months: list[MonthRow] = []
    reconciliation: list[ReconLine] = []
    findings: list[FindingOut] = []
    clarifications: list[ClarificationOut] = []
    obligations: list[Obligation] = []
    missing_documents: list[MissingDocument] = []
    unusual: list[UnusualTransaction] = []
    lender_snapshot: LenderSnapshot | None = None
    summary: Narrative | None = None
    error: str | None = None


class EmiIn(BaseModel):
    principal: int = Field(gt=0, le=MAX_AMOUNT)
    annual_rate_pct: float = Field(ge=0, le=100)
    months: int = Field(ge=1, le=480)
    upfront_fees: int = Field(default=0, ge=0)


class ScheduleRow(BaseModel):
    month: int
    opening: int
    emi: int
    interest: int
    principal: int
    closing: int


class EmiOut(BaseModel):
    emi: int
    total_repayment: int
    total_interest: int
    apr_pct: float
    schedule: list[ScheduleRow]


class LiabilityAction(BaseModel):
    action: Literal["keep", "refinance", "consolidate"] = "keep"
    rate: float | None = Field(default=None, ge=0, le=60)
    tenure: int | None = Field(default=None, ge=6, le=120)


Category = Literal["working_capital", "term_loan", "lap", "secured_business", "unsecured_business", "equipment"]
Priority = Literal["balanced", "lowest_emi", "lowest_cost", "no_collateral", "fastest"]


class RestructureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int = Field(gt=0, le=MAX_AMOUNT)
    tenure_months: int = Field(ge=6, le=180)
    liability_actions: dict[str, LiabilityAction] = {}
    offer_collateral: bool = True
    product_categories: list[Category] = []
    co_applicant_income: int = Field(default=0, ge=0, le=MAX_AMOUNT)
    include_paytm_evidence: bool = False


class PositionOut(BaseModel):
    fresh_funds: int
    loan_amount: int
    tenure_months: int
    existing_emi: int
    new_emi: int
    total_monthly_repayment: int
    total_repayment: int
    total_interest: int
    operating_surplus: int
    free_cash_after: int
    dscr: float | None
    illustrative_rate_pct: float
    products_fitting_in_full: int
    products_viable: int
    products_evaluated: int
    best_fresh_funds: int


class DimensionOut(BaseModel):
    key: str
    title: str
    relevant: bool
    why: str
    current: str
    proposed: str
    financial_impact: str
    emi_impact: int | None
    total_repayment_impact: int | None
    additional_costs: list[str]
    risks: list[str]
    required_evidence: list[str]
    lender_fit_before: int
    lender_fit_after: int
    lender_fit_example: str
    options: list[dict[str, Any]]
    applied: bool


class PaytmMonth(BaseModel):
    month: str
    gross_collections: int
    fees: int
    refunds: int
    net_settlements: int
    settlement_count: int
    bank_credits_matched: int


class PaytmSummary(BaseModel):
    source: str
    simulated: bool
    merchant_id: str
    months: list[PaytmMonth]
    total_gross: int
    total_net: int
    total_refunds: int
    avg_net_settlements: int
    settlements_per_month: float
    refund_rate_pct: float
    share_of_bank_receipts_pct: float
    trend_pct: float | None
    peak_month: str
    low_month: str
    reconciles_with_bank: bool
    notes: list[str]


class RestructureOut(BaseModel):
    inputs: RestructureInput
    saved: bool
    current: PositionOut
    proposed: PositionOut
    notes: list[str]
    dimensions: list[DimensionOut]
    assumptions: list[str]
    paytm: PaytmSummary | None


class LenderProduct(BaseModel):
    """A fictional lender policy. Editable in the demo control centre; every edit bumps `version`."""
    model_config = ConfigDict(extra="forbid")
    id: str
    lender_id: str
    lender_name: str
    lender_type: str
    product_name: str
    category: Category
    repayment_type: Literal["emi", "interest_only"]
    min_amount: int = Field(gt=0)
    max_amount: int = Field(gt=0)
    min_vintage_years: float = Field(ge=0)
    min_monthly_revenue: int = Field(ge=0)
    income_method: Literal["banking", "itr", "gst"]
    gst_margin_pct: float | None
    max_foir_pct: float | None
    min_dscr: float = Field(gt=0)
    max_active_loans: int
    max_bounces_12m: int
    max_late_gst_filings: int
    gst_required: bool
    allowed_purposes: list[str] | None
    turnover_multiple: float | None
    collateral_required: bool
    collateral_accepted: list[str]
    max_ltv_pct: float | None
    interest_rate_pct: float = Field(gt=0, le=60)
    processing_fee_pct: float = Field(ge=0, le=10)
    other_charges: int = Field(ge=0)
    min_tenure_months: int = Field(ge=1)
    max_tenure_months: int = Field(ge=1)
    allows_balance_transfer: bool
    allows_co_applicant: bool
    counter_offers: bool
    turnaround_days: int
    required_documents: list[str]
    exclusions: list[str]
    effective_date: str
    version: int
    verification_status: str
    source: str


class RuleCheck(BaseModel):
    rule: str
    label: str
    required: str
    actual: str
    status: Literal["pass", "fail", "unresolved"]


class PolicySource(BaseModel):
    policy_version: int
    effective_date: str
    verification_status: str
    description: str


class ScoreFactor(BaseModel):
    key: str
    label: str
    score: float
    weight: int
    contribution: float


class HistoricalOutcome(BaseModel):
    product_id: str
    similar_cases: int
    offers: int
    label: str
    note: str


class KnowledgeEntry(BaseModel):
    """Practical expert knowledge. Kept apart from official lender policy; active only once approved."""
    id: str
    status: Literal["candidate", "approved", "rejected"]
    version: int
    problem: str
    reasoning: str
    lender_name: str | None
    product_id: str | None
    intervention: str
    outcome: str
    conditions: list[str]
    scope: str
    source: str
    case_id: str | None
    author: str
    approver: str | None
    verification_status: str
    structured_by: str
    created_at: str
    updated_at: str


class OptionOut(BaseModel):
    product_id: str
    lender_name: str
    lender_type: str
    product_name: str
    category: str
    decision: str
    decision_label: str
    explanation: str
    rules: list[RuleCheck]
    source: PolicySource
    rank: int
    score: float
    score_factors: list[ScoreFactor]
    status_label: str
    suggested_amount: int
    fresh_funds: int
    takeover_amount: int
    monthly_payment: int
    repayment_type: str
    rate_pct: float
    apr_pct: float
    tenure_months: int
    total_repayment: int
    total_interest: int
    fees: int
    processing_fee_pct: float
    other_charges: int
    dscr_after: float | None
    foir_after_pct: float | None
    ltv_pct: float | None
    existing_emi_after: int
    eligibility_fit: str
    required_changes: list[str]
    risks: list[str]
    supporting_evidence: list[str]
    unresolved_conditions: list[str]
    exclusions: list[str]
    notes: list[str]
    turnaround_days: int
    expert_notes: list[KnowledgeEntry]
    historical_outcomes: HistoricalOutcome | None
    ai_commentary: Narrative | None
    simulated_status: str


class UnsuitableOut(BaseModel):
    product_id: str
    lender_name: str
    lender_type: str
    product_name: str
    category: str
    decision: str
    decision_label: str
    explanation: str
    rules: list[RuleCheck]
    source: PolicySource
    reason: str
    max_supported_amount: int


class RankingFactor(BaseModel):
    key: str
    label: str
    weight: int


class Ranking(BaseModel):
    basis: str
    factors: list[RankingFactor]
    minimum_coverage_pct: int


class BlockingReason(BaseModel):
    reason: str
    products: int


class RecoveryPlan(BaseModel):
    headline: str
    blocking_reasons: list[BlockingReason]
    steps: list[str]


class RecommendationsOut(BaseModel):
    priority: Priority
    priority_label: str
    ranking: Ranking
    requested_amount: int
    tenure_months: int
    lenders_evaluated: int
    products_evaluated: int
    options: list[OptionOut]
    unsuitable: list[UnsuitableOut]
    recovery_plan: RecoveryPlan | None
    labels: dict[str, str]
    selected_product_id: str | None


class SelectionIn(BaseModel):
    product_id: str
    priority: Priority = "balanced"


class ChecklistItem(BaseModel):
    id: str
    group: str
    label: str
    status: Literal["on_file", "missing", "to_provide"]
    detail: str
    required_by_lender: bool


class Checkpoint(BaseModel):
    key: str
    label: str
    done: bool


class CheckpointIn(BaseModel):
    key: str
    done: bool


class ProposalOut(BaseModel):
    status: Literal["draft", "ready", "submitted"]
    disclaimer: str
    option: OptionOut
    facts_used: list[HeadlineValue]
    structure: list[Option]
    assumptions: list[str]
    checklist: list[ChecklistItem]
    unresolved: list[str]
    checkpoints: list[Checkpoint]
    summary: Narrative | None
    pdf_url: str
    created_at: str


class QueryOut(BaseModel):
    id: str
    text: str
    routine: bool
    status: Literal["open", "answered"]
    draft: Narrative | None
    response: str | None
    raised_at: str


class OfferOut(BaseModel):
    label: str
    amount: int
    rate_pct: float
    tenure_months: int
    monthly_payment: int
    repayment_type: str
    fees: int
    apr_pct: float
    total_repayment: int
    validity: str
    conditions: list[str]


class EventOut(BaseModel):
    id: int
    case_id: str | None
    kind: str
    actor: str
    title: str
    detail: str
    simulated: bool
    created_at: str


ApplicationStatus = Literal["draft", "ready", "submitted", "under_review", "query_raised", "info_supplied",
                            "offer_generated", "rejected", "human_review"]


class ApplicationOut(BaseModel):
    status: ApplicationStatus
    status_label: str
    simulated: bool
    banner: str
    reference: str | None
    lender_name: str | None
    product_name: str | None
    queries: list[QueryOut]
    offer: OfferOut | None
    decision_label: str | None
    decision_explanation: str | None
    failed_rules: list[RuleCheck]
    next_step: str
    events: list[EventOut]


class QueryResponseIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


class EscalateIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AdvisorCaseRow(BaseModel):
    case_id: str
    borrower_name: str
    business_name: str
    city: str
    requested_amount: int
    is_synthetic: bool
    stage: str
    status: Literal["open", "escalated", "unresolved", "resolved"]
    blocker: str
    open_items: int
    application_status: str | None
    updated_at: str


class AdvisorComment(BaseModel):
    note: str
    by: str
    at: str
    kind: str


class AdvisorActionIn(BaseModel):
    type: Literal["review_finding", "correct_value", "comment", "request_clarification", "review_solution", "resolve"]
    target: str | None = None
    decision: Literal["accept", "reject"] | None = None
    value: float | None = None
    note: str = Field(default="", max_length=1000)


class AdvisorCaseDetail(BaseModel):
    case: CaseOut
    investigation: InvestigationOut
    restructure: RestructureOut | None
    recommendations: RecommendationsOut | None
    application: ApplicationOut | None
    comments: list[AdvisorComment]
    solution_review: Feedback | None
    correctable: list[str]
    audit: list[EventOut]


class KnowledgeCaptureIn(BaseModel):
    text: str = Field(min_length=20, max_length=4000)
    case_id: str | None = None
    author: str = Field(default="Advisor", max_length=80)
    source: Literal["text", "voice"] = "text"


class KnowledgeReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    approver: str = Field(default="Senior advisor", max_length=80)


class TranscriptOut(BaseModel):
    text: str
    provider: str
    mode: Literal["mock", "live"]
    fallback: bool


class TranslateIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    target_language: Literal["ta-IN", "en-IN", "hi-IN"] = "ta-IN"


class ProviderStatus(BaseModel):
    name: str
    purpose: str
    configured: bool
    model: str
    state: Literal["mock", "ready", "not_configured", "ok", "error", "not_available"]
    detail: str


class AIStatus(BaseModel):
    mode: Literal["mock", "live"]
    effective_mode: Literal["mock", "live"]
    note: str
    providers: list[ProviderStatus]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=200)


class SessionOut(BaseModel):
    advisor: bool
    environment: Literal["development", "production"]
    public_demo: bool        # may a visitor open the shared synthetic demo case?
    demo_tools: bool         # are the demo-control endpoints present on this server?


class AIModeIn(BaseModel):
    mode: Literal["mock", "live"]


class ScenarioOut(BaseModel):
    id: str
    title: str
    tests: str
    primary: bool
    case_id: str
    loaded: bool
    borrower_name: str
    business_name: str


class DemoLoadIn(BaseModel):
    scenario_id: str


class DemoTriggerIn(BaseModel):
    case_id: str
    action: Literal["query", "rejection", "alternative_offer"]


class DemoCaseState(BaseModel):
    case_id: str
    business_name: str
    scenario_id: str | None
    investigation_status: str
    tasks: list[TaskOut]
    documents: int
    application_status: str | None
    escalation: str


class DemoState(BaseModel):
    ai_mode: Literal["mock", "live"]
    cases: list[DemoCaseState]
    application_events: list[EventOut]
    lenders: int
    products: int
    knowledge_entries: int


class TruthLine(BaseModel):
    metric: str
    ground_truth: float | None
    investigated: float | None
    match: bool | None
    note: str | None = None


class GroundTruthOut(BaseModel):
    case_id: str
    scenario_id: str | None
    note: str
    deliberate_discrepancies: str
    comparison: list[TruthLine]


class MessageOut(BaseModel):
    message: str
