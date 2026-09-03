"""Profile wiki: read/write markdown pages keyed by resume_label."""

from __future__ import annotations

import re
from pathlib import Path

BASE_DIR = Path.home() / ".local" / "share" / "callback" / "profile-wiki"


def company_slug(company_name: str) -> str:
    """Convert company name to lowercase hyphenated alphanumeric slug.

    Examples: "Acme Corp." -> "acme-corp", "AT&T" -> "at-t"
    """
    slug = company_name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


class WikiStore:
    def wiki_root(self, resume_label: str) -> Path:
        return BASE_DIR / resume_label

    def write_index(self, resume_label: str, content: str) -> None:
        root = self.wiki_root(resume_label)
        root.mkdir(parents=True, exist_ok=True)
        (root / "index.md").write_text(content, encoding="utf-8")

    def write_experience_page(self, resume_label: str, company_slug_: str, content: str) -> None:
        exp_dir = self.wiki_root(resume_label) / "experience"
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / f"{company_slug_}.md").write_text(content, encoding="utf-8")

    def _page_path(self, resume_label: str, page_id: str) -> Path:
        """Resolve page_id under the wiki root; reject ids that escape it."""
        root = self.wiki_root(resume_label).resolve()
        path = (root / page_id).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"page_id escapes wiki root: {page_id!r}")
        return path

    def write_page(self, resume_label: str, page_id: str, content: str) -> None:
        """Write any page by page_id (path relative to wiki_root)."""
        p = self._page_path(resume_label, page_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def read_index(self, resume_label: str) -> str | None:
        p = self.wiki_root(resume_label) / "index.md"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def read_pages(self, resume_label: str, page_ids: list[str]) -> dict[str, str]:
        """Return {page_id: content} for each requested page.

        Missing pages return empty string. Raises ValueError for a page_id
        that resolves outside the wiki root.
        """
        result = {}
        for page_id in page_ids:
            p = self._page_path(resume_label, page_id)
            result[page_id] = p.read_text(encoding="utf-8") if p.exists() else ""
        return result
