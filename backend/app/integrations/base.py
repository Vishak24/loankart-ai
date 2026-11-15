"""Provider interfaces. The application depends on these, never on a vendor SDK directly."""

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from ..redact import redact


class ProviderError(Exception):
    """A provider call failed or returned something unusable. Callers fall back; they never crash.
    The message is scrubbed of credentials at creation, so it is safe to log, store and show."""

    def __init__(self, message: object = "") -> None:
        super().__init__(redact(message))


class NarrativeDraft(BaseModel):
    headline: str = Field(max_length=300)
    body: str = Field(max_length=4000)
    caveats: list[str] = Field(default_factory=list, max_length=8)


class KnowledgeDraft(BaseModel):
    problem: str = Field(max_length=600)
    reasoning: str = Field(max_length=1200)
    lender_name: str | None = None
    product_name: str | None = None
    intervention: str = Field(max_length=800)
    outcome: str = Field(max_length=600)
    conditions: list[str] = Field(default_factory=list, max_length=8)
    scope: str = Field(max_length=300)


SYSTEM_PROMPT = """You write short, plain-English explanations for LoanKart.ai, a tool that helps small-business \
borrowers in India understand a loan rejection and their financing options. Your readers are business owners, \
not finance professionals.

You are given structured evidence as JSON. It was produced by deterministic code: a document parser, a financial \
calculator and a simulated lender rule engine. Your job is only to explain it. Follow these rules because a wrong \
figure or an overstated claim could mislead someone making a financial decision:

- Use only facts and figures present in the evidence. Do not calculate new figures, round differently, or estimate.
- Do not state or imply any lender decision, eligibility result or ranking other than the ones in the evidence.
- A finding is a possible contributing factor unless its verification label says it is confirmed in a document. \
Never say this is why a lender rejected the application.
- If something is missing or unanswered in the evidence, say it is missing. Do not fill the gap.
- Lender results in the evidence come from a simulation with fictional lenders. Call them simulated or indicative. \
Never say approved, sanctioned, guaranteed or pre-approved.
- Never suggest altering, inventing or withholding documents.
- Write amounts exactly as they appear in the evidence."""

TASKS = {
    "diagnosis_summary": "Summarise what the investigation found: the two or three findings that matter most, what is "
                         "confirmed versus uncertain, and what the borrower can do next. Under 140 words in the body.",
    "recommendation_commentary": "Explain in under 110 words why the top-ranked option scored highest under the disclosed "
                                 "ranking factors, and name its main trade-off. This is commentary, not a new ranking.",
    "proposal_summary": "Write a covering summary for a draft financing proposal: who the borrower is, what is being "
                        "requested from which simulated lender, and the documented figures that support it. Under 150 words.",
    "query_response": "Draft the borrower's reply to the lender query in the evidence, using only the documented facts "
                      "provided. First person, factual, under 110 words. Put the reply in the body.",
    "escalation_summary": "Summarise this case for a human loan advisor taking it over: what is understood, what is "
                          "unresolved, and why it was escalated. Under 150 words.",
    "knowledge_candidate": "An advisor has described how a case was solved. Structure it into the fields requested. "
                           "Keep it specific to the situation described: record the conditions under which it applied "
                           "and do not turn one case into a general rule.",
}
SCHEMAS: dict[str, type[BaseModel]] = {task: NarrativeDraft for task in TASKS} | {"knowledge_candidate": KnowledgeDraft}


class ReasoningProvider(Protocol):
    name: str

    def generate(self, task: str, context: dict[str, Any]) -> BaseModel: ...


class SpeechProvider(Protocol):
    name: str

    def transcribe(self, audio: bytes, filename: str) -> str: ...

    def synthesize(self, text: str, language_code: str) -> bytes: ...


class TranslationProvider(Protocol):
    name: str

    def translate(self, text: str, target_language_code: str) -> str: ...


class DocumentProvider(Protocol):
    name: str

    def extract_text(self, path: Path) -> list[str]: ...
