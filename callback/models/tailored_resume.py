from pydantic import BaseModel


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
    education_raw: str | None = None
    candidate_experience_years: float | None = None
    max_pages: int = 1
