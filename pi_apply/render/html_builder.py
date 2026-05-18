from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright
from pypdf import PdfReader

_RENDER_DIR = Path(__file__).parent
_TEMPLATE = "resume_template.html.j2"
FONT_B64 = base64.b64encode((_RENDER_DIR / "fonts" / "InterVariable.ttf").read_bytes()).decode()
_CSS_DPI = 96
_LETTER_WIDTH_IN = 8.5
_LETTER_HEIGHT_IN = 11
_PAGE_MARGIN_X_IN = 1.0
_PAGE_MARGIN_Y_IN = 0.46
_PRINTABLE_WIDTH_PX = round((_LETTER_WIDTH_IN - _PAGE_MARGIN_X_IN) * _CSS_DPI)
_PRINTABLE_HEIGHT_PX = (_LETTER_HEIGHT_IN - _PAGE_MARGIN_Y_IN) * _CSS_DPI

_JINJA = Environment(
    loader=FileSystemLoader(str(_RENDER_DIR)),
    autoescape=select_autoescape(("html", "xml")),
)

_DATE_RANGE_TAIL_RE = re.compile(
    r"\s+("
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?|\d{4})"
    r"[^|\n]{0,40}?"
    r"(?:–|-|to)"
    r"\s*"
    r"(?:Present|Current|"
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?|\d{4})"
    r"(?:\s+\d{4})?"
    r")\s*$",
    re.IGNORECASE,
)


def _split_nonempty_lines(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _split_blocks(raw: str | None) -> list[list[str]]:
    if not raw:
        return []
    blocks: list[list[str]] = []
    for block in re.split(r"\n\s*\n", raw):
        lines = _split_nonempty_lines(block)
        if lines:
            blocks.append(lines)
    return blocks


def _split_skill_rows(raw: str | None) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for line in _split_nonempty_lines(raw):
        if ":" in line:
            category, _, value = line.partition(":")
            rows.append({"category": category.strip(), "value": value.strip()})
        else:
            rows.append({"category": None, "value": line})
    return rows


def _split_label_date(line: str) -> tuple[str, str | None]:
    if "|" in line:
        label, _, date = line.partition("|")
        return label.strip(), date.strip() or None
    match = _DATE_RANGE_TAIL_RE.search(line)
    if match:
        return line[: match.start()].strip(), match.group(1).strip()
    return line.strip(), None


def _is_bullet(line: str) -> bool:
    return line.lstrip().startswith("•")


def _strip_bullet(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("•"):
        return stripped[1:].strip()
    return stripped


def _split_timeline_entries(raw: str | None) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for block in _split_blocks(raw):
        headings = [line for line in block if not _is_bullet(line)]
        bullets = [_strip_bullet(line) for line in block if _is_bullet(line)]
        organization: str | None = None
        role: str | None = None
        date: str | None = None

        if len(headings) >= 2:
            organization = headings[0]
            role, date = _split_label_date(headings[1])
        elif len(headings) == 1:
            role, date = _split_label_date(headings[0])
            if date is None:
                organization = role
                role = None

        entries.append(
            {
                "organization": organization,
                "role": role,
                "date": date,
                "bullets": bullets,
            }
        )
    return entries


def _render_page_warnings(
    page_count: int,
    max_pages: int,
    candidate_experience_years: float | None,
) -> list[dict]:
    if (
        candidate_experience_years is not None
        and candidate_experience_years < 5
        and max_pages > 0
        and page_count > max_pages
    ):
        return [
            {
                "code": "under_five_years_over_one_page",
                "message": (
                    f"Resume rendered to {page_count} pages; candidates with under 5 years "
                    f"of experience should stay within {max_pages} page."
                ),
                "page_count": page_count,
                "max_pages": max_pages,
                "candidate_experience_years": round(candidate_experience_years, 2),
            }
        ]
    return []


def _render_html(tailored: dict) -> str:
    template = _JINJA.get_template(_TEMPLATE)
    contact_items = []
    for kind in ("location", "email", "phone", "linkedin", "website"):
        value = tailored.get(kind)
        if value is not None and str(value).strip():
            contact_items.append({"value": str(value).strip(), "kind": kind})
    return template.render(
        name=(tailored.get("name") or "YOUR NAME"),
        title=(tailored.get("title") or ""),
        summary=(tailored.get("summary") or ""),
        contact_items=contact_items,
        skills_rows=_split_skill_rows(tailored.get("skills_raw")),
        experience_entries=_split_timeline_entries(tailored.get("experience_raw")),
        project_entries=_split_timeline_entries(tailored.get("projects_raw")),
        volunteer_entries=_split_timeline_entries(tailored.get("volunteer_raw")),
        education_lines=_split_nonempty_lines(tailored.get("education_raw")),
        font_b64=FONT_B64,
    )


async def _render_async(tailored: dict, output_path: str) -> None:
    html = _render_html(tailored)
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            page = await browser.new_page()
            await page.set_viewport_size(
                {"width": _PRINTABLE_WIDTH_PX, "height": round(_LETTER_HEIGHT_IN * _CSS_DPI)}
            )
            await page.set_content(html, wait_until="load")
            if tailored.get("max_pages", 1) == 1:
                scroll_height = await page.evaluate(
                    "() => Math.max("
                    "document.body.scrollHeight, "
                    "document.documentElement.scrollHeight)"
                )
                fit_zoom = max(0.68, min(1.0, _PRINTABLE_HEIGHT_PX / max(scroll_height, 1)))
                if fit_zoom < 0.999:
                    await page.evaluate(
                        "(zoom) => { document.body.style.zoom = String(zoom); }",
                        fit_zoom,
                    )
            await page.pdf(
                path=output_path,
                print_background=True,
                prefer_css_page_size=True,
                format="Letter",
            )
        finally:
            await browser.close()


def render_resume(tailored: dict, output_path: str) -> dict:
    """Compile a TailoredResume dict to PDF via HTML + Playwright."""
    out = Path(output_path)
    if not out.parent.exists():
        return {"success": False, "error": f"output directory does not exist: {out.parent}"}
    try:
        asyncio.run(_render_async(tailored, output_path))
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("rendered PDF is missing or empty")
        page_count = len(PdfReader(str(out)).pages)
        max_pages = int(tailored.get("max_pages") or 0)
        warnings = _render_page_warnings(
            page_count=page_count,
            max_pages=max_pages,
            candidate_experience_years=tailored.get("candidate_experience_years"),
        )
        return {
            "success": True,
            "pdf_path": output_path,
            "page_count": page_count,
            "warnings": warnings,
        }
    except Exception as exc:
        if out.exists():
            out.unlink()
        return {"success": False, "error": str(exc)}
