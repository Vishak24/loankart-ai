"""Environment-based configuration. Read at app creation so tests can override via env vars.

Provider credentials are read here, on the backend only. They are never sent to the browser.
"""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"


def load_env_file(path: Path = BACKEND_DIR / ".env") -> None:
    """Minimal .env reader: KEY=VALUE lines, optional quotes. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    db_path: Path
    cors_origins: list[str]
    storage_dir: Path
    ai_mode: str                 # "mock" or "live": the default at start-up; switchable at runtime in /demo-control
    reasoning_provider: str      # "claude" or "sarvam": which live provider writes explanations
    pacing_ms: int               # pause between investigation steps so the timeline can be followed
    anthropic_api_key: str
    anthropic_model: str
    sarvam_api_key: str
    sarvam_chat_model: str
    sarvam_stt_model: str
    sarvam_tts_model: str
    sarvam_tts_speaker: str
    sarvam_translate_model: str
    sarvam_use_vision: bool
    paytm_merchant_id: str
    paytm_merchant_key: str
    paytm_environment: str
    paytm_client_id: str         # Settlement API credentials: a client ID and a JWT issued by Paytm
    paytm_access_token: str
    # ---- security (see SECURITY.md). "development" keeps the zero-config local demo; "production" is strict.
    environment: str = "development"
    secret_key: str = ""                 # signs session cookies
    advisor_password: str = ""           # the advisor sign-in passcode
    secrets_are_ephemeral: bool = False  # development only: generated at start-up because none was configured
    public_demo: bool = True             # may anyone open the shared synthetic demo case?
    demo_tools: bool = True              # reset / scenario / log endpoints exist (advisor-only either way)
    trust_proxy: bool = False            # take the client address from X-Forwarded-For (only behind your own proxy)
    rate_default: int = 600              # requests per minute per client, all /api routes (0 = off)
    rate_ai: int = 20                    # per minute per client, routes that can spend provider credits
    rate_ai_daily: int = 500             # per day, whole server, same routes
    rate_login: int = 5                  # advisor sign-in attempts per minute per client
    rate_upload: int = 10                # uploads per minute per client
    rate_create: int = 10                # new borrower profiles per minute per client
    borrower_session_hours: int = 12
    advisor_session_hours: int = 4

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


_EPHEMERAL: dict[str, str] = {}      # one generated value per process, so repeated get_settings() calls agree


def _number(raw: str | None, default: int) -> int:
    try:
        return max(0, int(raw)) if raw not in (None, "") else default
    except ValueError:
        return default


def _flag(raw: str | None, default: bool) -> bool:
    return default if raw in (None, "") else raw.strip().lower() in ("1", "true", "yes", "on")


def production_problems(s: "Settings") -> list[str]:
    """Why these settings are unsafe for production. Messages never contain values."""
    problems = []
    if len(s.secret_key) < 32 or s.secrets_are_ephemeral:
        problems.append("LOANKART_SECRET_KEY must be set to a random value of at least 32 characters")
    if len(s.advisor_password) < 12 or s.secrets_are_ephemeral:
        problems.append("LOANKART_ADVISOR_PASSWORD must be set to a passcode of at least 12 characters")
    origins = s.cors_origins
    if not origins or any(o == "*" or not o.startswith("https://") for o in origins):
        problems.append("LOANKART_CORS_ORIGINS must list the exact https:// origin(s) of the site (no wildcard, no http)")
    return problems


def get_settings() -> Settings:
    load_env_file()
    env = os.environ.get
    mode = (env("LOANKART_ENV") or "development").strip().lower()
    if mode not in ("development", "production"):
        raise RuntimeError("LOANKART_ENV must be 'development' or 'production'")
    prod = mode == "production"
    ephemeral = False
    secret_key, advisor_password = env("LOANKART_SECRET_KEY") or "", env("LOANKART_ADVISOR_PASSWORD") or ""
    if not prod:                      # development: a missing secret is generated, never a fixed default
        if not secret_key:
            secret_key, ephemeral = _EPHEMERAL.setdefault("secret", secrets.token_urlsafe(32)), True
        if not advisor_password:
            advisor_password, ephemeral = _EPHEMERAL.setdefault("passcode", secrets.token_urlsafe(9)), True
    db_path = Path(env("LOANKART_DB_PATH") or BACKEND_DIR / "data" / "loankart.db")
    origins = env("LOANKART_CORS_ORIGINS") or DEFAULT_CORS
    mode_ai = (env("LOANKART_AI_MODE") or "mock").strip().lower()
    return Settings(
        db_path=db_path,
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        storage_dir=db_path.parent / "files",        # next to the database, so tests stay inside their temp dir
        ai_mode=mode_ai if mode_ai in ("mock", "live") else "mock",
        reasoning_provider=(env("LOANKART_REASONING_PROVIDER") or "claude").strip().lower(),
        pacing_ms=int(env("LOANKART_DEMO_PACING_MS") or 350),
        anthropic_api_key=env("ANTHROPIC_API_KEY") or "",
        anthropic_model=env("ANTHROPIC_MODEL") or "claude-opus-5-5",
        sarvam_api_key=env("SARVAM_API_KEY") or "",
        sarvam_chat_model=env("SARVAM_CHAT_MODEL") or "sarvam-105b",
        sarvam_stt_model=env("SARVAM_STT_MODEL") or "saaras:v4",
        sarvam_tts_model=env("SARVAM_TTS_MODEL") or "bulbul:v4-flash",
        sarvam_tts_speaker=env("SARVAM_TTS_SPEAKER") or "",
        sarvam_translate_model=env("SARVAM_TRANSLATE_MODEL") or "sarvam-translate:v1",
        sarvam_use_vision=(env("LOANKART_USE_SARVAM_VISION") or "0") == "1",
        paytm_merchant_id=env("PAYTM_MERCHANT_ID") or "",
        paytm_merchant_key=env("PAYTM_MERCHANT_KEY") or "",
        paytm_environment=(env("PAYTM_ENVIRONMENT") or "staging").strip().lower(),
        paytm_client_id=env("PAYTM_CLIENT_ID") or "",
        paytm_access_token=env("PAYTM_ACCESS_TOKEN") or "",
        environment=mode, secret_key=secret_key, advisor_password=advisor_password, secrets_are_ephemeral=ephemeral,
        public_demo=_flag(env("LOANKART_PUBLIC_DEMO"), not prod), demo_tools=_flag(env("LOANKART_ENABLE_DEMO_TOOLS"), not prod),
        trust_proxy=_flag(env("LOANKART_TRUST_PROXY"), False),
        rate_default=_number(env("LOANKART_RATE_DEFAULT"), 600), rate_ai=_number(env("LOANKART_RATE_AI"), 20),
        rate_ai_daily=_number(env("LOANKART_RATE_AI_DAILY"), 500), rate_login=_number(env("LOANKART_RATE_LOGIN"), 5),
        rate_upload=_number(env("LOANKART_RATE_UPLOAD"), 10), rate_create=_number(env("LOANKART_RATE_CREATE"), 10),
        borrower_session_hours=_number(env("LOANKART_BORROWER_SESSION_HOURS"), 12) or 12,
        advisor_session_hours=_number(env("LOANKART_ADVISOR_SESSION_HOURS"), 4) or 4,
    )
