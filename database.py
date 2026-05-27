"""SQLite 数据库连接与初始化"""

import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "aiops.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库表"""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fault_records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                log_input   TEXT    NOT NULL,
                fault_type  TEXT    NOT NULL DEFAULT '',
                cause       TEXT    NOT NULL DEFAULT '',
                commands    TEXT    NOT NULL DEFAULT '[]',
                solution    TEXT    NOT NULL DEFAULT '',
                risk_level  TEXT    NOT NULL DEFAULT 'info',
                raw_response TEXT   NOT NULL DEFAULT '',
                created_at  TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_records_created
                ON fault_records(created_at DESC);
        """)
