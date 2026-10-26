"""Domain errors for the candidate assessment path."""


def is_schema_drift_error(exc: BaseException) -> bool:
    """True when the failure is a missing table/column, not a pooler glitch.

    Prepared-statement drops also contain ``does not exist`` (SQLSTATE 26000);
    those are transient under Supavisor transaction mode and must not be
    classified as schema drift.

    Args:
        exc: SQLAlchemy or driver exception.

    Returns:
        True for undefined table/column (or equivalent text), else False.
    """
    text = str(exc)
    low = text.lower()
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) if orig is not None else None
    if "prepared statement" in low or sqlstate == "26000":
        return False
    if sqlstate in ("42P01", "42703"):
        return True
    return (
        "does not exist" in low
        or "UndefinedColumn" in text
        or "UndefinedTable" in text
    )


def is_transient_db_error(exc: BaseException) -> bool:
    """True for disconnects, pooler timeouts, and prepared-statement drops.

    Args:
        exc: SQLAlchemy or driver exception.

    Returns:
        True when a short retry may succeed without a schema change.
    """
    if is_schema_drift_error(exc):
        return False
    text = str(exc).lower()
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) if orig is not None else None
    if getattr(exc, "connection_invalidated", False):
        return True
    if "prepared statement" in text or sqlstate == "26000":
        return True
    if sqlstate in ("57P01", "57P02", "57P03", "08006", "08001", "08003", "08004", "40001"):
        return True
    return any(
        token in text
        for token in (
            "connection refused",
            "connection reset",
            "server closed the connection",
            "timeout",
            "too many connections",
            "cannot connect",
            "connection was closed",
            "ssl connection has been closed",
            "broken pipe",
            "connectiondoesnotexisterror",
            "interfacederror",
            "operationalerror",
        )
    )


def schema_drift_detail(exc: Exception) -> str:
    """Build a client-safe message for database errors caused by missing migrations.

    Args:
        exc: Database exception (typically ``sqlalchemy.exc.ProgrammingError``).

    Returns:
        A migration hint when the error is an undefined column/table, otherwise a
        generic message (raw driver text is not echoed to clients).
    """
    if is_schema_drift_error(exc):
        return (
            "Database schema is out of date. Apply pending migrations "
            "(`supabase migration up --local`, or `supabase db push` for a hosted "
            "project), then retry."
        )
    return "Database query failed"


class AssessmentNotFoundError(Exception):
    """Assessment is not in the candidate's package."""


class AssessmentTimeExpiredError(Exception):
    """Strict-timer module passed its server-side deadline; further saves are rejected."""

    detail = "Time limit reached. This section is locked; submit to finalize."

    def __init__(self) -> None:
        super().__init__(self.detail)


class PackageNotOpenError(Exception):
    """Candidate activity attempted before the package's open_time."""

    code = "PACKAGE_NOT_OPEN"

    def __init__(self, opens_at: str) -> None:
        self.detail = f"This assessment opens on {opens_at}."
        super().__init__(self.detail)


class PackageClosedError(Exception):
    """Candidate tried to start new work after the package's close_time."""

    code = "PACKAGE_CLOSED"

    def __init__(self, closed_at: str) -> None:
        self.detail = f"This assessment closed on {closed_at}."
        super().__init__(self.detail)


class UnknownQuestionError(Exception):
    """Candidate wrote an answer for a question id that is not in the module's bank."""

    code = "UNKNOWN_QUESTION"
    detail = "Question is not part of this assessment."

    def __init__(self) -> None:
        super().__init__(self.detail)


class AssessmentAlreadySubmittedError(Exception):
    """Writes and retakes are locked after a candidate submits."""

    detail = "Assessment already completed. Modifications are locked."

    def __init__(self) -> None:
        super().__init__(self.detail)
