"""SQLite persistence: schema and row-level access. No business rules here.

Tables: borrowers (onboarding answers), cases (one per borrower; workflow state as JSON), documents (files and
their extraction output), lender_products (editable fictional policies), events (application, audit and log
trail), knowledge (expert knowledge entries), settings (runtime switches such as the AI mode).
"""

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redact import redact

SCHEMA_VERSION = 2   # bump when the seed or table shapes change: derived tables are rebuilt on start-up

SCHEMA = """
CREATE TABLE IF NOT EXISTS borrowers (
    id          TEXT PRIMARY KEY,
    is_demo     INTEGER NOT NULL DEFAULT 0,
    profile     TEXT NOT NULL,          -- JSON: validated BorrowerProfile
    evidence    TEXT,                   -- unused since schema v2 (kept so older databases still open)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY, borrower_id TEXT NOT NULL, scenario_id TEXT, intent TEXT NOT NULL,
    data TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, doc_type TEXT, grp TEXT NOT NULL, title TEXT NOT NULL,
    period TEXT, filename TEXT NOT NULL, path TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
    extraction TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lender_products (id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, kind TEXT NOT NULL, actor TEXT NOT NULL,
    title TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', payload TEXT, simulated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
DERIVED = ("cases", "documents", "lender_products", "events", "knowledge")


def connect(db_path: Path) -> sqlite3.Connection:
    # One connection per request or background task, never shared between them. FastAPI may create the connection
    # (dependency) and run the handler on different worker threads, one after the other, so the same-thread check
    # is turned off; a connection is still only ever used by one request at a time.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> bool:
    """Create tables. Returns True when demo data must be (re)seeded because the schema version changed."""
    conn = connect(db_path)
    try:
        stale = conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
        conn.executescript(SCHEMA)
        if stale:
            wipe_demo(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return stale
    finally:
        conn.close()


def wipe_demo(conn: sqlite3.Connection) -> None:
    """Remove everything derived from the synthetic environment. Borrowers created through onboarding stay."""
    for table in DERIVED:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM borrowers WHERE is_demo = 1")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'events'")   # event ids restart, so a reset is exact
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------------------------- borrowers

def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "is_demo": bool(row["is_demo"]),
        "profile": json.loads(row["profile"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_borrower(conn: sqlite3.Connection, borrower_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM borrowers WHERE id = ?", (borrower_id,)).fetchone()
    return _row_to_dict(row) if row else None


def insert_borrower(conn: sqlite3.Connection, borrower_id: str, profile: dict[str, Any], is_demo: bool = False
                    ) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO borrowers (id, is_demo, profile, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (borrower_id, int(is_demo), json.dumps(profile), now, now),
    )
    conn.commit()
    return get_borrower(conn, borrower_id)  # type: ignore[return-value]


def update_profile(conn: sqlite3.Connection, borrower_id: str, profile: dict[str, Any]) -> dict[str, Any] | None:
    cur = conn.execute(
        "UPDATE borrowers SET profile = ?, updated_at = ? WHERE id = ?",
        (json.dumps(profile), _now(), borrower_id),
    )
    conn.commit()
    return get_borrower(conn, borrower_id) if cur.rowcount else None


def delete_borrower(conn: sqlite3.Connection, borrower_id: str) -> None:
    conn.execute("DELETE FROM borrowers WHERE id = ?", (borrower_id,))
    conn.commit()


# ---------------------------------------------------------------------------------------------- cases

def _case(row: sqlite3.Row) -> dict[str, Any]:
    return {**dict(row), "data": json.loads(row["data"])}


def get_case(conn: sqlite3.Connection, case_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return _case(row) if row else None


def case_for_borrower(conn: sqlite3.Connection, borrower_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM cases WHERE borrower_id = ?", (borrower_id,)).fetchone()
    return _case(row) if row else None


def list_cases(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_case(r) for r in conn.execute("SELECT * FROM cases ORDER BY updated_at DESC, id")]


def insert_case(conn: sqlite3.Connection, case_id: str, borrower_id: str, scenario_id: str | None, intent: str,
                data: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    conn.execute("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (case_id, borrower_id, scenario_id, intent, json.dumps(data), now, now))
    conn.commit()
    return get_case(conn, case_id)  # type: ignore[return-value]


def update_case(conn: sqlite3.Connection, case_id: str, change: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    """Read-modify-write of the case JSON inside one write transaction, so a background investigation and a
    request cannot overwrite each other's changes."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT data FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        data = json.loads(row["data"])
        change(data)
        conn.execute("UPDATE cases SET data = ?, updated_at = ? WHERE id = ?", (json.dumps(data), _now(), case_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return get_case(conn, case_id)  # type: ignore[return-value]


def delete_case(conn: sqlite3.Connection, case_id: str) -> None:
    for table, column in (("documents", "case_id"), ("events", "case_id"), ("cases", "id")):
        conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (case_id,))
    conn.commit()


# ---------------------------------------------------------------------------------------------- documents

def _doc(row: sqlite3.Row) -> dict[str, Any]:
    return {**dict(row), "extraction": json.loads(row["extraction"]) if row["extraction"] else None}


def list_documents(conn: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    return [_doc(r) for r in conn.execute("SELECT * FROM documents WHERE case_id = ? ORDER BY rowid", (case_id,))]


def get_document(conn: sqlite3.Connection, doc_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return _doc(row) if row else None


def insert_document(conn: sqlite3.Connection, doc: dict[str, Any]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO documents (id, case_id, doc_type, grp, title, period, filename, path, source, status,"
        " extraction, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (doc["id"], doc["case_id"], doc.get("doc_type"), doc["grp"], doc["title"], doc.get("period"), doc["filename"],
         doc["path"], doc["source"], doc["status"],
         json.dumps(doc["extraction"]) if doc.get("extraction") else None, _now()))


def set_extraction(conn: sqlite3.Connection, doc_id: str, extraction: dict[str, Any], status: str) -> None:
    conn.execute("UPDATE documents SET extraction = ?, doc_type = COALESCE(?, doc_type), status = ? WHERE id = ?",
                 (json.dumps(extraction), extraction.get("doc_type"), status, doc_id))


def delete_documents(conn: sqlite3.Connection, case_id: str, source: str) -> None:
    conn.execute("DELETE FROM documents WHERE case_id = ? AND source = ?", (case_id, source))
    conn.commit()


# ---------------------------------------------------------------------------------------------- events

def add_event(conn: sqlite3.Connection, kind: str, title: str, *, case_id: str | None = None, actor: str = "system",
              detail: str = "", payload: dict[str, Any] | None = None, simulated: bool = False) -> None:
    conn.execute(                                    # every stored event is scrubbed here, whatever the caller passed
        "INSERT INTO events (case_id, kind, actor, title, detail, payload, simulated, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (case_id, kind, actor, redact(title), redact(detail), redact(json.dumps(payload)) if payload else None, int(simulated), _now()))
    conn.commit()


def list_events(conn: sqlite3.Connection, case_id: str | None = None, kinds: tuple[str, ...] | None = None,
                limit: int = 200) -> list[dict[str, Any]]:
    where, args = [], []
    if case_id:
        where.append("case_id = ?")
        args.append(case_id)
    if kinds:
        where.append(f"kind IN ({','.join('?' * len(kinds))})")
        args.extend(kinds)
    sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    rows = conn.execute(sql, (*args, limit)).fetchall()
    return [{**dict(r), "simulated": bool(r["simulated"]), "payload": json.loads(r["payload"]) if r["payload"] else None}
            for r in reversed(rows)]


# ---------------------------------------------------------------------------------------------- lenders, knowledge, settings

def list_products(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [json.loads(r["data"]) for r in conn.execute("SELECT data FROM lender_products ORDER BY rowid")]


def put_product(conn: sqlite3.Connection, product: dict[str, Any]) -> None:
    conn.execute("INSERT OR REPLACE INTO lender_products VALUES (?, ?, ?)", (product["id"], json.dumps(product), _now()))
    conn.commit()


def list_knowledge(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [{**json.loads(r["data"]), "id": r["id"], "status": r["status"], "version": r["version"],
             "created_at": r["created_at"], "updated_at": r["updated_at"]}
            for r in conn.execute("SELECT * FROM knowledge ORDER BY created_at, id")]


def put_knowledge(conn: sqlite3.Connection, entry_id: str, data: dict[str, Any], status: str, version: int) -> None:
    now = _now()
    existing = conn.execute("SELECT created_at FROM knowledge WHERE id = ?", (entry_id,)).fetchone()
    conn.execute("INSERT OR REPLACE INTO knowledge VALUES (?, ?, ?, ?, ?, ?)",
                 (entry_id, json.dumps(data), status, version, existing["created_at"] if existing else now, now))
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))
    conn.commit()
