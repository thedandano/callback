"""Project candidate ranking, layout and bullet-trim recommendations."""

import re

from callback.config.logging import log
from callback.repositories.story_pages import tags_from_meta
from callback.repositories.wiki import WikiPageError, WikiStore, split_frontmatter
from callback.services.keyword_coverage import matched_keywords

_WIKI_LINK_RE = re.compile(r"\[[^\]]+\]\((experience/[^)]+\.md)\)")


def _read_project_page(resume_label: str, page_id: str) -> str | None:
    """One page's text, or None (logged) when the file cannot be read or decoded."""
    try:
        return WikiStore().read_pages(resume_label, [page_id])[page_id]
    except (UnicodeDecodeError, OSError) as exc:
        log(
            "WARNING",
            {
                "tool": "submit_keywords",
                "event": "story_page_unreadable",
                "page_id": page_id,
                "reason": f"{type(exc).__name__}: {exc}",
            },
        )
        return None


def _project_page_meta(page_id: str, content: str) -> dict | None:
    """Frontmatter of a project page; None (logged) for non-projects and unreadable pages."""
    try:
        meta, _ = split_frontmatter(content)
    except WikiPageError as exc:
        log(
            "WARNING",
            {
                "tool": "submit_keywords",
                "event": "story_page_unreadable",
                "page_id": page_id,
                "reason": str(exc),
            },
        )
        return None
    if not meta:
        log(
            "WARNING",
            {
                "tool": "submit_keywords",
                "event": "story_page_without_frontmatter",
                "page_id": page_id,
            },
        )
        return None
    if meta.get("type") != "project":
        return None
    try:
        meta["tags"] = tags_from_meta(meta)
    except WikiPageError as exc:
        log(
            "WARNING",
            {
                "tool": "submit_keywords",
                "event": "story_page_unreadable",
                "page_id": page_id,
                "reason": str(exc),
            },
        )
        return None
    return meta


def _evidence_preview(content: str) -> str:
    lines = [
        line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")
    ]
    return re.sub(r"\s+", " ", " ".join(lines))[:240]


def project_score(required: list[str], preferred: list[str], text: str) -> float:
    possible = len(required) * 2 + len(preferred)
    if possible == 0:
        return 0.0
    matched = len(matched_keywords(required, text)) * 2 + len(matched_keywords(preferred, text))
    return round(matched / possible, 4)


def _project_page_ids(wiki_index: str) -> list[str]:
    seen: set[str] = set()
    page_ids: list[str] = []
    for match in _WIKI_LINK_RE.finditer(wiki_index):
        page_id = match.group(1)
        if page_id not in seen:
            seen.add(page_id)
            page_ids.append(page_id)
    return page_ids


def _valid_project_page_ids(resume_label: str, page_ids: list[str]) -> list[str]:
    """Return page_ids that resolve under the wiki root, logging any that don't."""
    store = WikiStore()
    valid_ids: list[str] = []
    for page_id in page_ids:
        if store.is_valid_page_id(resume_label, page_id):
            valid_ids.append(page_id)
        else:
            log(
                "WARNING",
                {
                    "tool": "submit_keywords",
                    "event": "invalid_wiki_link_skipped",
                    "page_id": page_id,
                },
            )
    return valid_ids


def _candidate(
    page_id: str,
    meta: dict,
    body: str,
    required: list[str],
    preferred: list[str],
) -> dict:
    skills = [str(tag) for tag in (meta.get("tags") or [])]
    title = str(meta.get("title") or "")
    # Headings are dropped: the frontmatter title is the authoritative name, and a
    # stale H1 left behind by a hand edit must not keep matching the old skill.
    paragraphs = "\n".join(line for line in body.splitlines() if not line.startswith("#"))
    match_text = f"{title}\n{paragraphs}\n{', '.join(skills)}"
    return {
        "page_id": page_id,
        "name": str(meta.get("title") or ""),
        "skills": skills,
        "score": project_score(required, preferred, match_text),
        "required_matched": matched_keywords(required, match_text),
        "preferred_matched": matched_keywords(preferred, match_text),
        "evidence_preview": _evidence_preview(body),
    }


