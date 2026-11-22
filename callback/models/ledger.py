"""Ledger record types."""

from typing import NamedTuple

from pydantic import BaseModel, ConfigDict


def _text_field(keywords: dict | None, name: str) -> str | None:
    value = (keywords or {}).get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


class RunRecord(BaseModel):
    """One tailoring run, shaped like the old <session_id>.json archive."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    timestamp: str
    jd_url: str | None = None
    jd_text: str | None = None
    keywords: dict | None = None
    tailored_resume_text: str | None = None
    pdf_path: str | None = None
    render_page_count: int | None = None
    render_warnings: list = []
    scores: dict = {}
    uncovered_skills: list = []
    outcome: dict = {}

    @property
    def company(self) -> str | None:
        return _text_field(self.keywords, "company")

    @property
    def title(self) -> str | None:
        return _text_field(self.keywords, "title")


class JobNameMatch(NamedTuple):
    """The matching job key, plus every same-name candidate when it is ambiguous."""

    job_key: str | None
    candidates: tuple[str, ...]


class StatusUpdate(BaseModel):
    """One status to record. Name the job by job_key, or by url / company + title."""

    status: str
    recorded_at: str
    note: str | None = None
    source: str
    job_key: str | None = None
    url: str | None = None
    company: str | None = None
    title: str | None = None
    salary_range: str | None = None
