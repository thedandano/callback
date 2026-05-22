"""Tests for wired render and parse_final nodes."""

import asyncio
import base64
import re
from pathlib import Path

import pi_apply.render.html_builder as render_builder
from pi_apply import extractor as resume_extractor
from pi_apply.apply_nodes import parse_final, render
from pi_apply.render.html_builder import (
    _render_async,
    _render_html,
    _render_page_warnings,
    _split_blocks,
    _split_label_date,
    _split_timeline_entries,
    _strip_bullet,
    render_resume,
)
from pi_apply.scorer import ScoringConfig, _score_ats
from pi_apply.state import ApplyState, TailoredResume


def test_render_produces_real_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(
        session_id="s1",
        keywords={"company": "Acme Corp"},
        tailored=TailoredResume(name="Jane Doe", summary="Python engineer"),
    )
    result = render(state)
    expected_path = str(tmp_path / "Jane_Doe_Acme_Corp_Resume.pdf")
    assert result == {"pdf_path": expected_path, "render_page_count": 1, "render_warnings": []}
    with open(expected_path, "rb") as f:
        assert f.read(4) == b"%PDF"


def test_render_keyword_round_trip(tmp_path, monkeypatch):
    """skills_raw keyword survives render → extract round-trip."""
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(
        session_id="s2",
        keywords={"company": "Kafka Systems"},
        tailored=TailoredResume(name="Jane Doe", skills_raw="Tools: Apache Kafka"),
    )
    render_result = render(state)
    assert render_result == {
        "pdf_path": str(tmp_path / "Jane_Doe_Kafka_Systems_Resume.pdf"),
        "render_page_count": 1,
        "render_warnings": [],
    }

    pdf_path = render_result["pdf_path"]
    parse_state = ApplyState(session_id="s2", pdf_path=pdf_path)
    parse_result = parse_final(parse_state)
    expected_text = resume_extractor.extract(pdf_path)
    assert parse_result == {"parsed_final": expected_text}
    assert "Apache Kafka" in parse_result["parsed_final"]


def test_render_halts_when_tailored_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_APPLY_APPS_DIR", str(tmp_path))
    state = ApplyState(session_id="s3")
    result = render(state)
    assert result == {"error": "render: state.tailored is None — tailor node must run first"}


def test_split_label_date_without_date_returns_label_and_none():
    assert _split_label_date("Solo Heading") == ("Solo Heading", None)


def test_strip_bullet_without_bullet_returns_stripped_text():
    assert _strip_bullet("  Built pricing systems") == "Built pricing systems"


def test_split_blocks_ignores_empty_blocks():
    assert _split_blocks("\n\nSkills\n\n   \n\nExperience") == [["Skills"], ["Experience"]]


def test_split_timeline_entries_single_heading_without_date_is_organization():
    assert _split_timeline_entries("Amazon, Anytown, USA\n• Built pricing systems") == [
        {
            "organization": "Amazon, Anytown, USA",
            "role": None,
            "date": None,
            "bullets": ["Built pricing systems"],
        }
    ]


def test_split_timeline_entries_single_heading_with_date_is_role_row():
    entry = _split_timeline_entries("Engineer September 2020 – Present\n• Built pricing systems")
    assert entry == [
        {
            "organization": None,
            "role": "Engineer",
            "date": "September 2020 – Present",
            "bullets": ["Built pricing systems"],
        }
    ]


def test_render_resume_inter_font_produces_valid_pdf(tmp_path):
    """render_resume() with bundled Inter font produces a valid PDF."""
    output_path = str(tmp_path / "inter_test.pdf")
    result = render_resume({"name": "Inter Test"}, output_path)
    assert result == {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}
    with open(output_path, "rb") as f:
        assert f.read(4) == b"%PDF"


def test_render_resume_returns_error_on_missing_output_parent(tmp_path):
    output_path = str(tmp_path / "missing" / "resume.pdf")

    assert render_resume({"name": "Jane Doe"}, output_path) == {
        "success": False,
        "error": f"output directory does not exist: {tmp_path / 'missing'}",
    }


def test_render_resume_removes_empty_pdf_on_failure(tmp_path, monkeypatch):
    output_path = tmp_path / "empty.pdf"

    async def write_empty_pdf(_tailored: dict, output_path: str) -> None:
        Path(output_path).write_bytes(b"")

    monkeypatch.setattr(render_builder, "_render_async", write_empty_pdf)

    result = render_resume({"name": "Jane Doe"}, str(output_path))

    assert result == {"success": False, "error": "rendered PDF is missing or empty"}
    assert not output_path.exists()


def test_render_resume_returns_error_when_render_fails_before_file_exists(tmp_path, monkeypatch):
    output_path = tmp_path / "missing.pdf"

    async def fail_before_writing(_tailored: dict, _output_path: str) -> None:
        raise RuntimeError("browser failed")

    monkeypatch.setattr(render_builder, "_render_async", fail_before_writing)

    result = render_resume({"name": "Jane Doe"}, str(output_path))

    assert result == {"success": False, "error": "browser failed"}
    assert not output_path.exists()


