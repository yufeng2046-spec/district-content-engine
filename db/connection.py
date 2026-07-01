"""SQLite connection with WAL mode, matching existing build_db.py pattern."""

import sqlite3
from contextlib import contextmanager

from config import DB_PATH


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.row_factory = sqlite3.Row
    return conn
