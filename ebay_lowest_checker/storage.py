import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import SQLITE_PATH


@contextmanager
def _connect():
    conn = sqlite3.connect(SQLITE_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS check_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checked_at TEXT NOT NULL,
                product_key TEXT NOT NULL,
                condition_name TEXT,
                target_url TEXT,
                target_price REAL,
                min_price REAL,
                min_url TEXT,
                status TEXT NOT NULL,
                note TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS price_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                product_key TEXT NOT NULL,
                old_price REAL,
                new_price REAL,
                floor_price REAL,
                dry_run INTEGER NOT NULL,
                success INTEGER NOT NULL,
                detail TEXT
            )
            """
        )


def add_check_log(
    product_key: str,
    condition_name: str,
    target_url: str,
    target_price: float,
    min_price: float,
    min_url: str,
    status: str,
    note: str = "",
):
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO check_logs
            (checked_at, product_key, condition_name, target_url, target_price, min_price, min_url, status, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                product_key,
                condition_name,
                target_url,
                target_price,
                min_price,
                min_url,
                status,
                note,
            ),
        )


def add_price_action(
    product_key: str,
    old_price: float,
    new_price: float,
    floor_price: float,
    dry_run: bool,
    success: bool,
    detail: str,
):
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO price_actions
            (created_at, product_key, old_price, new_price, floor_price, dry_run, success, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                product_key,
                old_price,
                new_price,
                floor_price,
                1 if dry_run else 0,
                1 if success else 0,
                detail,
            ),
        )


def get_recent_logs(limit: int = 50):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT checked_at, product_key, condition_name, target_url, target_price, min_price, min_url, status, note
            FROM check_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
