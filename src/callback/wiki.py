"""Profile wiki: read/write markdown pages keyed by resume_label."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from callback import paths


class WikiPageIdError(ValueError):
    """A page_id resolves outside the wiki root."""


class WikiPageError(ValueError):
    """A page's YAML frontmatter is malformed."""


_FENCE = "---\n"


def split_frontmatter(content: str) -> tuple[dict, str]:
    """Split an OKF page into (frontmatter mapping, markdown body).

    A page without a leading fence has no frontmatter: returns ({}, content).
    """
    content = content.lstrip("﻿").replace("\r\n", "\n")
    if not content.startswith(_FENCE):
        return {}, content
    end = content.find("\n" + _FENCE, len(_FENCE) - 1)
    if end < 0:
        raise WikiPageError("frontmatter has no closing '---' fence")
    raw = content[len(_FENCE) : end + 1]
    body = content[end + 1 + len(_FENCE) :]
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise WikiPageError(f"frontmatter is not valid YAML: {exc}") from exc
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise WikiPageError(f"frontmatter must be a mapping, got {type(meta).__name__}")
    return meta, body


def join_frontmatter(meta: dict, body: str) -> str:
    """Join frontmatter mapping and markdown body into OKF format."""
    header = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"{_FENCE}{header}{_FENCE}{body}"


def company_slug(company_name: str) -> str:
    """Convert company name to lowercase hyphenated alphanumeric slug.

    Examples: "Acme Corp." -> "acme-corp", "AT&T" -> "at-t"
    """
    slug = company_name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


class WikiStore:
    def wiki_root(self, resume_label: str) -> Path:
        return paths.wiki_dir() / resume_label

    def write_index(self, resume_label: str, content: str) -> None:
        root = self.wiki_root(resume_label)
        paths.write_text_atomic(root / "index.md", content)

    def write_experience_page(self, resume_label: str, company_slug_: str, content: str) -> None:
        exp_dir = self.wiki_root(resume_label) / "experience"
        paths.write_text_atomic(exp_dir / f"{company_slug_}.md", content)

    def _page_path(self, resume_label: str, page_id: str) -> Path:
        """Resolve page_id under the wiki root; reject ids that escape it."""
        root = self.wiki_root(resume_label).resolve()
        try:
            path = (root / page_id).resolve()
        except (ValueError, OSError) as exc:
            raise WikiPageIdError(f"invalid page_id: {page_id!r}") from exc
        if not path.is_relative_to(root):
            raise WikiPageIdError(f"page_id escapes wiki root: {page_id!r}")
        return path

    def write_page(self, resume_label: str, page_id: str, content: str) -> None:
        """Write any page by page_id (path relative to wiki_root)."""
        p = self._page_path(resume_label, page_id)
        paths.write_text_atomic(p, content)

    def is_valid_page_id(self, resume_label: str, page_id: str) -> bool:
        """Return True when page_id resolves under the wiki root, False otherwise."""
        try:
            self._page_path(resume_label, page_id)
        except WikiPageIdError:
            return False
        return True

    def read_pages(self, resume_label: str, page_ids: list[str]) -> dict[str, str]:
        """Return {page_id: content} for each requested page.

        Missing pages return empty string. Raises ValueError for a page_id
        that resolves outside the wiki root.
        """
        result = {}
        for page_id in page_ids:
            p = self._page_path(resume_label, page_id)
            result[page_id] = p.read_text(encoding="utf-8") if p.is_file() else ""
        return result
