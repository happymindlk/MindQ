"""Classify schema-drift vs transient DB errors for 503 messaging / retries."""

from sqlalchemy.exc import OperationalError, ProgrammingError

from app.exceptions import is_schema_drift_error, is_transient_db_error, schema_drift_detail


class _PgUndefinedColumn(Exception):
    sqlstate = "42703"


class _PreparedDropped(Exception):
    sqlstate = "26000"


class _ConnReset(Exception):
    sqlstate = "08006"


def test_undefined_column_is_schema_drift_not_transient():
    exc = ProgrammingError(
        "SELECT",
        {},
        _PgUndefinedColumn('column assessments.top_disclaimer_text does not exist'),
    )
    assert is_schema_drift_error(exc) is True
    assert is_transient_db_error(exc) is False
    assert "migration" in schema_drift_detail(exc).lower()


def test_prepared_statement_drop_is_transient_not_schema():
    exc = ProgrammingError(
        "SELECT",
        {},
        _PreparedDropped('prepared statement "__asyncpg_stmt_3e__" does not exist'),
    )
    assert is_schema_drift_error(exc) is False
    assert is_transient_db_error(exc) is True
    assert schema_drift_detail(exc) == "Database query failed"


def test_connection_reset_is_transient():
    exc = OperationalError("SELECT", {}, _ConnReset("connection reset by peer"))
    assert is_schema_drift_error(exc) is False
    assert is_transient_db_error(exc) is True
