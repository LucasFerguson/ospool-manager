"""
Job run tracking backed by SQLite.

Database lives at runs/runs.db alongside the project.
All submitted jobs are recorded here and the watcher uses this
to know what to poll and fetch.

Schema:
  runs(cluster_id, sub_file, submitted_at, status, fetched_at)

Status values: submitted → running → done → fetched
                                   → failed
                                   → held
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Generator

from .config import Config

_CREATE = """
CREATE TABLE IF NOT EXISTS runs (
    cluster_id   INTEGER PRIMARY KEY,
    sub_file     TEXT    NOT NULL,
    submitted_at TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'submitted',
    fetched_at   TEXT
);
"""


def _db_path(cfg: Config) -> Path:
    cfg.local.runs_dir.mkdir(parents=True, exist_ok=True)
    return cfg.local.runs_dir / "runs.db"


@contextmanager
def _connect(cfg: Config) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(_db_path(cfg))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(_CREATE)
        conn.commit()
        yield conn
    finally:
        conn.close()


def save(cfg: Config, cluster_id: int, sub_file: str) -> None:
    """Insert a new run record. Replaces if the cluster ID already exists."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect(cfg) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs (cluster_id, sub_file, submitted_at, status, fetched_at) "
            "VALUES (?, ?, ?, 'submitted', NULL)",
            (cluster_id, sub_file, now),
        )
        conn.commit()


def update_status(cfg: Config, cluster_id: int, status: str, fetched: bool = False) -> None:
    """Update the status of a run. Pass fetched=True to also set fetched_at."""
    now = datetime.now(timezone.utc).isoformat() if fetched else None
    with _connect(cfg) as conn:
        if fetched:
            conn.execute(
                "UPDATE runs SET status = ?, fetched_at = ? WHERE cluster_id = ?",
                (status, now, cluster_id),
            )
        else:
            conn.execute(
                "UPDATE runs SET status = ? WHERE cluster_id = ?",
                (status, cluster_id),
            )
        conn.commit()


def load(cfg: Config, cluster_id: int) -> Optional[dict]:
    """Return a single run record as a dict, or None if not found."""
    with _connect(cfg) as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE cluster_id = ?", (cluster_id,)
        ).fetchone()
    return dict(row) if row else None


def list_runs(cfg: Config, days: Optional[int] = 30) -> list[dict]:
    """
    Return runs ordered by submission time descending.
    Pass days=None to return everything.
    """
    with _connect(cfg) as conn:
        if days is None:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY submitted_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs WHERE submitted_at >= datetime('now', ?) "
                "ORDER BY submitted_at DESC",
                (f"-{days} days",),
            ).fetchall()
    return [dict(r) for r in rows]


def pending_runs(cfg: Config) -> list[dict]:
    """Return runs that haven't been fetched or failed yet."""
    with _connect(cfg) as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE status NOT IN ('fetched', 'failed') "
            "ORDER BY submitted_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]
