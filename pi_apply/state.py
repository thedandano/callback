from pydantic import BaseModel, Field


class TailoredResume(BaseModel):
    name: str
    location: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    website: str | None = None
    title: str | None = None
    summary: str | None = None
    skills_raw: str | None = None
    experience_raw: str | None = None
    projects_raw: str | None = None
    volunteer_raw: str | None = None
    education_raw: str | None = None
    max_pages: int = 1


class ApplyState(BaseModel):
    """Per-session state for the apply graph."""

    session_id: str
    jd_url: str | None = Field(default=None)
    jd_raw_text: str | None = Field(default=None)
    jd_text: str | None = Field(default=None)
    keywords: dict | None = Field(default=None)
    resume_path: str | None = Field(default=None)
    resume_label: str | None = Field(default=None)
    sections: dict | None = Field(default=None)
    wiki_index: str | None = Field(default=None)
    parsed_initial: str | None = Field(default=None)
    parsed_final: str | None = Field(default=None)
    score_initial: dict | None = Field(default=None)
    score_final: dict | None = Field(default=None)
    tailored: TailoredResume | None = Field(default=None)
    tailored_sections: dict | None = Field(default=None)
    pdf_path: str | None = Field(default=None)
    report: dict | None = Field(default=None)
    uncovered_skills: list | None = Field(default=None)
    finalized: bool | None = Field(default=None)
    error: str | None = Field(default=None)


class ProfileState(BaseModel):
    """Per-session state for the profile graph."""

    session_id: str
    profile_exists: bool | None = Field(default=None)
    resume_label: str | None = Field(default=None)
    resume_path: str | None = Field(default=None)
    sections: dict | None = Field(default=None)
    wiki_path: str | None = Field(default=None)
    intake: dict | None = Field(default=None)
    compiled_profile: dict | None = Field(default=None)
    orphaned_skills: list | None = Field(default=None)
    current_story_target: str | None = Field(default=None)
    error: str | None = Field(default=None)
