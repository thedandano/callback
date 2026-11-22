"""Resume-label fallback shared by the compile_profile and create_story nodes."""

from callback.repositories.resumes import list_resumes


def registered_label(state_label: str | None) -> str:
    """Resolve the resume label to use for reading/writing wiki content.

    Uses the state's resume_label when set, else the first registered resume,
    else falls back to "default" (no resumes registered at all).
    """
    if state_label:
        return state_label
    registered = list_resumes()
    return registered[0] if registered else "default"
