"""Sarvam AI adapters, via the official `sarvamai` SDK.

Method names, model IDs and parameters follow docs.sarvam.ai as read on 15 Nov 2026:
  chat        client.chat.completions(model="sarvam-105b", messages=[...])         -> choices[0].message.content
  STT         client.speech_to_text.transcribe(file=..., model="saaras:v4", mode="transcribe")   -> .transcript
  TTS         client.text_to_speech.convert(text=..., language_code=..., model="bulbul:v4-flash") -> .audios (base64 WAV)
  translate   client.text.translate(input=..., source_language_code=..., target_language_code=..., model=...)
  documents   client.doc_ai.parse(file=[(name, f, "application/pdf")], language="en-IN"),
              then get_status(job_id) and get_download_url(job_id) -> ZIP holding Markdown or HTML.
              (The docs page also shows output_format="md"; sarvamai 0.1.46 does not accept it, so both are handled.)
Every call here has been run against the live API with an invalid key and returns Sarvam's authentication error,
so the requests are well-formed. Nothing past authentication has been exercised: no credentials were available.
"""

import base64
import html
import io
import json
import re
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from .base import SCHEMAS, SYSTEM_PROMPT, TASKS, ProviderError


class _Sarvam:
    def __init__(self, api_key: str) -> None:
        from sarvamai import SarvamAI     # lazy: mock mode never needs the SDK

        self.client = SarvamAI(api_subscription_key=api_key)

    def _guard(self, call: Any, **kwargs: Any) -> Any:
        try:
            return call(**kwargs)
        except Exception as exc:  # the SDK raises typed ApiError subclasses; all map to one safe error here
            status = getattr(exc, "status_code", None)
            if status in (401, 403):
                raise ProviderError("Sarvam rejected the API key. Check SARVAM_API_KEY in backend/.env.") from exc
            raise ProviderError(f"Sarvam API error{f' {status}' if status else ''}: {str(exc)[:200]}") from exc


class SarvamChatProvider(_Sarvam):
    name = "sarvam-chat"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key)
        self.model = model

    def generate(self, task: str, context: dict[str, Any]) -> BaseModel:
        schema = SCHEMAS[task]
        prompt = (f"{TASKS[task]}\n\nReply with one JSON object only, no other text, matching this JSON schema:\n"
                  f"{json.dumps(schema.model_json_schema())}\n\n<evidence>\n{json.dumps(context, ensure_ascii=False)}\n</evidence>")
        response = self._guard(self.client.chat.completions, model=self.model, temperature=0.2,
                               messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}])
        text = response.choices[0].message.content or ""
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ProviderError("Sarvam chat did not return JSON.")
        try:
            return schema.model_validate_json(match.group())
        except ValidationError as exc:
            raise ProviderError(f"Sarvam chat returned JSON that does not match the schema: {exc.error_count()} error(s).") from exc

    def ping(self) -> str:
        self._guard(self.client.chat.completions, model=self.model, max_tokens=5,
                    messages=[{"role": "user", "content": "Reply with OK."}])
        return f"Connected. Model: {self.model}."


class SarvamSpeechProvider(_Sarvam):
    name = "sarvam-speech"

    def __init__(self, api_key: str, stt_model: str, tts_model: str, speaker: str) -> None:
        super().__init__(api_key)
        self.stt_model, self.tts_model, self.speaker = stt_model, tts_model, speaker

    def transcribe(self, audio: bytes, filename: str) -> str:
        """Tamil, English and code-mixed speech. The synchronous API accepts clips up to 30 seconds."""
        file = io.BytesIO(audio)
        file.name = filename
        response = self._guard(self.client.speech_to_text.transcribe, file=file, model=self.stt_model, mode="codemix")
        return response.transcript

    def synthesize(self, text: str, language_code: str) -> bytes:
        kwargs = {"text": text, "language_code": language_code, "model": self.tts_model}
        if self.speaker:
            kwargs["speaker"] = self.speaker
        response = self._guard(self.client.text_to_speech.convert, **kwargs)
        return base64.b64decode("".join(response.audios))


class SarvamTranslationProvider(_Sarvam):
    name = "sarvam-translate"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key)
        self.model = model

    def translate(self, text: str, target_language_code: str) -> str:
        response = self._guard(self.client.text.translate, input=text, source_language_code="en-IN",
                               target_language_code=target_language_code, model=self.model)
        return response.translated_text

    def ping(self) -> str:
        return "Connected. Sample translation: " + self.translate("Hello", "ta-IN")


def lines_from_archive(data: bytes) -> list[str]:
    """Text lines from a Document AI result ZIP, flattened to the space-separated form extraction.parse_text reads.
    Markdown tables arrive as "| a | b |" and HTML tables as <tr><td>; both become "a b"."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    lines: list[str] = []
    for name in sorted(archive.namelist()):
        text = archive.read(name).decode("utf-8", "replace")
        if name.endswith((".html", ".htm")):
            text = re.sub(r"</(tr|p|div|h\d|li)>|<br\s*/?>", "\n", text, flags=re.I)
            text = html.unescape(re.sub(r"<[^>]+>", " ", text))
        elif not name.endswith(".md"):
            continue
        lines += [" ".join(line.replace("|", " ").split()) for line in text.splitlines() if set(line) - set("|-: ")]
    return [line for line in lines if line]


class SarvamDocumentProvider(_Sarvam):
    """Sarvam Vision as an alternative text source for scanned documents. Output feeds extraction.parse_text."""
    name = "sarvam-vision"

    def extract_text(self, path: Path) -> list[str]:
        with open(path, "rb") as f:
            job = self._guard(self.client.doc_ai.parse, file=[(path.name, f, "application/pdf")], language="en-IN")
        for _ in range(40):
            status = self._guard(self.client.doc_ai.get_status, job_id=job.job_id).status.lower()
            if status in ("completed", "partially_completed"):
                break
            if status in ("failed", "rejected"):
                raise ProviderError(f"Sarvam Vision job {status}.")
            time.sleep(3)
        else:
            raise ProviderError("Sarvam Vision job timed out.")
        url = self._guard(self.client.doc_ai.get_download_url, job_id=job.job_id).url
        if not str(url).startswith("https://"):      # urlopen would also read file:// and ftp:// URLs
            raise ProviderError("Sarvam returned a download URL that is not HTTPS.")
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - HTTPS URL issued by the Sarvam API
            return lines_from_archive(response.read())
