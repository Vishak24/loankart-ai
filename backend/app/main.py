"""FastAPI app: start-up, CORS, central error mapping. Run with `uvicorn app.main:app`."""

import logging
import sqlite3

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from . import db, environment
from .config import get_settings
from .errors import BadInput, Conflict, Forbidden, NotFound
from .routes import get_conn, router
from .schemas import HealthOut

log = logging.getLogger("loankart")


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.init_db(settings.db_path)          # rebuilds derived tables when the schema version changed
        conn = db.connect(settings.db_path)
        try:
            environment.seed(conn)
        finally:
            conn.close()
        yield

    app = FastAPI(title="LoanKart.ai API", version="0.2.0", lifespan=lifespan,
                  description="Hackathon prototype. All lenders, borrowers and documents are synthetic.")
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-LoanKart-Role"],
    )

    def problem(status: int):
        async def handler(_: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc)})
        return handler

    for error, status in ((NotFound, 404), (Conflict, 409), (Forbidden, 403), (BadInput, 422)):
        app.add_exception_handler(error, problem(status))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals to the browser; record the failure where the demo control centre can show it.
        log.exception("Unhandled error on %s", request.url.path)
        try:
            conn = db.connect(settings.db_path)
            db.add_event(conn, "log", "Unhandled server error", detail=f"{request.url.path}: {exc.__class__.__name__}: {exc}"[:600])
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
