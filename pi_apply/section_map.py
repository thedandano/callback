"""SectionMap data model and edit application for holistic-tailor."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

_EXP_BULLET_RE = re.compile(r"^exp-(\d+)-b(\d+)$")
_EXP_CTX_RE = re.compile(r"^exp-(\d+)-context$")
_PROJ_DESC_RE = re.compile(r"^proj-(\d+)-desc$")
_PROJ_BULLET_RE = re.compile(r"^proj-(\d+)-b(\d+)$")
_SKILLS_IDX_RE = re.compile(r"^skills-(\d+)$")

_EDITABLE = {"summary", "skills", "experience", "projects"}


class SkillsSection(BaseModel):
    flat: list[str] = []
    categorized: dict[str, list[str]] = {}


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
    contact: str | None = None
    certifications: list[str] = []
    awards: list[str] = []


@dataclass
class EditResult:
    applied: bool
    rejection_reason: str | None = None


def _validate_experience_target(entries: list[ExperienceEntry], target: str) -> str | None:
    m = _EXP_BULLET_RE.match(target)
    if m:
        i, j = int(m.group(1)), int(m.group(2))
        if i >= len(entries):
            return f"experience index {i} out of bounds (have {len(entries)})"
        if j >= len(entries[i].bullets):
            n = len(entries[i].bullets)
            return f"experience[{i}] bullet index {j} out of bounds (have {n})"
        return None
    m = _EXP_CTX_RE.match(target)
    if m:
        i = int(m.group(1))
        if i >= len(entries):
            return f"experience index {i} out of bounds (have {len(entries)})"
        return None
    if target:
        return f"invalid experience target format: {target}"
    return None


def _validate_project_target(projects: list[ProjectEntry], target: str) -> str | None:
    m = _PROJ_DESC_RE.match(target)
    if m:
        i = int(m.group(1))
        if i >= len(projects):
            return f"project index {i} out of bounds (have {len(projects)})"
        return None
    m = _PROJ_BULLET_RE.match(target)
    if m:
        i, j = int(m.group(1)), int(m.group(2))
        if i >= len(projects):
            return f"project index {i} out of bounds (have {len(projects)})"
        if j >= len(projects[i].bullets):
            n = len(projects[i].bullets)
            return f"projects[{i}] bullet index {j} out of bounds (have {n})"
        return None
    if target:
        return f"invalid project target format: {target}"
    return None


def validate_edit_target(section_map: SectionMap, edit: dict[str, Any]) -> str | None:
    """Return rejection reason or None if valid."""
    section = edit.get("section", "")
    if section not in _EDITABLE:
        return f"non-editable section: {section}"
    target = edit.get("target", "")
    if section == "experience":
        return _validate_experience_target(section_map.experience, target)
    if section == "projects":
        return _validate_project_target(section_map.projects, target)
    return None


def _apply_skills_edit(section_map: SectionMap, edit: dict[str, Any]) -> None:
    op = edit.get("op", "replace")
    target = edit.get("target", "")
    value: str = edit.get("value", "")
    category = edit.get("category")
    if category:
        if op == "add":
            section_map.skills.categorized.setdefault(category, []).append(value)
        else:
            section_map.skills.categorized[category] = [value]
    elif op == "add":
        section_map.skills.flat.append(value)
    else:
        m = _SKILLS_IDX_RE.match(target)
        if m:
            section_map.skills.flat[int(m.group(1))] = value
        else:
            section_map.skills.flat = [value]


def _apply_experience_edit(entry: ExperienceEntry, target: str, value: str) -> None:
    m = _EXP_BULLET_RE.match(target)
    if m:
        entry.bullets[int(m.group(2))] = value
        return
    m = _EXP_CTX_RE.match(target)
    if m:
        entry.context_line = value


def _apply_project_edit(project: ProjectEntry, target: str, value: str) -> None:
    if _PROJ_DESC_RE.match(target):
        project.description = value
        return
    m = _PROJ_BULLET_RE.match(target)
    if m:
        project.bullets[int(m.group(2))] = value


def apply_edit(section_map: SectionMap, edit: dict[str, Any]) -> EditResult:
    """Apply a structured edit to section_map in-place."""
    reason = validate_edit_target(section_map, edit)
    if reason is not None:
        return EditResult(applied=False, rejection_reason=reason)

    section = edit.get("section", "")
    target = edit.get("target", "")
    value: str = edit.get("value", "")

    if section == "summary":
        section_map.summary = value
    elif section == "skills":
        _apply_skills_edit(section_map, edit)
    elif section == "experience":
        i = int((_EXP_BULLET_RE.match(target) or _EXP_CTX_RE.match(target)).group(1))  # type: ignore[union-attr]
        _apply_experience_edit(section_map.experience[i], target, value)
    elif section == "projects":
        i = int((_PROJ_DESC_RE.match(target) or _PROJ_BULLET_RE.match(target)).group(1))  # type: ignore[union-attr]
        _apply_project_edit(section_map.projects[i], target, value)

    return EditResult(applied=True)
