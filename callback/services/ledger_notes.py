"""Ledger status-note parsing."""

from callback.repositories import ledger_keys


def contact_note(url: str | None, note: str | None) -> str | None:
    """A non-URL `url` (e.g. a recruiter thread) is kept in the note as `Contact: <value>`.

    A leading or mid-note `Not reportable` marker stays first so export_ledger(mode=contacts)
    still excludes the event; `Contact method:` stays ahead of `Contact:`.
    """
    contact = (url or "").strip()
    if not contact or ledger_keys.url_or_none(contact):
        return note
    not_reportable, method, rest = split_note_markers(note)
    return " | ".join(
        part for part in (not_reportable, method, f"Contact: {contact}", rest) if part
    )


def split_note_markers(note: str | None) -> tuple[str | None, str | None, str | None]:
    """('Not reportable'|None, 'Contact method: X'|None, remaining note)."""
    segments = [part.strip() for part in (note or "").split(" | ") if part.strip()]
    not_reportable = None
    method = None
    rest_parts: list[str] = []
    for part in segments:
        folded = part.casefold()
        if not_reportable is None and folded == "not reportable":
            not_reportable = "Not reportable"
            continue
        if method is None and folded.startswith("contact method:"):
            method = part
            continue
        rest_parts.append(part)
    return not_reportable, method, " | ".join(rest_parts) or None
