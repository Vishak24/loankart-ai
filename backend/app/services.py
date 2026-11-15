"""Borrower business logic, between the HTTP routes and the db layer."""

import sqlite3
import uuid

from . import db
from .errors import NotFound  # noqa: F401  (re-exported: older callers use services.NotFound)
from .schemas import BorrowerOut, BorrowerProfile


def create_borrower(conn: sqlite3.Connection, profile: BorrowerProfile) -> BorrowerOut:
    record = db.insert_borrower(conn, uuid.uuid4().hex, profile.model_dump(mode="json"))
    return BorrowerOut.from_record(record)


def get_borrower(conn: sqlite3.Connection, borrower_id: str) -> BorrowerOut:
    record = db.get_borrower(conn, borrower_id)
    if record is None:
        raise NotFound(f"Borrower '{borrower_id}' not found")
    return BorrowerOut.from_record(record)


def update_borrower(conn: sqlite3.Connection, borrower_id: str, profile: BorrowerProfile) -> BorrowerOut:
    record = db.update_profile(conn, borrower_id, profile.model_dump(mode="json"))
    if record is None:
        raise NotFound(f"Borrower '{borrower_id}' not found")
    return BorrowerOut.from_record(record)
