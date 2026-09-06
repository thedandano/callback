"""Stories live as OKF markdown pages under <wiki>/<label>/experience/story-NNN.md.

The page is the original. JSON caches (compiled_profile.json) are rebuilt from
these files and never the other way round.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from callback.repository.accomplishments import AccomplishmentsStore
from callback.state import CreatedStory
from callback.wiki import WikiPageError, WikiStore, join_frontmatter, split_frontmatter

logger = logging.getLogger(__name__)

STORY_TYPES = ("story", "project")
_PROJECT_JOB_TITLE = "Project"
_STORY_FILE_RE = re.compile(r"^story-(\d{3,})\.md$")
_LABELS = ("Situation", "Behavior", "Impact")
_PARAGRAPH_RE = re.compile(
    r"^\*\*(Situation|Behavior|Impact):\*\*\s*(.*?)\s*"
    r"(?=^\*\*(?:Situation|Behavior|Impact):\*\*|\Z)",
    re.M | re.S,
)


def story_page_id(story_id: str) -> str:
    return f"experience/{story_id}.md"


def _story_id_from_page_id(page_id: str) -> str:
    return page_id.rsplit("/", 1)[-1].removesuffix(".md")


def story_to_page(story: CreatedStory, timestamp: str) -> str:
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
    found = {label: text for label, text in _PARAGRAPH_RE.findall(body)}
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


def _tags_from_meta(meta: dict) -> list[str]:
    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        raise WikiPageError(f"tags must be a list, got {type(tags).__name__}")
    return [str(t) for t in tags]


def story_from_page(page_id: str, content: str) -> CreatedStory:
    """Rebuild a CreatedStory from a page. Raises WikiPageError when it is not a story."""
    meta, body = split_frontmatter(content)
    _story_type_from_meta(page_id, meta)
    paragraphs = _body_paragraphs(page_id, body)
    return CreatedStory(
        id=_story_id_from_page_id(page_id),
        primary_skill=str(meta.get("title", "")),
        skills=_tags_from_meta(meta),
        story_type=str(meta.get("story_type", "")),
        job_title=str(meta.get("job_title", "")),
        situation=paragraphs["Situation"],
        behavior=paragraphs["Behavior"],
        impact=paragraphs["Impact"],
    )


def _story_page_ids(resume_label: str) -> list[str]:
    exp_dir = WikiStore().wiki_root(resume_label) / "experience"
    if not exp_dir.is_dir():
        return []
    return [f"experience/{p.name}" for p in sorted(exp_dir.iterdir()) if p.suffix == ".md"]


def list_stories(resume_label: str) -> tuple[list[CreatedStory], list[str]]:
    """Every readable story page in id order, plus one warning per page skipped."""
    page_ids = _story_page_ids(resume_label)
    pages = WikiStore().read_pages(resume_label, page_ids)
    found: list[CreatedStory] = []
    warnings: list[str] = []
    for page_id in page_ids:
        try:
            found.append(story_from_page(page_id, pages[page_id]))
        except WikiPageError as exc:
            message = f"{page_id}: skipped: {exc}"
            logger.warning(message)
            warnings.append(message)
    return found, warnings


def next_story_id(resume_label: str) -> str:
    highest = 0
    for page_id in _story_page_ids(resume_label):
        match = _STORY_FILE_RE.match(page_id.rsplit("/", 1)[-1])
        if match:
            highest = max(highest, int(match.group(1)))
    return f"story-{highest + 1:03d}"


def save_story(resume_label: str, story: CreatedStory) -> CreatedStory:
    """Write one story page. An identical story (all fields but id) returns the stored one."""
    content = story.model_dump(exclude={"id"})
    existing, _ = list_stories(resume_label)
    for stored in existing:
        if stored.model_dump(exclude={"id"}) == content:
            return stored
    saved = story.model_copy(update={"id": next_story_id(resume_label)})
    timestamp = datetime.now(UTC).isoformat()
    WikiStore().write_page(resume_label, story_page_id(saved.id), story_to_page(saved, timestamp))
    logger.info("story written: %s (%s)", story_page_id(saved.id), saved.primary_skill)
    return saved


def _needs_page(resume_label: str, page_id: str) -> bool:
    """True when the page is missing or is an old render without frontmatter."""
    content = WikiStore().read_pages(resume_label, [page_id])[page_id]
    return not content or not content.startswith("---\n")


def migrate_legacy_stories(resume_label: str) -> int:
    """One-time move of stories from accomplishments.json to OKF pages.

    Writes a page only where none exists or the existing one is a pre-OKF
    render (no frontmatter); a page that already has frontmatter is the
    original and is left alone. Then drops the stories from the JSON so this
    never runs twice. Returns the number of pages written.
    """
    store = AccomplishmentsStore()
    legacy = store.legacy_stories()
    if not legacy:
        return 0
    timestamp = datetime.now(UTC).isoformat()
    written = 0
    for record in legacy:
        story = CreatedStory.model_validate(record)
        page_id = story_page_id(story.id)
        if _needs_page(resume_label, page_id):
            WikiStore().write_page(resume_label, page_id, story_to_page(story, timestamp))
            written += 1
    store.drop_legacy_stories()
    logger.info(
        "legacy stories migrated: %d of %d pages written under %s; "
        "accomplishments.json now holds onboard_text only",
        written,
        len(legacy),
        resume_label,
    )
    return written
