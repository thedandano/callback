from callback.state import CompiledProfile, CreatedStory
from callback.wiki import WikiStore, company_slug

_WIKI_STORE = WikiStore()


def _experience_page_content(story: CreatedStory) -> str:
    skills_line = ", ".join(sorted(story.skills)) if story.skills else ""
    return (
        f"# {story.primary_skill} — {story.story_type.title()}\n\n"
        f"**Job Title:** {story.job_title}\n\n"
        f"Skills: {skills_line}\n\n"
        f"**Situation:** {story.situation}\n\n"
        f"**Behavior:** {story.behavior}\n\n"
        f"**Impact:** {story.impact}\n"
    )


def _story_page_id(story: CreatedStory) -> str:
    return f"experience/{story.id}.md"


def _skill_story_map(stories: list[CreatedStory]) -> dict[str, CreatedStory]:
    mapping: dict[str, CreatedStory] = {}
    for story in stories:
        for s in [story.primary_skill, *story.skills]:
            if s.lower() not in mapping:
                mapping[s.lower()] = story
    return mapping


def _skill_lines(skills_index: list[str], skill_map: dict[str, CreatedStory]) -> list[str]:
    lines = []
    for skill in skills_index:
        story = skill_map.get(skill.lower())
        line = f"- [{skill}]({_story_page_id(story)})" if story else f"- {skill}"
        lines.append(line)
    return lines


def _index_content(profile: CompiledProfile) -> str:
    skill_map = _skill_story_map(profile.stories)
    lines: list[str] = ["# Profile Index\n", "## Skills\n"]
    lines.extend(_skill_lines(profile.skills_index, skill_map))
    if profile.orphaned_skills:
        lines.append("\n## Orphaned Skills\n")
        lines.extend(f"- {o.skill}" for o in profile.orphaned_skills)
    return "\n".join(lines) + "\n"


class WikiRenderer:
    def __init__(self, store: WikiStore | None = None) -> None:
        self._store = store or _WIKI_STORE

    def render_experience_page(self, resume_label: str, story: CreatedStory) -> None:
        slug = company_slug(story.id)
        self._store.write_experience_page(resume_label, slug, _experience_page_content(story))

    def render_index(self, resume_label: str, profile: CompiledProfile) -> None:
        self._store.write_index(resume_label, _index_content(profile))