class _FakePage:
    def __init__(self, scroll_height: int = 100):
        self.scroll_height = scroll_height
        self.evaluate_calls: list[tuple[str, tuple]] = []
        self.pdf_kwargs: dict | None = None
        self.viewport: dict | None = None

    async def set_viewport_size(self, viewport: dict) -> None:
        self.viewport = viewport

    async def set_content(self, _html: str, wait_until: str) -> None:
        assert wait_until == "load"

    async def evaluate(self, script: str, *args) -> int | None:
        self.evaluate_calls.append((script, args))
        if args:
            return None
        return self.scroll_height

    async def pdf(self, **kwargs) -> None:
        self.pdf_kwargs = kwargs


class _FakeBrowser:
    def __init__(self, page: _FakePage):
        self.page = page

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def new_page(self) -> _FakePage:
        return self.page


class _FakeChromium:
    def __init__(self, page: _FakePage):
        self.page = page

    async def launch(self, args: list[str]) -> _FakeBrowser:
        assert args == ["--no-sandbox"]
        return _FakeBrowser(self.page)


class _FakePlaywright:
    def __init__(self, page: _FakePage):
        self.chromium = _FakeChromium(page)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def test_render_async_skips_fit_logic_when_max_pages_is_not_one(tmp_path, monkeypatch):
    page = _FakePage()
    monkeypatch.setattr(render_builder, "async_playwright", lambda: _FakePlaywright(page))

    asyncio.run(_render_async({"name": "Jane Doe", "max_pages": 2}, str(tmp_path / "resume.pdf")))

    assert {
        "evaluate_calls": page.evaluate_calls,
        "has_pdf_kwargs": page.pdf_kwargs is not None,
    } == {"evaluate_calls": [], "has_pdf_kwargs": True}


def test_render_async_skips_zoom_when_content_already_fits(tmp_path, monkeypatch):
    page = _FakePage(scroll_height=100)
    monkeypatch.setattr(render_builder, "async_playwright", lambda: _FakePlaywright(page))

    asyncio.run(_render_async({"name": "Jane Doe", "max_pages": 1}, str(tmp_path / "resume.pdf")))

    evaluate_scripts = [script for script, _args in page.evaluate_calls]
    assert {
        "measured_page_height": evaluate_scripts[0].startswith("() => Math.max("),
        "applied_zoom": any("document.body.style.zoom" in script for script in evaluate_scripts),
        "applied_vertical_centering": any("translateY" in script for script in evaluate_scripts),
        "centering_height": page.evaluate_calls[-1][1],
        "has_pdf_kwargs": page.pdf_kwargs is not None,
    } == {
        "measured_page_height": True,
        "applied_zoom": False,
        "applied_vertical_centering": True,
        "centering_height": (render_builder._PRINTABLE_HEIGHT_PX,),
        "has_pdf_kwargs": True,
    }


def test_parse_final_halts_on_missing_pdf_path():
    state = ApplyState(session_id="s4", pdf_path=None)
    result = parse_final(state)
    assert result == {"error": "parse_final: no pdf_path in state"}


def test_parse_final_halts_on_missing_file(tmp_path):
    path = str(tmp_path / "nonexistent.pdf")
    state = ApplyState(session_id="s5", pdf_path=path)
    assert parse_final(state) == {"error": f"parse_final: pdf file not found: {path}"}


def test_render_html_contains_font_face_embed():
    html = _render_html(
        {
            "name": "Jane Doe",
            "skills_raw": "Python",
            "experience_raw": "• Built classifier",
            "education_raw": "State University",
        }
    )
    assert "@font-face" in html
    assert 'src: url("data:font/' in html

    payload_m = re.search(r'data:font/ttf;base64,([^"]+)"', html)
    assert payload_m is not None
    payload_len = len(payload_m.group(1))
    font_bytes = (
        Path(__file__).parent.parent / "pi_apply" / "render" / "fonts" / "InterVariable.ttf"
    ).read_bytes()
    expected_len = len(base64.b64encode(font_bytes).decode())
    assert payload_len == expected_len


def test_render_html_bolds_skill_categories_and_uses_target_header():
    html = _render_html(
        {
            "name": "Jane Doe",
            "skills_raw": "Languages: Python, Java\nCloud & Infrastructure: AWS, Docker",
        }
    )
    assert "SKILLS &amp; ABILITIES" in html
    assert '<span class="skill-label">Languages:</span> Python, Java' in html
    assert '<span class="skill-label">Cloud & Infrastructure:</span> AWS, Docker' in html


