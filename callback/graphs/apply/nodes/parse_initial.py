"""Apply node: load the base resume's sections and text for tailoring and scoring."""

import json
import logging

from callback.config.observability import record_decision, trace_node
from callback.graphs.node_log import log_enter
from callback.models.section_map import SectionMap
from callback.models.state import ApplyState
from callback.repositories import story_migration
from callback.repositories.resumes import ResumeNotFoundError, get_resume
from callback.repositories.wiki import WikiStore
from callback.services import extractor as resume_extractor
from callback.services.experience_years import candidate_experience_years
from callback.services.section_text import sections_to_text

logger = logging.getLogger("callback.apply_nodes")


def _load_wiki_sections(resume_label: str) -> tuple[str, str, str]:
    """Load sections.json and index.md from wiki.

    Returns (sections_json, wiki_index, resume_text) where resume_text is empty
    when sections_json is empty.
    """
    store = WikiStore()
    pages = store.read_pages(resume_label, ["sections.json", "index.md"])
    sections_json = pages.get("sections.json", "")
    wiki_index = pages.get("index.md", "")
    if not sections_json:
        return "", "", ""
    section_map = SectionMap.model_validate_json(sections_json)
    resume_text = sections_to_text(section_map)
    return sections_json, wiki_index, resume_text


@trace_node("apply", "parse_initial")
def parse_initial(state: ApplyState) -> dict:
    """Load sections.json from wiki for tailoring; extract original PDF for scoring."""
    log_enter(logger, "parse_initial", state)
    if state.resume_label is None:
        record_decision("initial_score_source", "none")
        return {"parsed_initial": "<noop:parse:no-source>"}

    # The apply path may be the first thing run after an upgrade; legacy story
    # pages must carry frontmatter before submit_keywords ranks them.
    story_migration.migrate_legacy_stories(state.resume_label)
    sections_json, wiki_index, sections_text = _load_wiki_sections(state.resume_label)
    base: dict = {}
    if sections_json:
        section_map = SectionMap.model_validate_json(sections_json)
        base = {
            "sections": section_map.model_dump(),
            "wiki_index": wiki_index,
            "candidate_years": candidate_experience_years(section_map.experience),
        }

    try:
        resume_path = get_resume(state.resume_label)
    except ResumeNotFoundError:
        fallback = sections_text if sections_json else "<noop:parse:no-source>"
        logger.warning(
            json.dumps(
                {
                    "node": "parse_initial",
                    "event": "resume_not_found",
                    "resume_label": state.resume_label,
                    "fallback": "sections_text" if sections_json else "noop",
                }
            )
        )
        record_decision("initial_score_source", "sections_text" if sections_json else "none")
        return {**base, "parsed_initial": fallback}

    text = resume_extractor.extract(resume_path)
    record_decision("initial_score_source", "resume_file")
    return {**base, "parsed_initial": text}
