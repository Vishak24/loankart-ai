"""MockAIProvider: deterministic, offline stand-in for every AI provider. The whole product works on it.

Text is assembled only from the structured evidence it is given, so it cannot introduce a figure or a claim.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .base import KnowledgeDraft, NarrativeDraft, ProviderError


def _first_sentence(text: str) -> str:
    return text.split(". ")[0].rstrip(".") + "."


class MockAIProvider:
    name = "mock"

    def generate(self, task: str, context: dict[str, Any]) -> BaseModel:
        return getattr(self, f"_{task}")(context)

    def _diagnosis_summary(self, c: dict[str, Any]) -> NarrativeDraft:
        main = [f for f in c["findings"] if f["severity"] in ("high", "medium")]
        if not main:
            return NarrativeDraft(headline="The documents did not show a clear problem",
                                  body="Nothing in the supplied documents stands out as a likely factor. "
                                       "The lender options page shows which simulated lenders fit as things stand.")
        body = " ".join(f"{i}. {f['title']} ({f['verification_label'].lower()})." for i, f in enumerate(main[:3], 1))
        if c.get("stated_reason"):
            body += f" The lender's letter says: \"{c['stated_reason']}\""
        body += " The next step is to test changes on the restructuring page and see which simulated lenders then fit."
        caveats = ["These are possible contributing factors, not the lender's confirmed reasons."]
        if c["open_questions"]:
            caveats.append(f"{c['open_questions']} question(s) still need your answer.")
        return NarrativeDraft(headline=f"{len(main)} possible factor(s) may have affected the application",
                              body=body, caveats=caveats)

    def _recommendation_commentary(self, c: dict[str, Any]) -> NarrativeDraft:
        o = c["option"]
        top = sorted(o["score_factors"], key=lambda f: -f["contribution"])[:2]
        body = (f"{o['lender_name']} {o['product_name']} ranks first under the \"{c['priority_label']}\" weighting with a "
                f"score of {o['score']}. Most of that comes from: " + "; ".join(f["label"].lower() for f in top) + ".")
        if o["risks"]:
            body += " Main trade-off: " + o["risks"][0]
        return NarrativeDraft(headline="Why this option ranks first", body=body,
                              caveats=["Commentary on the disclosed ranking. The ranking itself is calculated, not written by AI.",
                                       "Indicative match against simulated lender rules, not an offer."])

    def _proposal_summary(self, c: dict[str, Any]) -> NarrativeDraft:
        o = c["option"]
        body = (f"{c['business_name']}, {c['city']}, requests {o['amount_text']} from {o['lender_name']} under its "
                f"{o['product_name']} (simulated lender). Documented figures: " + "; ".join(c["facts"]) + ".")
        if o["required_changes"]:
            body += " The request reflects: " + " ".join(o["required_changes"])
        return NarrativeDraft(headline=f"Draft proposal: {o['product_name']}", body=body,
                              caveats=["Draft for review. Not a sanction letter."])

    def _query_response(self, c: dict[str, Any]) -> NarrativeDraft:
        facts = " ".join(f if f.endswith(".") else f + "." for f in c["evidence"][:3]) or "I do not have a document that answers this."
        return NarrativeDraft(headline="Draft reply", body=f"{facts} I can provide supporting documents on request.",
                              caveats=["Drafted from documents on file. Check it before sending."])

    def _escalation_summary(self, c: dict[str, Any]) -> NarrativeDraft:
        body = (f"{c['business_name']} asked for an advisor: \"{c['reason']}\". Investigation status: "
                f"{c['investigation_status']}. Main findings: " + ("; ".join(c["findings"][:4]) or "none recorded") + ". "
                f"Open items: {c['open_items']}. Application status: {c['application_status']}.")
        return NarrativeDraft(headline="Case handed to an advisor", body=body,
                              caveats=["The full investigation, documents and audit trail are attached to the case."])

    def _knowledge_candidate(self, c: dict[str, Any]) -> KnowledgeDraft:
        text, case = " ".join(c["text"].split()), c.get("case") or {}
        sentences = [s.strip() for s in text.replace("? ", ". ").split(". ") if s.strip()]
        return KnowledgeDraft(
            problem=_first_sentence(sentences[0]) if sentences else text[:200],
            reasoning=". ".join(sentences[1:-1])[:1100] or text[:600],
            lender_name=case.get("lender_name"), product_name=case.get("product_name"),
            intervention=(sentences[-2] if len(sentences) > 2 else text)[:700],
            outcome=(sentences[-1] if sentences else text)[:500],
            conditions=[x for x in (case.get("condition"),) if x] or ["Applies to the case it came from; confirm before reuse."],
            scope="Single case observation" + (f" ({case['business_name']})" if case.get("business_name") else ""))

    # ---- speech, translation, documents: nothing can be honestly faked, so the mock says so

    def transcribe(self, audio: bytes, filename: str) -> str:
        return ("[Mock transcript: live speech-to-text is not configured] We moved the borrower from an unsecured term "
                "loan to a gold-backed overdraft because the EMI on a term loan exceeded the monthly surplus. The "
                "interest-only line fitted the documented cash flow. The simulated lender made an offer after the "
                "EMI return was explained.")

    def synthesize(self, text: str, language_code: str) -> bytes:
        raise ProviderError("Text-to-speech needs live mode with a Sarvam API key.")

    def translate(self, text: str, target_language_code: str) -> str:
        raise ProviderError("Translation needs live mode with a Sarvam API key.")

    def extract_text(self, path: Path) -> list[str]:
        raise ProviderError("The mock provider does not read documents; the baseline parser does.")
