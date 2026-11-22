"""Stories live as OKF markdown pages under <wiki>/<label>/experience/story-NNN.md.

The page is the original. JSON caches (compiled_profile.json) are rebuilt from
these files and never the other way round.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from callback.models.profile import CreatedStory
from callback.repositories.accomplishments import AccomplishmentsStore
from callback.repositories.story_pages import (
    STORY_FILE_RE,
    canonical_story,
    story_from_page,
    story_page_id,
    story_to_page,
)
from callback.repositories.wiki import (
    WikiPageError,
    WikiPageIdError,
    WikiStore,
)

logger = logging.getLogger(__name__)


def _story_page_ids(resume_label: str) -> list[str]:
    exp_dir = WikiStore().wiki_root(resume_label) / "experience"
    if not exp_dir.is_dir():
        return []
    return [f"experience/{p.name}" for p in sorted(exp_dir.iterdir()) if p.suffix == ".md"]


def read_page(resume_label: str, page_id: str) -> str:
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
            stories.append(story_from_page(page_id, read_page(resume_label, page_id)))
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
        match = STORY_FILE_RE.match(name)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"story-{highest + 1:03d}"


def save_story(resume_label: str, story: CreatedStory) -> CreatedStory:
    """Write one story page. An identical story (all fields but id) returns the stored one."""
    story = canonical_story(story)
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