def test_render_html_structures_title_contact_and_timeline_rows():
    html = _render_html(
        {
            "name": "Jane Doe",
            "location": "Anytown, USA",
            "email": "jane.doe@example.com",
            "linkedin": "www.linkedin.com/in/janedoe",
            "title": "SOFTWARE ENGINEER – BACKEND & AI",
            "experience_raw": (
                "Amazon, Anytown, USA\n"
                "Software Development Engineer II | December 2024 – January 2026\n"
                "• Built pricing systems"
            ),
            "projects_raw": (
                "Howe-2 Care 4 Critters – 501(c)(3) Cat Rescue, Escondido, CA\n"
                "Full-Stack Web & Accessibility Engineer (Volunteer) September 2020 – Present\n"
                "• Built rescue website"
            ),
        }
    )

    assert "Anytown, USA" in html
    assert '<span class="contact-link">www.linkedin.com/in/janedoe</span>' in html
    assert '<div class="section-header">SOFTWARE ENGINEER – BACKEND & AI</div>' in html
    assert '<div class="entry-organization">Amazon, Anytown, USA</div>' in html
    assert '<span class="entry-role">Software Development Engineer II</span>' in html
    assert '<span class="entry-date">December 2024 – January 2026</span>' in html
    assert '<span class="entry-date">September 2020 – Present</span>' in html


def test_render_html_keeps_summary_divider_when_title_is_absent():
    html = _render_html(
        {
            "name": "Jane Doe",
            "location": "Anytown, USA",
            "summary": "Backend and data engineer.",
        }
    )

    assert '<div class="summary-divider" aria-hidden="true"></div>' in html
    divider_index = html.rindex('<div class="summary-divider" aria-hidden="true"></div>')
    assert html.index("Anytown, USA") < divider_index
    assert divider_index < html.index("Backend and data engineer.")


def test_render_async_vertical_centering_targets_resume_container():
    assert 'document.querySelector(".container")' in render_builder._VERTICAL_CENTER_SCRIPT
    assert "container.getBoundingClientRect().height" in render_builder._VERTICAL_CENTER_SCRIPT
    assert "translateY" in render_builder._VERTICAL_CENTER_SCRIPT


def test_render_html_uses_consistent_body_font_for_contact_summary_and_skills():
    html = _render_html(
        {
            "name": "Jane Doe",
            "location": "Anytown, USA",
            "summary": "Backend engineer.",
            "skills_raw": "Languages: Python",
        }
    )

    assert 'font-family: "Inter", sans-serif;' in html
    assert ".contact {\n      text-align: center;\n      margin-top:" in html
    assert ".contact {\n      text-align: center;\n      font-size:" not in html
    assert ".summary {\n      white-space: normal;" in html
    assert ".line {\n      white-space: normal;" in html


def test_render_html_uses_compact_internal_line_height_and_room_between_groups():
    html = _render_html({"name": "Jane Doe", "summary": "Backend engineer."})

    assert "line-height: 1.15;" in html
    assert ".summary {\n      white-space: normal;\n      margin: 0.35em 0 0.5em;" in html
    assert ".section {\n      margin-top: 0.55em;" in html
    assert ".section-header {\n      font-weight: 800;" in html
    assert "margin-bottom: 0.35em;" in html
    assert ".bullet {\n      display: grid;" in html
    assert "margin: 0 0 0.35em 8px;" in html


def test_render_html_uses_two_column_bullets_for_wrapped_line_alignment():
    html = _render_html(
        {
            "name": "Jane Doe",
            "experience_raw": "Amazon\nEngineer | 2024 – Present\n• Built pricing systems",
        }
    )

    assert ".bullet {\n      display: grid;" in html
    assert "grid-template-columns: 0.7em 1fr;" in html
    assert (
        '<span class="bullet-marker">•</span><span class="bullet-text">Built pricing systems</span>'
    ) in html


def test_render_resume_ats_headers_round_trip(tmp_path):
    output_path = str(tmp_path / "ats_roundtrip.pdf")
    tailored = TailoredResume(
        name="Jane Doe",
        skills_raw="Python\nFastAPI",
        experience_raw=(
            "Senior Engineer\n"
            "Acme Corp | 2020 – Present\n"
            "• Built a classifier\n"
            "• Shipped ATS-safe formatting"
        ),
        education_raw="State University\nB.S. Computer Science",
    )
    result = render_resume(tailored.model_dump(), output_path)
    assert result == {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    text = resume_extractor.extract(output_path)
    ats_score, diagnostics = _score_ats(text, ScoringConfig())
    assert ats_score == 10.0
    assert all(d.matched for d in diagnostics)


def test_render_resume_bullet_round_trip(tmp_path):
    output_path = str(tmp_path / "bullet_roundtrip.pdf")
    tailored = TailoredResume(
        name="Jane Doe",
        experience_raw="• Built a classifier",
    )
    result = render_resume(tailored.model_dump(), output_path)
    assert result == {"success": True, "pdf_path": output_path, "page_count": 1, "warnings": []}

    text = resume_extractor.extract(output_path)
    assert "• Built a classifier" in text
    assert "? Built a classifier" not in text


def test_render_page_warnings_flags_under_five_years_over_one_page():
    assert _render_page_warnings(page_count=2, max_pages=1, candidate_experience_years=3.8) == [
        {
            "code": "under_five_years_over_one_page",
            "message": (
                "Resume rendered to 2 pages; candidates with under 5 years of "
                "experience should stay within 1 page."
            ),
            "page_count": 2,
            "max_pages": 1,
            "candidate_experience_years": 3.8,
        }
    ]


def test_render_page_warnings_allows_five_plus_years_over_one_page():
    assert _render_page_warnings(page_count=2, max_pages=1, candidate_experience_years=5.0) == []
