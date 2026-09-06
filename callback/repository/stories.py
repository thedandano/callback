"""Stories live as OKF markdown pages under <wiki>/<label>/experience/story-NNN.md.

The page is the original. JSON caches (compiled_profile.json) are rebuilt from
these files and never the other way round.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from pydantic import ValidationError

from callback.repository.accomplishments import AccomplishmentsStore
from callback.repository.resumes import list_resumes
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
    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        raise WikiPageError(f"tags must be a list, got {type(tags).__name__}")
    return [str(t) for t in tags]


def story_from_page(page_id: str, content: str) -> CreatedStory:
    """Rebuild a CreatedStory from a page. Raises WikiPageError when it is not a story."""
    meta, body = split_frontmatter(content)
    _story_type_from_meta(page_id, meta)
    skills = tags_from_meta(meta)
    paragraphs = _body_paragraphs(page_id, body)
    return CreatedStory(
        id=_story_id_from_page_id(page_id),
        primary_skill=str(meta.get("title", "")),
        skills=skills,
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


_BODY_FIELDS = ("situation", "behavior", "impact")


def _canonical(story: CreatedStory) -> CreatedStory:
    """Strip the body paragraphs the way reading a page back does, so equality holds."""
    return story.model_copy(update={f: getattr(story, f).strip() for f in _BODY_FIELDS})


def save_story(resume_label: str, story: CreatedStory) -> CreatedStory:
    """Write one story page. An identical story (all fields but id) returns the stored one."""
    story = _canonical(story)
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


def _validate_legacy(records: list[dict]) -> tuple[list[CreatedStory], list[str]]:
    """Validated stories plus the ids (or index) of records that could not be read."""
    valid: list[CreatedStory] = []
    skipped: list[str] = []
    for index, record in enumerate(records):
        try:
            valid.append(CreatedStory.model_validate(record))
        except ValidationError as exc:
            fallback = f"#{index}"
            ident = str(record.get("id") or fallback) if isinstance(record, dict) else fallback
            logger.warning("legacy story %s skipped: not a valid story: %s", ident, exc)
            skipped.append(ident)
    return valid, skipped


def _may_overwrite(page_id: str, existing: str) -> bool:
    """True only for an empty page or a pre-OKF render with no frontmatter.

    Uses the same normalized parser as reading, so a CRLF or BOM page with valid
    frontmatter is recognized. A page with a malformed fence is left alone too:
    the JSON copy is kept (read-back verification fails) until someone fixes it.
    """
    if not existing:
        return True
    try:
        meta, _ = split_frontmatter(existing)
    except WikiPageError as exc:
        logger.warning("%s: left alone; existing page has a malformed fence (%s)", page_id, exc)
        return False
    if meta:
        logger.info("%s: left alone; page already has frontmatter", page_id)
        return False
    return True


def _write_legacy_page(resume_label: str, story: CreatedStory, timestamp: str) -> bool:
    """Write the page unless one with frontmatter already exists. Returns True when written."""
    page_id = story_page_id(story.id)
    store = WikiStore()
    existing = store.read_pages(resume_label, [page_id])[page_id]
    if not _may_overwrite(page_id, existing):
        return False
    store.write_page(resume_label, page_id, story_to_page(story, timestamp))
    logger.info(
        "story migrated: %s (%s, %s)",
        page_id,
        story.primary_skill,
        "overwritten" if existing else "created",
    )
    return True


def _drop_legacy_if_complete(
    store: AccomplishmentsStore,
    resume_label: str,
    expected: list[CreatedStory],
    skipped: list[str],
) -> None:
    listed, _ = list_stories(resume_label)
    present = {s.id for s in listed}
    missing = [s.id for s in expected if s.id not in present]
    if skipped or missing:
        logger.warning(
            "legacy stories kept in accomplishments.json: "
            "%d invalid (%s), %d not readable after write (%s)",
            len(skipped),
            ", ".join(skipped) or "-",
            len(missing),
            ", ".join(missing) or "-",
        )
        return
    store.drop_legacy_stories()
    logger.info(
        "legacy stories migrated under %s; accomplishments.json now holds onboard_text only",
        resume_label,
    )


def migrate_legacy_stories(resume_label: str) -> int:
    """One-time move of stories from accomplishments.json to OKF pages.

    Validates every record first, writes only pages that are missing or lack
    frontmatter (logging each), reads them back, and drops the JSON stories
    only when every one is readable. Returns the number of pages written.
    """
    store = AccomplishmentsStore()
    legacy = store.legacy_stories()
    if not legacy:
        if store.has_legacy_key():
            store.drop_legacy_stories()
            logger.info("accomplishments.json had an empty created_stories list; dropped")
        return 0
    if not list_resumes():
        logger.warning(
            "legacy stories not migrated: no resume registered, so no wiki label to write under"
        )
        return 0
    stories, skipped = _validate_legacy(legacy)
    timestamp = datetime.now(UTC).isoformat()
    written = sum(_write_legacy_page(resume_label, story, timestamp) for story in stories)
    _drop_legacy_if_complete(store, resume_label, stories, skipped)
    return written
