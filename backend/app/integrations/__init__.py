"""AI service: chooses mock or live providers, validates what they return, and always falls back safely.

Rules enforced here for every AI output:
  1. It must parse into the task's schema.
  2. Every figure it mentions must already be in the evidence it was given (no invented numbers).
  3. On any failure: one retry, then the other live provider if configured, then the deterministic mock text.
     The failure is logged; case state is never touched by a failed call.
"""

import json
import re
import sqlite3
from typing import Any

from .. import db
from ..config import Settings
from .base import ProviderError
from .mock import MockAIProvider

_BANNED = re.compile(r"\b(pre-?approved|guaranteed|sanctioned)\b", re.I)
_NEGATION = re.compile(r"\b(not|no|never|nothing|none|cannot|isn't|aren't|wasn't|without|nor)\b[^.!?]{0,40}$", re.I)


def claims_approval(text: str) -> bool:
    """True when approval language is used as a claim. Denying it ("this is not guaranteed") is allowed."""
    return any(not _NEGATION.search(text[:m.start()]) for m in _BANNED.finditer(text))


def _numbers(text: str) -> set[str]:
    """Digit runs of 4+ digits with separators removed: the figures that matter in a financial explanation."""
    return {n for n in (re.sub(r"[,\s]", "", m) for m in re.findall(r"\d[\d,]*\d", text)) if len(n) >= 4}


