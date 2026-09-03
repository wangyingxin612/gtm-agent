"""
Persistence layer for the GTM Agent learning pipeline.

Invariants this module enforces:
  - Every company scored in a session produces exactly one signal_snapshot row
    (UNIQUE constraint + INSERT OR IGNORE).
  - user_outcome is always NULL at write time; only record_outcome() may set it.
  - record_outcome() raises ValueError if the target snapshot does not exist —
    silent no-ops are not permitted.
  - Callers own transaction scope; individual write functions do not commit.
    Use `with conn:` to make a group of writes atomic.
"""

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict

from src.models.events import OverrideEvent


def _iso(dt: datetime) -> str:
    """Convert datetime to ISO-8601 string for SQLite TEXT storage."""
    return dt.isoformat() if isinstance(dt, datetime) else dt


def get_connection(path: str = "data/signal_store/gtm_agent.db") -> sqlite3.Connection:
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_snapshots (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            company_id TEXT NOT NULL,
            company_domain TEXT NOT NULL,
            icp_hash TEXT NOT NULL,
            signals TEXT NOT NULL,
            firmographic_score REAL,
            keyword_score REAL,
            growth_score REAL,
            timing_score REAL,
            lookalike_score REAL,
            total_score REAL NOT NULL,
            tier_assigned TEXT NOT NULL,
            user_outcome TEXT,
            outcome_reason TEXT,
            outcome_timestamp TEXT,
            scored_at TEXT NOT NULL,
            UNIQUE(session_id, company_id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshot_session ON signal_snapshots(session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshot_outcome ON signal_snapshots(user_outcome)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshot_icp ON signal_snapshots(icp_hash)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS override_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            company_id TEXT NOT NULL,
            company_domain TEXT NOT NULL,
            action TEXT NOT NULL,
            remove_reason TEXT,
            remove_reason_text TEXT,
            rerank_direction TEXT,
            score_at_override REAL NOT NULL,
            tier_at_override TEXT NOT NULL,
            score_breakdown_at_override TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'operator',
            was_correct INTEGER  -- Python bool: 1=True, 0=False, NULL=unlabeled
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_override_company ON override_events(company_domain)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_override_action ON override_events(action)"
    )
    conn.commit()


def write_signal_snapshot(conn: sqlite3.Connection, snapshot: Dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO signal_snapshots (
            id, session_id, company_id, company_domain, icp_hash,
            signals,
            firmographic_score, keyword_score, growth_score, timing_score, lookalike_score,
            total_score, tier_assigned,
            user_outcome, outcome_reason, outcome_timestamp,
            scored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
        """,
        (
            snapshot["id"],
            snapshot["session_id"],
            snapshot["company_id"],
            snapshot["company_domain"],
            snapshot["icp_hash"],
            json.dumps(snapshot.get("signals", {}), default=str),
            snapshot.get("firmographic_score"),
            snapshot.get("keyword_score"),
            snapshot.get("growth_score"),
            snapshot.get("timing_score"),
            snapshot.get("lookalike_score"),
            snapshot["total_score"],
            snapshot["tier_assigned"],
            _iso(snapshot["scored_at"]),
        ),
    )


def record_outcome(conn: sqlite3.Connection, override: OverrideEvent) -> None:
    cursor = conn.execute(
        """
        UPDATE signal_snapshots
        SET user_outcome = ?,
            outcome_reason = ?,
            outcome_timestamp = ?
        WHERE session_id = ? AND company_id = ?
        """,
        (
            override.action,
            override.remove_reason,
            _iso(override.timestamp),
            override.session_id,
            override.company_id,
        ),
    )
    if cursor.rowcount == 0:
        raise ValueError(
            f"No snapshot found for session={override.session_id!r} company={override.company_id!r}"
        )


class SignalStore:
    """Object wrapper around the DB layer for pipeline injection.

    Provides save_signal_snapshot(session_id, rc, icp) so the pipeline
    never writes raw SQL — and so tests can inject an in-memory instance.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save_signal_snapshot(self, session_id: str, rc: Any, icp: Any = None) -> None:
        from src.models.company import RankedCompany  # local import avoids circular dep
        icp_hash = (
            hashlib.md5(icp.model_dump_json().encode()).hexdigest()
            if icp is not None
            else ""
        )
        bd = rc.score_breakdown
        snapshot: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "company_id": rc.company.id,
            "company_domain": rc.company.domain,
            "icp_hash": icp_hash,
            "signals": {},
            "firmographic_score": bd.firmographic_score,
            "keyword_score": bd.keyword_score,
            "growth_score": bd.growth_score,
            "timing_score": bd.timing_score,
            "lookalike_score": bd.lookalike_score,
            "total_score": rc.total_score,
            "tier_assigned": rc.tier,
            "scored_at": datetime.utcnow(),
        }
        with self.conn:
            write_signal_snapshot(self.conn, snapshot)


def write_override_event(conn: sqlite3.Connection, override: Dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO override_events (
            id, session_id, company_id, company_domain,
            action, remove_reason, remove_reason_text, rerank_direction,
            score_at_override, tier_at_override, score_breakdown_at_override,
            timestamp, user_id, was_correct
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            override["id"],
            override["session_id"],
            override["company_id"],
            override["company_domain"],
            override["action"],
            override.get("remove_reason"),
            override.get("remove_reason_text"),
            override.get("rerank_direction"),
            override["score_at_override"],
            override["tier_at_override"],
            json.dumps(override["score_breakdown_at_override"], default=str),
            _iso(override["timestamp"]),
            override.get("user_id", "operator"),
            override.get("was_correct"),
        ),
    )
