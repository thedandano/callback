"""Apply node: turn the host's tailored sections into a renderable resume."""

import logging

from pydantic import ValidationError

from callback.config.observability import trace_node
from callback.graphs.node_log import log_enter
from callback.models.section_map import SectionMap
from callback.models.state import ApplyState
from callback.models.tailored_resume import TailoredResume
from callback.services.experience_years import candidate_experience_years

logger = logging.getLogger("callback.apply_nodes")


def _build_skills_raw(skills) -> str | None:
    lines: list[str] = []
    for cat, items in skills.categorized.items():
        lines.append(f"{cat}: {', '.join(items)}")
    if skills.flat:
        lines.append(f"Additional: {', '.join(skills.flat)}")
    return "\n".join(lines) or None


def _build_experience_raw(experience) -> str | None:
    blocks: list[str] = []
    for exp in experience:
        lines = [exp.company]
        role_line = exp.context_line if exp.context_line is not None else exp.role
        start = exp.start_date or ""
        end = exp.end_date or ""
        date_range = f"{start} – {end}" if (start or end) else ""
        if role_line and date_range:
            lines.append(f"{role_line} | {date_range}")
        elif role_line:
            lines.append(role_line)
        elif date_range:
            lines[-1] = f"{lines[-1]} | {date_range}"
        lines.extend(f"• {b}" for b in exp.bullets)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or None


def _split_title_summary(summary: str | None) -> tuple[str | None, str | None]:
    if not summary:
        return None, None
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    if len(lines) > 1 and lines[0] == lines[0].upper() and any(c.isalpha() for c in lines[0]):
        return lines[0], " ".join(lines[1:])
    return None, summary


def _normalize_resume_title(title: str | None) -> str | None:
    if not isinstance(title, str):
        return None
    stripped = title.strip()
    return stripped.upper() if stripped else None


def _headline_from_sections(sections: dict | None) -> str | None:
    """ALL-CAPS headline from the base resume summary, if present.

    Never use the JD title — inventing a role the candidate never held is an
    honesty failure (#142).
    """
    if not isinstance(sections, dict):
        return None
    summary = sections.get("summary")
    if not isinstance(summary, str):
        return None
    title, _ = _split_title_summary(summary)
    return title


def _section_map_to_tailored_resume(
    section_map: SectionMap,
    fallback_title: str | None = None,
) -> TailoredResume:
    """Convert a SectionMap to a TailoredResume for rendering."""
    contact = section_map.contact
    if contact is None:
        raise ValueError("_section_map_to_tailored_resume: section_map.contact is required")
    title, summary = _split_title_summary(section_map.summary)
    title = title or _normalize_resume_title(fallback_title)
    proj_blocks: list[str] = []
    for proj in section_map.projects:
        block_lines = [proj.name]
        if proj.description is not None:
            block_lines.append(proj.description)
        block_lines.extend(f"• {b}" for b in proj.bullets)
        proj_blocks.append("\n".join(block_lines))
    edu_blocks = [f"{edu.institution}\n{edu.degree or ''}" for edu in section_map.education]
    return TailoredResume(
        name=contact.name,
        email=contact.email,
        phone=contact.phone,
        location=contact.location,
        linkedin=contact.linkedin,
        website=contact.website,
        title=title,
        summary=summary,
        skills_raw=_build_skills_raw(section_map.skills),
        experience_raw=_build_experience_raw(section_map.experience),
        projects_raw="\n\n".join(proj_blocks) or None,
        education_raw="\n\n".join(edu_blocks) or None,
        candidate_experience_years=candidate_experience_years(section_map.experience),
        max_pages=1,
    )


@trace_node("apply", "tailor")
def tailor(state: ApplyState) -> dict:
    """Convert tailored_sections SectionMap to TailoredResume, or skip if no_coverage."""
    log_enter(logger, "tailor", state)
    if state.no_coverage:
        return {}  # conditional edge routes to report
    if state.tailored_sections:
        try:
            section_map = SectionMap.model_validate(state.tailored_sections)
            # Base resume headline only — never the JD title (#142).
            fallback_title = _headline_from_sections(state.sections)
            tailored = _section_map_to_tailored_resume(section_map, fallback_title)
            if tailored.title is None:
                logger.warning(
                    "tailor: no resume headline in tailored summary or base sections; "
                    "leaving title empty rather than substituting JD title"
                )
            return {"tailored": tailored}
        except (ValidationError, ValueError) as exc:
            return {"error": f"tailor: invalid tailored_sections: {exc}"}
    return {"error": "tailor: no tailored_sections and no_coverage not set"}
