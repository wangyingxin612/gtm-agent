"""
TDD tests for src/storage/database.py.
All tests use an in-memory SQLite database — never touch the filesystem.
"""
import json
import sqlite3
from datetime import datetime

import pytest

from src.models.events import OverrideEvent
from src.storage.database import (
    get_connection,
    init_db,
    record_outcome,
    write_override_event,
    write_signal_snapshot,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    """Fresh in-memory SQLite connection for every test."""
    connection = get_connection(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def initialized_conn(conn):
    """In-memory DB with tables already created."""
    init_db(conn)
    return conn


@pytest.fixture
def sample_snapshot():
    return dict(
        id="snap-001",
        session_id="sess-abc",
        company_id="comp-001",
        company_domain="acme.com",
        icp_hash="sha256:abc123",
        signals={
            "industry_match": True,
            "size_in_range": True,
            "location_match": True,
            "employee_count": 320,
            "keywords_matched": ["compliance", "operations"],
            "keyword_match_ratio": 0.67,
            "funding_series": "Series B",
            "funding_months_ago": 10,
            "company_age_years": 8,
            "revenue_range": "$10M-$50M",
            "lookalike_score": 7.0,
            "existing_customers_count": 4,
            "enrichment_confidence": 0.87,
            "data_quality": "full",
        },
        firmographic_score=26.0,
        keyword_score=22.5,
        growth_score=18.0,
        timing_score=13.0,
        lookalike_score=7.0,
        total_score=89.5,
        tier_assigned="Tier 1",
        scored_at=datetime(2026, 4, 28, 10, 5, 0),
    )


@pytest.fixture
def sample_override():
    return dict(
        id="ov-001",
        session_id="sess-abc",
        company_id="comp-001",
        company_domain="acme.com",
        action="keep",
        remove_reason=None,
        remove_reason_text=None,
        rerank_direction=None,
        score_at_override=89.5,
        tier_at_override="Tier 1",
        score_breakdown_at_override={
            "firmographic_score": 26.0,
            "keyword_score": 22.5,
            "growth_score": 18.0,
            "timing_score": 13.0,
            "lookalike_score": 7.0,
        },
        timestamp=datetime(2026, 4, 28, 10, 10, 0),
        user_id="operator",
        was_correct=None,
    )


def _make_override_event(**kwargs) -> OverrideEvent:
    """Build a minimal valid OverrideEvent, overriding any fields via kwargs."""
    defaults = dict(
        id="ov-test",
        session_id="sess-abc",
        company_id="comp-001",
        company_domain="acme.com",
        action="keep",
        score_at_override=89.5,
        tier_at_override="Tier 1",
        score_breakdown_at_override={"firmographic_score": 26.0},
        timestamp=datetime(2026, 4, 28, 11, 0, 0),
    )
    return OverrideEvent(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# test_tables_created
# ---------------------------------------------------------------------------

class TestTablesCreated:
    def test_signal_snapshots_table_exists(self, initialized_conn):
        row = initialized_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_snapshots'"
        ).fetchone()
        assert row is not None, "signal_snapshots table was not created"

    def test_override_events_table_exists(self, initialized_conn):
        row = initialized_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='override_events'"
        ).fetchone()
        assert row is not None, "override_events table was not created"

    def test_signal_snapshots_indexes_exist(self, initialized_conn):
        rows = initialized_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='signal_snapshots'"
        ).fetchall()
        index_names = {r["name"] for r in rows}
        assert "idx_snapshot_session" in index_names
        assert "idx_snapshot_outcome" in index_names
        assert "idx_snapshot_icp" in index_names

    def test_override_events_indexes_exist(self, initialized_conn):
        rows = initialized_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='override_events'"
        ).fetchall()
        index_names = {r["name"] for r in rows}
        assert "idx_override_company" in index_names
        assert "idx_override_action" in index_names

    def test_init_db_is_idempotent(self, initialized_conn):
        """Calling init_db() twice must not raise."""
        init_db(initialized_conn)


# ---------------------------------------------------------------------------
# test_write_signal_snapshot
# ---------------------------------------------------------------------------

