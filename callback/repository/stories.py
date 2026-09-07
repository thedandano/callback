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
from callback.wiki import (
    WikiPageError,
    WikiPageIdError,
    WikiStore,
    join_frontmatter,
    split_frontmatter,
)

logger = logging.getLogger(__name__)

STORY_TYPES = ("story", "project")
_PROJECT_JOB_TITLE = "Project"
_STORY_FILE_RE = re.compile(r"^story-(\d{3,})\.md$")
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


def label_line_field(story: CreatedStory) -> str | None:
    """Name of the first body field holding a line that starts with a structural label."""
    for field in _BODY_FIELDS:
        if _LABEL_LINE_RE.search(getattr(story, field)):
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


def _story_page_ids(resume_label: str) -> list[str]:
    exp_dir = WikiStore().wiki_root(resume_label) / "experience"
    if not exp_dir.is_dir():
        return []
    return [f"experience/{p.name}" for p in sorted(exp_dir.iterdir()) if p.suffix == ".md"]


def _read_page(resume_label: str, page_id: str) -> str:
    """One page's text. Raises WikiPageError when the file cannot be read or decoded."""
    try:
        return WikiStore().read_pages(resume_label, [page_id])[page_id]
    except UnicodeDecodeError as exc:
        raise WikiPageError(f"file is not valid UTF-8 ({exc.reason} at byte {exc.start})") from exc
    except OSError as exc:
        raise WikiPageError(f"file could not be read ({type(exc).__name__}: {exc})") from exc


def list_stories(resume_label: str) -> tuple[list[CreatedStory], list[str]]:
    """Every readable story page in id order, plus one warning per page skipped."""
    stories: list[CreatedStory] = []
    warnings: list[str] = []
    for page_id in _story_page_ids(resume_label):
        try:
            stories.append(story_from_page(page_id, _read_page(resume_label, page_id)))
        except (WikiPageError, WikiPageIdError) as exc:
            message = f"{page_id}: skipped: {exc}"
            logger.warning(message)
            warnings.append(message)
    return stories, warnings


def next_story_id(resume_label: str) -> str:
    """One past the highest story-NNN on disk or still held in the legacy JSON.

    Legacy records the migration skipped (invalid, or their page unreadable)
    keep their ids reserved so a new story can never take one.
    """
    names = [page_id.rsplit("/", 1)[-1] for page_id in _story_page_ids(resume_label)]
    names += [
        f"{record.get('id')}.md"
        for record in AccomplishmentsStore().legacy_stories()
        if isinstance(record, dict)
    ]
    highest = 0
    for name in names:
        match = _STORY_FILE_RE.match(name)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"story-{highest + 1:03d}"


def _canonical(story: CreatedStory) -> CreatedStory:
    """Strip the body paragraphs the way reading a page back does, so equality holds."""
    return story.model_copy(
        update={f: getattr(story, f).replace("\r\n", "\n").strip() for f in _BODY_FIELDS}
    )


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
            story = CreatedStory.model_validate(record)
            if not _STORY_FILE_RE.match(f"{story.id}.md"):
                raise ValueError(f"id {story.id!r} is not of the form story-NNN")
            if (field := label_line_field(story)) is not None:
                raise ValueError(f"{field} holds a line starting with a structural label")
            valid.append(story)
        except (ValidationError, ValueError) as exc:
            fallback = f"#{index}"
            ident = str(record.get("id") or fallback) if isinstance(record, dict) else fallback
            logger.warning("legacy story %s skipped: not a valid story: %s", ident, exc)
            skipped.append(ident)
    return valid, skipped


def _may_overwrite(page_id: str, existing: str) -> bool:
    """True only for an empty page or a pre-OKF render with no fence at all.

    Any page that opens with a fence is someone's edit and is left alone: valid
    frontmatter (even an empty mapping) or a malformed one both keep the JSON
    copy until the page is repaired, because read-back verification will fail.
    """
    if not existing:
        return True
    if not existing.lstrip("\ufeff").replace("\r\n", "\n").startswith("---\n"):
        return True
    try:
        split_frontmatter(existing)
    except WikiPageError as exc:
        logger.warning("%s: left alone; existing page has a malformed fence (%s)", page_id, exc)
        return False
    logger.info("%s: left alone; page already has a frontmatter fence", page_id)
    return False


def _write_legacy_page(resume_label: str, story: CreatedStory, timestamp: str) -> bool:
    """Write the page unless one with frontmatter already exists. Returns True when written."""
    page_id = story_page_id(story.id)
    try:
        existing = _read_page(resume_label, page_id)
    except (WikiPageError, WikiPageIdError) as exc:
        logger.warning("%s: left alone; %s", page_id, exc)
        return False
    if not _may_overwrite(page_id, existing):
        return False
    WikiStore().write_page(resume_label, page_id, story_to_page(story, timestamp))
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
    written_ids: set[str],
) -> None:
    """Drop the JSON stories only when every legacy story reads back.

    Pages written this run must read back with identical content; pages left
    alone (they already had frontmatter) only need to exist.
    """
    listed, _ = list_stories(resume_label)
    by_id = {s.id: s for s in listed}
    missing = [s.id for s in expected if s.id not in by_id]
    mismatched = [
        s.id
        for s in expected
        if s.id in written_ids
        and s.id in by_id
        and by_id[s.id].model_dump(exclude={"id"}) != _canonical(s).model_dump(exclude={"id"})
    ]
    if skipped or missing or mismatched:
        logger.warning(
            "legacy stories kept in accomplishments.json: "
            "%d invalid (%s), %d not readable after write (%s), %d read back differently (%s)",
            len(skipped),
            ", ".join(skipped) or "-",
            len(missing),
            ", ".join(missing) or "-",
            len(mismatched),
            ", ".join(mismatched) or "-",
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
    written_ids = {s.id for s in stories if _write_legacy_page(resume_label, s, timestamp)}
    _drop_legacy_if_complete(store, resume_label, stories, skipped, written_ids)
    return len(written_ids)
