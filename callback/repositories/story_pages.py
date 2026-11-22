"""Story page format: one story to and from its markdown page text. No file access."""

from __future__ import annotations

import logging
import re

from callback.models.profile import CreatedStory
from callback.repositories.wiki import (
    WikiPageError,
    join_frontmatter,
    split_frontmatter,
)

logger = logging.getLogger(__name__)

STORY_TYPES = ("story", "project")
_PROJECT_JOB_TITLE = "Project"
STORY_FILE_RE = re.compile(r"^story-(\d{3,})\.md$")
_LABELS = ("Situation", "Behavior", "Impact")
_BODY_FIELDS = ("situation", "behavior", "impact")
_PARAGRAPH_RE = re.compile(
    r"^\*\*(Situation|Behavior|Impact):\*\*\s*(.*?)\s*"
    r"(?=^\*\*(?:Situation|Behavior|Impact):\*\*|\Z)",
    re.M | re.S,
)


def story_page_id(story_id: str) -> str:
    return f"experience/{story_id}.md"


def _story_id_from_page_id(page_id: str) -> str:
    return page_id.rsplit("/", 1)[-1].removesuffix(".md")


_LABEL_LINE_RE = re.compile(r"^\*\*(?:Situation|Behavior|Impact):\*\*", re.M)


def _normalize_newlines(text: str) -> str:
    """CRLF and lone CR become LF, the form a page reads back as."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def label_line_field(story: CreatedStory) -> str | None:
    """Name of the first body field holding a line that starts with a structural label."""
    for field in _BODY_FIELDS:
        if _LABEL_LINE_RE.search(_normalize_newlines(getattr(story, field))):
            return field
    return None


def story_to_page(story: CreatedStory, timestamp: str) -> str:
    if (field := label_line_field(story)) is not None:
        raise ValueError(
            f"{field} contains a line starting with **Situation:**, **Behavior:**, or "
            "**Impact:**; those mark paragraph boundaries in the page, rephrase it"
        )
    meta = {
        "type": "project" if story.job_title == _PROJECT_JOB_TITLE else "story",
        "title": story.primary_skill,
        "job_title": story.job_title,
        "tags": list(story.skills),
        "story_type": story.story_type,
        "timestamp": timestamp,
    }
    body = (
        f"# {story.primary_skill}\n\n"
        f"**Situation:** {story.situation}\n\n"
        f"**Behavior:** {story.behavior}\n\n"
        f"**Impact:** {story.impact}\n"
    )
    return join_frontmatter(meta, body)


def _body_paragraphs(page_id: str, body: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for label, text in _PARAGRAPH_RE.findall(body):
        if label in found:
            logger.warning("%s: '**%s:**' appears twice; keeping the last", page_id, label)
        found[label] = text
    for label in _LABELS:
        if label not in found:
            logger.warning("%s: no '**%s:**' paragraph in body; stored as empty", page_id, label)
            found[label] = ""
    return found


def _story_type_from_meta(page_id: str, meta: dict) -> None:
    page_type = meta.get("type")
    if page_type not in STORY_TYPES:
        if page_type is None:
            raise WikiPageError("frontmatter has no 'type'")
        raise WikiPageError(f"type {page_type!r} is not a story")


def tags_from_meta(meta: dict) -> list[str]:
    """The page's tags as strings. Raises WikiPageError unless tags is a list (or absent)."""
    tags = meta.get("tags")
    if tags is None:
        return []
    if not isinstance(tags, list):
        raise WikiPageError(f"tags must be a list, got {type(tags).__name__} {tags!r}")
    return [str(t) for t in tags]


def _warn_if_type_disagrees(page_id: str, meta: dict) -> None:
    expected = "project" if meta.get("job_title") == _PROJECT_JOB_TITLE else "story"
    if meta.get("type") != expected:
        logger.warning(
            "%s: type %r disagrees with job_title %r (submit_keywords classifies by type; "
            "set both when regrouping)",
            page_id,
            meta.get("type"),
            meta.get("job_title"),
        )


def story_from_page(page_id: str, content: str) -> CreatedStory:
    """Rebuild a CreatedStory from a page. Raises WikiPageError when it is not a story."""
    meta, body = split_frontmatter(content)
    _story_type_from_meta(page_id, meta)
    _warn_if_type_disagrees(page_id, meta)
    skills = tags_from_meta(meta)
    paragraphs = _body_paragraphs(page_id, body)
    return CreatedStory(
        id=_story_id_from_page_id(page_id),
        primary_skill=str(meta.get("title") or ""),
        skills=skills,
        story_type=str(meta.get("story_type") or ""),
        job_title=str(meta.get("job_title") or ""),
        situation=paragraphs["Situation"],
        behavior=paragraphs["Behavior"],
        impact=paragraphs["Impact"],
    )


def canonical_story(story: CreatedStory) -> CreatedStory:
    """Strip the body paragraphs the way reading a page back does, so equality holds."""
    return story.model_copy(
        update={f: _normalize_newlines(getattr(story, f)).strip() for f in _BODY_FIELDS}
    )