class TestWriteSignalSnapshot:
    def test_row_is_stored(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        row = initialized_conn.execute(
            "SELECT * FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        assert row is not None

    def test_all_scalar_fields_match(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        row = initialized_conn.execute(
            "SELECT * FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        assert row["session_id"] == "sess-abc"
        assert row["company_id"] == "comp-001"
        assert row["company_domain"] == "acme.com"
        assert row["icp_hash"] == "sha256:abc123"
        assert row["firmographic_score"] == pytest.approx(26.0)
        assert row["keyword_score"] == pytest.approx(22.5)
        assert row["growth_score"] == pytest.approx(18.0)
        assert row["timing_score"] == pytest.approx(13.0)
        assert row["lookalike_score"] == pytest.approx(7.0)
        assert row["total_score"] == pytest.approx(89.5)
        assert row["tier_assigned"] == "Tier 1"

    def test_signals_stored_as_valid_json(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        row = initialized_conn.execute(
            "SELECT signals FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        parsed = json.loads(row["signals"])
        assert parsed["industry_match"] is True
        assert parsed["keyword_match_ratio"] == pytest.approx(0.67)
        assert parsed["keywords_matched"] == ["compliance", "operations"]

    def test_duplicate_snapshot_is_ignored(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        write_signal_snapshot(initialized_conn, sample_snapshot)  # same session+company
        count = initialized_conn.execute(
            "SELECT COUNT(*) FROM signal_snapshots WHERE session_id = ? AND company_id = ?",
            ("sess-abc", "comp-001"),
        ).fetchone()[0]
        assert count == 1

    def test_scored_at_stored_as_iso_string(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        row = initialized_conn.execute(
            "SELECT scored_at FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        assert isinstance(row["scored_at"], str)
        datetime.fromisoformat(row["scored_at"])  # must be valid ISO format

    def test_signals_with_datetime_value_serialises_without_error(self, initialized_conn, sample_snapshot):
        """json.dumps default=str must handle datetime values in signals."""
        sample_snapshot["signals"]["some_date"] = datetime(2026, 4, 28)
        write_signal_snapshot(initialized_conn, sample_snapshot)
        row = initialized_conn.execute(
            "SELECT signals FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        parsed = json.loads(row["signals"])
        assert "some_date" in parsed


# ---------------------------------------------------------------------------
# test_user_outcome_defaults_null
# ---------------------------------------------------------------------------

class TestUserOutcomeDefaultsNull:
    def test_user_outcome_is_null_on_write(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        row = initialized_conn.execute(
            "SELECT user_outcome FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        assert row["user_outcome"] is None

    def test_outcome_reason_is_null_on_write(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        row = initialized_conn.execute(
            "SELECT outcome_reason FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        assert row["outcome_reason"] is None

    def test_outcome_timestamp_is_null_on_write(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        row = initialized_conn.execute(
            "SELECT outcome_timestamp FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        assert row["outcome_timestamp"] is None


# ---------------------------------------------------------------------------
# test_record_outcome
# ---------------------------------------------------------------------------

class TestRecordOutcome:
    def test_user_outcome_updated(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        record_outcome(initialized_conn, _make_override_event(action="keep"))
        row = initialized_conn.execute(
            "SELECT user_outcome FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        assert row["user_outcome"] == "keep"

    def test_outcome_reason_updated(self, initialized_conn, sample_snapshot):
        write_signal_snapshot(initialized_conn, sample_snapshot)
        record_outcome(
            initialized_conn,
            _make_override_event(action="remove", remove_reason="Wrong industry"),
        )
        row = initialized_conn.execute(
            "SELECT outcome_reason FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        assert row["outcome_reason"] == "Wrong industry"

    def test_outcome_timestamp_updated(self, initialized_conn, sample_snapshot):
        ts = datetime(2026, 4, 28, 11, 0, 0)
        write_signal_snapshot(initialized_conn, sample_snapshot)
        record_outcome(initialized_conn, _make_override_event(action="revisit", timestamp=ts))
        row = initialized_conn.execute(
            "SELECT outcome_timestamp FROM signal_snapshots WHERE id = ?", ("snap-001",)
        ).fetchone()
        assert row["outcome_timestamp"] == ts.isoformat()

    def test_record_outcome_raises_for_unknown_company(self, initialized_conn):
        with pytest.raises(ValueError, match="No snapshot found"):
            record_outcome(
                initialized_conn,
                _make_override_event(
                    session_id="sess-does-not-exist",
                    company_id="comp-does-not-exist",
                ),
            )

    def test_record_outcome_only_updates_matching_session(self, initialized_conn, sample_snapshot):
        """A snapshot in a different session must not be updated."""
        write_signal_snapshot(initialized_conn, sample_snapshot)
        other = {**sample_snapshot, "id": "snap-002", "session_id": "sess-OTHER"}
        write_signal_snapshot(initialized_conn, other)
        record_outcome(initialized_conn, _make_override_event(action="keep"))
        row = initialized_conn.execute(
            "SELECT user_outcome FROM signal_snapshots WHERE id = ?", ("snap-002",)
        ).fetchone()
        assert row["user_outcome"] is None


# ---------------------------------------------------------------------------
# test_write_override_event
# ---------------------------------------------------------------------------

class TestWriteOverrideEvent:
    def test_row_is_stored(self, initialized_conn, sample_override):
        write_override_event(initialized_conn, sample_override)
        row = initialized_conn.execute(
            "SELECT * FROM override_events WHERE id = ?", ("ov-001",)
        ).fetchone()
        assert row is not None

    def test_all_scalar_fields_match(self, initialized_conn, sample_override):
        write_override_event(initialized_conn, sample_override)
        row = initialized_conn.execute(
            "SELECT * FROM override_events WHERE id = ?", ("ov-001",)
        ).fetchone()
        assert row["session_id"] == "sess-abc"
        assert row["company_id"] == "comp-001"
        assert row["company_domain"] == "acme.com"
        assert row["action"] == "keep"
        assert row["score_at_override"] == pytest.approx(89.5)
        assert row["tier_at_override"] == "Tier 1"
        assert row["user_id"] == "operator"
        assert row["remove_reason"] is None
        assert row["remove_reason_text"] is None
        assert row["rerank_direction"] is None
        assert row["was_correct"] is None

    def test_score_breakdown_stored_as_valid_json(self, initialized_conn, sample_override):
        write_override_event(initialized_conn, sample_override)
        row = initialized_conn.execute(
            "SELECT score_breakdown_at_override FROM override_events WHERE id = ?", ("ov-001",)
        ).fetchone()
        parsed = json.loads(row["score_breakdown_at_override"])
        assert parsed["firmographic_score"] == pytest.approx(26.0)
        assert parsed["keyword_score"] == pytest.approx(22.5)

    def test_timestamp_stored_as_iso_string(self, initialized_conn, sample_override):
        write_override_event(initialized_conn, sample_override)
        row = initialized_conn.execute(
            "SELECT timestamp FROM override_events WHERE id = ?", ("ov-001",)
        ).fetchone()
        assert isinstance(row["timestamp"], str)
        datetime.fromisoformat(row["timestamp"])

    def test_remove_reason_persisted(self, initialized_conn, sample_override):
        override = {**sample_override, "id": "ov-002", "action": "remove",
                    "remove_reason": "Wrong industry"}
        write_override_event(initialized_conn, override)
        row = initialized_conn.execute(
            "SELECT remove_reason FROM override_events WHERE id = ?", ("ov-002",)
        ).fetchone()
        assert row["remove_reason"] == "Wrong industry"

    def test_rerank_direction_persisted(self, initialized_conn, sample_override):
        override = {**sample_override, "id": "ov-003", "action": "rerank",
                    "rerank_direction": "up"}
        write_override_event(initialized_conn, override)
        row = initialized_conn.execute(
            "SELECT rerank_direction FROM override_events WHERE id = ?", ("ov-003",)
        ).fetchone()
        assert row["rerank_direction"] == "up"


# ---------------------------------------------------------------------------
# test_in_memory_db (explicit guard)
# ---------------------------------------------------------------------------

class TestInMemoryDb:
    def test_no_filesystem_writes(self, initialized_conn):
        """Confirm the fixture is truly in-memory — no database filename."""
        assert initialized_conn.execute("PRAGMA database_list").fetchone()["file"] == ""

    def test_get_connection_sets_row_factory(self):
        """get_connection() must set row_factory so columns are accessible by name."""
        conn = get_connection(":memory:")
        assert conn.row_factory == sqlite3.Row
        conn.close()
