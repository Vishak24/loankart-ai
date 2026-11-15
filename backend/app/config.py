"""Environment-based configuration. Read at app creation so tests can override via env vars.

Provider credentials are read here, on the backend only. They are never sent to the browser.
"""

import os
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


def get_settings() -> Settings:
    load_env_file()
    env = os.environ.get
    db_path = Path(env("LOANKART_DB_PATH") or BACKEND_DIR / "data" / "loankart.db")
    origins = env("LOANKART_CORS_ORIGINS") or DEFAULT_CORS
    mode = (env("LOANKART_AI_MODE") or "mock").strip().lower()
    return Settings(
        db_path=db_path,
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        storage_dir=db_path.parent / "files",        # next to the database, so tests stay inside their temp dir
        ai_mode=mode if mode in ("mock", "live") else "mock",
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
    )
