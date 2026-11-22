"""Flatten a SectionMap into the plain text the scorer reads."""

from callback.models.section_map import SectionMap


def sections_to_text(section_map: SectionMap) -> str:  # noqa: C901
    """Convert a SectionMap to flat text suitable for scoring."""
    parts: list[str] = []
    if section_map.summary:
        parts.append(section_map.summary)
    skills = section_map.skills
    skill_chunks: list[str] = []
    if skills.flat:
        skill_chunks.append(", ".join(skills.flat))
    for cat, items in skills.categorized.items():
        skill_chunks.append(f"{cat}: {', '.join(items)}")
    if skill_chunks:
        parts.append("Skills")
        parts.append("\n".join(skill_chunks))
    if section_map.experience:
        parts.append("Experience")
    for exp in section_map.experience:
        header = f"{exp.company} | {exp.role}"
        lines = [header] + exp.bullets
        parts.append("\n".join(lines))
    if section_map.education:
        parts.append("Education")
    for edu in section_map.education:
        parts.append(edu.institution or "")
    for proj in section_map.projects:
        lines = [proj.name] + proj.bullets
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