def ungrounded(output: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Figures in the output that do not appear anywhere in the evidence."""
    known = _numbers(json.dumps(context, ensure_ascii=False))
    return sorted(_numbers(json.dumps(output, ensure_ascii=False)) - known)


class AIService:
    def __init__(self, settings: Settings, conn: sqlite3.Connection) -> None:
        self.settings, self.conn, self.mock = settings, conn, MockAIProvider()

    # ---- mode

    @property
    def mode(self) -> str:
        return db.get_setting(self.conn, "ai_mode", self.settings.ai_mode) or "mock"

    def set_mode(self, mode: str) -> None:
        db.set_setting(self.conn, "ai_mode", mode)
        db.add_event(self.conn, "audit", f"AI mode set to {mode}", actor="demo-control")

    def _claude(self) -> Any:
        from .claude import ClaudeReasoningProvider
        return ClaudeReasoningProvider(self.settings.anthropic_api_key, self.settings.anthropic_model)

    def _sarvam_chat(self) -> Any:
        from .sarvam import SarvamChatProvider
        return SarvamChatProvider(self.settings.sarvam_api_key, self.settings.sarvam_chat_model)

    def _reasoners(self) -> list[Any]:
        """Live reasoning providers in order of preference. Empty when nothing is configured."""
        s = self.settings
        available = {"claude": self._claude if s.anthropic_api_key else None,
                     "sarvam": self._sarvam_chat if s.sarvam_api_key else None}
        order = ["sarvam", "claude"] if s.reasoning_provider == "sarvam" else ["claude", "sarvam"]
        return [available[name] for name in order if available[name]]

    def _log(self, title: str, detail: str, case_id: str | None = None) -> None:
        db.add_event(self.conn, "log", title, case_id=case_id, actor="ai-service", detail=detail[:600])

    # ---- reasoning

    def generate(self, task: str, context: dict[str, Any], case_id: str | None = None) -> dict[str, Any]:
        """Run a reasoning task. Returns the draft fields plus provider, mode, fallback."""
        meta = {"mode": self.mode, "fallback": False, "generated_at": db._now()}
        if self.mode == "live":
            for make in self._reasoners():
                for attempt in (1, 2):
                    try:
                        provider = make()
                        draft = provider.generate(task, context).model_dump()
                        loose = ungrounded(draft, context)
                        if loose:
                            raise ProviderError(f"Output mentioned figures not in the evidence: {', '.join(loose[:5])}")
                        if claims_approval(json.dumps(draft, ensure_ascii=False)):
                            raise ProviderError("Output used approval language that is not allowed for simulated results.")
                        return {**draft, **meta, "provider": provider.name}
                    except ProviderError as exc:
                        self._log(f"AI output rejected ({task}, attempt {attempt})", str(exc), case_id)
                    except Exception as exc:  # never let a provider problem reach the user as a crash
                        self._log(f"AI provider failure ({task})", f"{exc.__class__.__name__}: {exc}", case_id)
                        break
            meta["fallback"] = True
            if not self._reasoners():
                self._log("Live mode without credentials", "No ANTHROPIC_API_KEY or SARVAM_API_KEY; used mock text.", case_id)
        return {**self.mock.generate(task, context).model_dump(), **meta, "provider": "mock"}

    # ---- speech and translation

    def _speech(self) -> Any:
        from .sarvam import SarvamSpeechProvider
        s = self.settings
        return SarvamSpeechProvider(s.sarvam_api_key, s.sarvam_stt_model, s.sarvam_tts_model, s.sarvam_tts_speaker)

    def transcribe(self, audio: bytes, filename: str) -> dict[str, Any]:
        if self.mode == "live" and self.settings.sarvam_api_key:
            try:
                return {"text": self._speech().transcribe(audio, filename), "provider": "sarvam-speech", "mode": "live",
                        "fallback": False}
            except Exception as exc:
                self._log("Speech-to-text failed", str(exc))
                return {"text": self.mock.transcribe(audio, filename), "provider": "mock", "mode": "live", "fallback": True}
        return {"text": self.mock.transcribe(audio, filename), "provider": "mock", "mode": self.mode,
                "fallback": self.mode == "live"}

    def synthesize(self, text: str, language_code: str) -> bytes:
        if self.mode != "live" or not self.settings.sarvam_api_key:
            raise ProviderError("Text-to-speech needs live mode with a Sarvam API key.")
        return self._speech().synthesize(text, language_code)

    def translate(self, text: str, target: str) -> dict[str, Any]:
        if self.mode == "live" and self.settings.sarvam_api_key:
            from .sarvam import SarvamTranslationProvider
            try:
                out = SarvamTranslationProvider(self.settings.sarvam_api_key, self.settings.sarvam_translate_model).translate(text, target)
                return {"text": out, "provider": "sarvam-translate", "mode": "live", "fallback": False}
            except Exception as exc:
                self._log("Translation failed", str(exc))
        return {"text": text, "provider": "mock", "mode": self.mode, "fallback": True}

    def document_text(self, path: Any) -> list[str] | None:
        """Sarvam Vision text for a document, when enabled. None means: use the baseline parser."""
        s = self.settings
        if not (self.mode == "live" and s.sarvam_use_vision and s.sarvam_api_key):
            return None
        from .sarvam import SarvamDocumentProvider
        try:
            return SarvamDocumentProvider(s.sarvam_api_key).extract_text(path)
        except Exception as exc:
            self._log("Sarvam Vision failed; baseline parser used", str(exc))
            return None

    # ---- status and connectivity

    def _paytm_row(self, check: bool) -> dict[str, Any]:
        s = self.settings
        ready = bool(s.paytm_merchant_id and s.paytm_client_id and s.paytm_access_token)
        row = {"name": "Paytm merchant evidence", "purpose": "Supplementary payment and settlement evidence",
               "configured": ready, "model": "Settlement Summary API", "state": "not_available",
               "detail": "Synthetic fixture in use. The Settlement Summary request is implemented but not wired into "
                         "cases; it needs PAYTM_MERCHANT_ID, PAYTM_CLIENT_ID and PAYTM_ACCESS_TOKEN (production only)."}
        if ready and check:
            from .paytm import LivePaytmEvidence
            try:
                LivePaytmEvidence(s.paytm_merchant_id, s.paytm_client_id, s.paytm_access_token).settlement_summary("2026-11-01")
                row["detail"] = "Settlement Summary API answered. Cases still use the synthetic fixture."
            except Exception as exc:
                row["state"], row["detail"] = "error", str(exc)[:300]
                self._log("Connectivity check failed: Paytm", row["detail"])
        return row

    def status(self, check: bool = False) -> dict[str, Any]:
        s, mode = self.settings, self.mode

        def row(name: str, purpose: str, key: str, model: str, ping: Any = None) -> dict[str, Any]:
            state, detail = ("ready", "Credentials found. Not yet checked.") if key else (
                "not_configured", "No API key set. Mock responses are used.")
            if key and check and ping:
                try:
                    state, detail = "ok", ping()
                except Exception as exc:
                    state, detail = "error", str(exc)[:300]
                    self._log(f"Connectivity check failed: {name}", detail)
            elif key and check:
                detail = "Credentials found. No zero-cost check exists for this service; it is exercised on first use."
            return {"name": name, "purpose": purpose, "configured": bool(key), "model": model, "state": state, "detail": detail}

        def sarvam_translate_ping() -> str:
            from .sarvam import SarvamTranslationProvider
            return SarvamTranslationProvider(s.sarvam_api_key, s.sarvam_translate_model).ping()

        providers = [
            row("Claude (Anthropic)", "Explanations, summaries, proposal drafting", s.anthropic_api_key, s.anthropic_model,
                lambda: self._claude().ping()),
            row("Sarvam chat", "Conversational reasoning; second reasoning provider", s.sarvam_api_key, s.sarvam_chat_model,
                lambda: self._sarvam_chat().ping()),
            row("Sarvam translate", "Tamil and English localisation of explanations", s.sarvam_api_key,
                s.sarvam_translate_model, sarvam_translate_ping),
            row("Sarvam speech (Saaras / Bulbul)", "Voice capture for advisors; read-aloud", s.sarvam_api_key,
                f"{s.sarvam_stt_model} / {s.sarvam_tts_model}"),
            row("Sarvam Vision", "OCR for scanned documents (off unless LOANKART_USE_SARVAM_VISION=1)", s.sarvam_api_key,
                "doc-ai parse"),
            self._paytm_row(check),
            {"name": "Mock AI provider", "purpose": "Deterministic offline responses for every AI task", "configured": True,
             "model": "built-in", "state": "mock", "detail": "Always available."},
        ]
        live_ready = bool(self._reasoners())
        effective = "live" if mode == "live" and live_ready else "mock"
        note = {"mock": "Mock mode: no external calls are made.",
                "live": "Live mode: explanations come from the configured provider, checked against the evidence."}[effective]
        if mode == "live" and not live_ready:
            note = "Live mode is selected but no API key is configured, so mock responses are used."
        return {"mode": mode, "effective_mode": effective, "note": note, "providers": providers}
