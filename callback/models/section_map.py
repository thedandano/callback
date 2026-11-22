"""SectionMap data model."""

from pydantic import BaseModel, Field


class ContactInfo(BaseModel):
    name: str  # required
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    website: str | None = None


class SkillsSection(BaseModel):
    flat: list[str] = []
    categorized: dict[str, list[str]] = {}

    def all_skills(self) -> list[str]:
        """Every skill string: the flat list first, then each category in order."""
        result = list(self.flat)
        for items in self.categorized.values():
            result.extend(items)
        return result


class ExperienceEntry(BaseModel):
    company: str
    role: str
    start_date: str | None = None
    end_date: str | None = None
    context_line: str | None = None
    bullets: list[str] = []


class ProjectEntry(BaseModel):
    name: str
    description: str | None = None
    bullets: list[str] = []


class EducationEntry(BaseModel):
    institution: str
    degree: str | None = None
    field: str | None = None
    graduation_date: str | None = None


class SectionMap(BaseModel):
    summary: str | None = None
    skills: SkillsSection = Field(default_factory=SkillsSection)
    experience: list[ExperienceEntry] = []
    projects: list[ProjectEntry] = []
    education: list[EducationEntry] = []
    contact: ContactInfo | None = None
    certifications: list[str] = []
    awards: list[str] = []
