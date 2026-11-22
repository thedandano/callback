"""One-time move of legacy stories from accomplishments.json onto markdown pages."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import ValidationError

from callback.models.profile import CreatedStory
from callback.repositories.accomplishments import AccomplishmentsStore
from callback.repositories.resumes import list_resumes
from callback.repositories.stories import list_stories, read_page
from callback.repositories.story_pages import (
    STORY_FILE_RE,
    canonical_story,
    label_line_field,
    story_page_id,
    story_to_page,
)
from callback.repositories.wiki import (
    WikiPageError,
    WikiPageIdError,
    WikiStore,
    split_frontmatter,
)

logger = logging.getLogger(__name__)


def _validate_legacy(records: list[dict]) -> tuple[list[CreatedStory], list[str]]:
    """Validated stories plus the ids (or index) of records that could not be read."""
    valid: list[CreatedStory] = []
    skipped: list[str] = []
    for index, record in enumerate(records):
        try:
            story = CreatedStory.model_validate(record)
            if not STORY_FILE_RE.match(f"{story.id}.md"):
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
        existing = read_page(resume_label, page_id)
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
        and by_id[s.id].model_dump(exclude={"id"}) != canonical_story(s).model_dump(exclude={"id"})
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