def rank_project_candidates(resume_label: str, keywords: dict, wiki_index: str) -> list[dict]:
    required = keywords.get("required") or []
    preferred = keywords.get("preferred") or []
    page_ids = _valid_project_page_ids(resume_label, _project_page_ids(wiki_index))
    candidates: list[dict] = []
    for page_id in page_ids:
        content = _read_project_page(resume_label, page_id)
        if content is None:
            continue
        meta = _project_page_meta(page_id, content)
        if meta is None:
            continue
        _, body = split_frontmatter(content)
        candidate = _candidate(page_id, meta, body, required, preferred)
        if candidate["score"] == 0:
            continue
        candidates.append(candidate)
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate["score"],
            len(candidate["required_matched"]),
            len(candidate["preferred_matched"]),
            candidate["name"],
        ),
        reverse=True,
    )


def _project_text(project: dict) -> str:
    parts = [project.get("name") or "", project.get("description") or ""]
    parts.extend(project.get("bullets") or [])
    return "\n".join(parts)


def project_swap_recommendation(
    candidates: list[dict], keywords: dict, sections: dict
) -> dict | None:
    projects = sections.get("projects") or []
    if not candidates or not projects:
        return None

    required = keywords.get("required") or []
    preferred = keywords.get("preferred") or []
    scored_projects = [
        (index, project_score(required, preferred, _project_text(project)))
        for index, project in enumerate(projects)
    ]
    replace_index, visible_score = min(scored_projects, key=lambda item: item[1])
    candidate = candidates[0]
    if candidate["score"] <= visible_score:
        return None
    return {
        "replace_target": f"proj-{replace_index}",
        "visible_project_score": visible_score,
        "candidate": candidate,
    }


_MAX_VISIBLE_PROJECTS = 2


def project_layout_recommendation(candidates: list[dict], keywords: dict, sections: dict) -> dict:
    recommendation: dict = {
        "strategy": "none",
        "max_visible_projects": _MAX_VISIBLE_PROJECTS,
    }
    if not candidates:
        return recommendation

    projects = sections.get("projects") or []
    if len(projects) < _MAX_VISIBLE_PROJECTS:
        return {
            **recommendation,
            "strategy": "append",
            "add_target": "proj-end",
            "candidate": candidates[0],
        }

    swap = project_swap_recommendation(candidates, keywords, sections)
    if not swap:
        return recommendation
    return {
        **recommendation,
        "strategy": "replace",
        "replace_target": swap["replace_target"],
        "visible_project_score": swap["visible_project_score"],
        "candidate": swap["candidate"],
    }


def _bullet_trim_candidate(section: str, target: str, text: str, keywords: dict) -> dict:
    required = keywords.get("required") or []
    preferred = keywords.get("preferred") or []
    return {
        "target": target,
        "section": section,
        "text": text,
        "required_matched": matched_keywords(required, text),
        "preferred_matched": matched_keywords(preferred, text),
        "score": project_score(required, preferred, text),
    }


def trim_candidates(keywords: dict, sections: dict) -> list[dict]:
    candidates: list[dict] = []
    for exp_index, entry in enumerate(sections.get("experience") or []):
        for bullet_index, bullet in enumerate(entry.get("bullets") or []):
            candidates.append(
                _bullet_trim_candidate(
                    "experience",
                    f"exp-{exp_index}-b{bullet_index}",
                    str(bullet),
                    keywords,
                )
            )
    for project_index, project in enumerate(sections.get("projects") or []):
        for bullet_index, bullet in enumerate(project.get("bullets") or []):
            candidates.append(
                _bullet_trim_candidate(
                    "projects",
                    f"proj-{project_index}-b{bullet_index}",
                    str(bullet),
                    keywords,
                )
            )
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate["score"],
            len(candidate["required_matched"]),
            len(candidate["preferred_matched"]),
            candidate["target"],
        ),
    )
