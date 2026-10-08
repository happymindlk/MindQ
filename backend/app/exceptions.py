"""Domain errors for the candidate assessment path."""


def schema_drift_detail(exc: Exception) -> str:
    """Build a client-safe message for database errors caused by missing migrations.

    Args:
        exc: Database exception (typically ``sqlalchemy.exc.ProgrammingError``).

    Returns:
        A migration hint when the error is an undefined column/table, otherwise a
        generic message (raw driver text is not echoed to clients).
    """
    text = str(exc)
    if "does not exist" in text.lower() or "UndefinedColumn" in text or "UndefinedTable" in text:
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


class AssessmentAlreadySubmittedError(Exception):
    """Writes and retakes are locked after a candidate submits."""

    detail = "Assessment already completed. Modifications are locked."

    def __init__(self) -> None:
        super().__init__(self.detail)
