"""ClaudeReasoningProvider: explanations and summaries over structured evidence, via the official Anthropic SDK.

Claude never calculates figures, sets lender rules or decides outcomes here: it receives finished evidence as JSON
and returns text in a validated schema (structured outputs).
"""

import json
from typing import Any

from pydantic import BaseModel

from .base import SCHEMAS, SYSTEM_PROMPT, TASKS, ProviderError

# Models that accept the server-side refusal fallback and the effort parameter used below.
FALLBACK_MODELS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class ClaudeReasoningProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str) -> None:
        import anthropic     # imported lazily so mock mode never needs the SDK

        self._anthropic = anthropic
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, timeout=90.0, max_retries=1)

    def _call(self, **kwargs: Any) -> Any:
        a = self._anthropic
        try:
            if self.model in FALLBACK_MODELS:
                return self.client.beta.messages.parse(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                                       output_config={"effort": "low"}, **kwargs)
            return self.client.messages.parse(**kwargs)
        except a.AuthenticationError as exc:
            raise ProviderError("Claude rejected the API key. Check ANTHROPIC_API_KEY in backend/.env.") from exc
        except a.PermissionDeniedError as exc:
            raise ProviderError("The Anthropic API key does not have access to this model.") from exc
        except a.NotFoundError as exc:
            raise ProviderError(f"Claude model '{self.model}' was not found. Check ANTHROPIC_MODEL.") from exc
        except a.RateLimitError as exc:
            raise ProviderError("Claude rate limit reached. Try again shortly.") from exc
        except a.APIStatusError as exc:
            raise ProviderError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except a.APIConnectionError as exc:
            raise ProviderError("Could not reach the Anthropic API. Check the internet connection.") from exc

    def generate(self, task: str, context: dict[str, Any]) -> BaseModel:
        response = self._call(
            model=self.model, max_tokens=16000, system=SYSTEM_PROMPT, output_format=SCHEMAS[task],
            messages=[{"role": "user", "content": f"{TASKS[task]}\n\n<evidence>\n{json.dumps(context, ensure_ascii=False)}\n</evidence>"}])
        if response.stop_reason == "refusal":
            raise ProviderError("Claude declined this request.")
        if response.parsed_output is None:
            raise ProviderError(f"Claude returned no structured output (stop reason: {response.stop_reason}).")
        return response.parsed_output

    def ping(self) -> str:
        """Connectivity check that spends no tokens."""
        a = self._anthropic
        try:
            info = self.client.models.retrieve(self.model)
        except a.AuthenticationError as exc:
            raise ProviderError("Authentication failed. Check ANTHROPIC_API_KEY.") from exc
        except a.NotFoundError as exc:
            raise ProviderError(f"Model '{self.model}' not found. Check ANTHROPIC_MODEL.") from exc
        except a.APIError as exc:
            raise ProviderError(f"Anthropic API error: {exc}") from exc
        return f"Connected. Model: {info.display_name}."
