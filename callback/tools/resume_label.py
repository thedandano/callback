"""Pick the registered resume label for a new session."""

from callback.config.logging import log
from callback.config.observability import (
    record_decision,
)
from callback.models.envelope import err
from callback.repositories.resumes import list_resumes


def resolve_resume_label(session_id: str) -> tuple[str | None, dict | None]:
    """Return (label, None) for the registered resume, or (None, error envelope)."""
    registered = list_resumes()
    if not registered:
        return None, err(
            stage="load_jd",
            code="no_resume_registered",
            message="no resume registered; run onboard_user first",
            session_id=session_id,
            retriable=False,
        )
    if len(registered) > 1:
        log(
            "WARNING",
            {
                "tool": "load_jd",
                "session_id": session_id,
                "event": "multiple resumes registered; using first",
                "registered": registered,
            },
        )
    record_decision("resume_pick", "first_of_many" if len(registered) > 1 else "only_one")
    return registered[0], None


def resolve_new_thread_resume_label(stage: str, session_id: str) -> str | None:
    """Resolve resume_label for a new profile thread, logging when unresolved.

    A missing resume registry does not stop the profile graph — it just means
    the wiki write falls back to _registered_label's own default — but the
    tool logs the miss so it's visible in callback logs.
    """
    resume_label, label_error = resolve_resume_label(session_id)
    if label_error is not None:
        log(
            "INFO",
            {"tool": stage, "session_id": session_id, "event": "resume_label_unresolved"},
        )
    return resume_label
