"""FastAPI app: start-up, CORS, central error mapping. Run with `uvicorn app.main:app`."""

import logging
import sqlite3

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from . import db, environment, redact
from . import config, security
from .config import get_settings
from .errors import BadInput, Conflict, Forbidden, NotFound, Unauthorized
from .routes import get_conn, router
from .schemas import HealthOut

log = logging.getLogger("loankart")


def create_app() -> FastAPI:
    settings = get_settings()
    redact.register(settings.secret_key, settings.advisor_password, settings.anthropic_api_key, settings.sarvam_api_key,
                    settings.paytm_merchant_key, settings.paytm_access_token)
    redact.install_log_scrubbing()
    if not log.handlers:                  # plain uvicorn configures only its own loggers; without this, INFO (auth events) is dropped
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    if settings.is_production:
        problems = config.production_problems(settings)
        if problems:                      # refuse to start rather than run production with development defaults
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems) + ". See SECURITY.md.")
    else:
        log.warning("LOANKART_ENV=development: for local demos only. Do not expose this server to a network.")
        if not settings.advisor_password:
            log.warning("No advisor passcode is configured, so advisor sign-in is closed. Run: python scripts/set_advisor_password.py")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.init_db(settings.db_path)          # rebuilds derived tables when the schema version changed
        conn = db.connect(settings.db_path)
        try:
            environment.seed(conn)
        finally:
            conn.close()
        yield

    hide_docs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.is_production else {}
    app = FastAPI(title="LoanKart.ai API", version="0.2.0", lifespan=lifespan, **hide_docs,
                  description="Hackathon prototype. All lenders, borrowers and documents are synthetic.")
    app.state.settings = settings
    app.state.limiter = security.RateLimiter()          # per app instance, so each test app starts clean
    app.middleware("http")(security.http_guard)
    app.add_middleware(                                  # added last = outermost, so even refusals carry CORS headers
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,                          # the session cookie; origins above are an explicit list
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    def problem(status: int):
        async def handler(_: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc)})
        return handler

    for error, status in ((NotFound, 404), (Conflict, 409), (Unauthorized, 401), (Forbidden, 403), (BadInput, 422)):
        app.add_exception_handler(error, problem(status))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals to the browser; record the failure where the demo control centre can show it.
        log.exception("Unhandled error on %s", request.url.path)
        try:
            conn = db.connect(settings.db_path)
            db.add_event(conn, "log", "Unhandled server error", detail=redact.redact(f"{request.url.path}: {exc.__class__.__name__}: {exc}")[:600])
            conn.close()
        except Exception:
            pass
        return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Your case is unchanged."})

    @app.get("/health", response_model=HealthOut)
    def health(conn: sqlite3.Connection = Depends(get_conn)) -> HealthOut:
        conn.execute("SELECT 1").fetchone()
        return HealthOut(status="ok", database="ok")

    app.include_router(router)
    return app


app = create_app()
