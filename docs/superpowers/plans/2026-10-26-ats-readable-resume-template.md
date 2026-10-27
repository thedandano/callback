# ATS-Readable Resume Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the HTML resume template so printed sections use plain ATS-friendly headings in the order Summary → Experience → Projects → Education → Skills (#145, agreed scope).

**Architecture:** Display-only change in `resume_template.html.j2`. Section data still arrives via semantic keys (`skills_rows`, `experience_entries`, etc.) from `html_builder.py`; only the hardcoded header strings and block order change. No SectionMap, tailor, scorer, or sort helper in this pass.

**Tech Stack:** Jinja2 HTML template, Playwright PDF render (unchanged), pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-ats-readable-resume-template-design.md`  
**Issue:** https://github.com/thedandano/callback/issues/145

## Global Constraints

- Keep existing all-caps section-header style (`EXPERIENCE`, not `Experience`).
- Do not add experience date sorting or PDF size warnings.
- Do not change `callback/extractor.py` input heading recognition.
- Touch only the template and render tests needed for the new strings/order.

## File map

| File | Role |
|------|------|
| `callback/render/resume_template.html.j2` | Hardcoded section headers and block order |
| `tests/test_render.py` | Asserts header strings (and will assert order) |
| `callback/render/html_builder.py` | Unchanged — still passes the same template variables |

---

### Task 1: Fail on old skills header; assert new headers and order

**Files:**
- Modify: `tests/test_render.py`
- Modify: `callback/render/resume_template.html.j2` (after red)

**Interfaces:**
- Consumes: `_render_html(tailored: dict) -> str` from `callback.render.html_builder` (already imported in the test module as used by existing tests)
- Produces: tests that require headers `EXPERIENCE`, `PROJECTS`, `EDUCATION`, `SKILLS` and document order Experience → Projects → Education → Skills in the HTML

- [ ] **Step 1: Write the failing test updates**

In `tests/test_render.py`, change `test_render_html_bolds_skill_categories_and_uses_target_header` so it expects the plain skills header:

```python
def test_render_html_bolds_skill_categories_and_uses_target_header():
    html = _render_html(
        {
            "name": "Jane Doe",
            "skills_raw": "Languages: Python, Java\nCloud & Infrastructure: AWS, Docker",
        }
    )
    assert '<div class="section-header">SKILLS</div>' in html
    assert "SKILLS &amp; ABILITIES" not in html
    assert '<span class="skill-label">Languages:</span> Python, Java' in html
    assert '<span class="skill-label">Cloud & Infrastructure:</span> AWS, Docker' in html
```

Add a focused order/header test (new function after the skills-header test):

```python
def test_render_html_uses_plain_headers_in_jeff_order():
    html = _render_html(
        {
            "name": "Jane Doe",
            "summary": "Backend engineer.",
            "skills_raw": "Python, AWS",
            "experience_raw": (
                "Acme\nEngineer | January 2024 – Present\n• Shipped APIs"
            ),
            "projects_raw": (
                "Side Project\nOwner | 2023 – Present\n• Built a tool"
            ),
            "education_raw": "BS Computer Science, State University",
        }
    )

    for header in ("EXPERIENCE", "PROJECTS", "EDUCATION", "SKILLS"):
        assert f'<div class="section-header">{header}</div>' in html

    experience = html.index('<div class="section-header">EXPERIENCE</div>')
    projects = html.index('<div class="section-header">PROJECTS</div>')
    education = html.index('<div class="section-header">EDUCATION</div>')
    skills = html.index('<div class="section-header">SKILLS</div>')

    assert "Backend engineer." in html
    assert html.index("Backend engineer.") < experience
    assert experience < projects < education < skills
    assert "PROFESSIONAL EXPERIENCE" not in html
    assert "SKILLS &amp; ABILITIES" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_render.py::test_render_html_bolds_skill_categories_and_uses_target_header tests/test_render.py::test_render_html_uses_plain_headers_in_jeff_order -v`

Expected: FAIL — old template still emits `SKILLS &amp; ABILITIES` / `PROFESSIONAL EXPERIENCE`, and/or `EXPERIENCE` header missing so `.index` raises / assert fails.

- [ ] **Step 3: Update the template**

In `callback/render/resume_template.html.j2`, keep the title + summary block as-is, then replace the four section blocks so the file order is Experience → Projects → Education → Skills, with plain headers:

```jinja2
    {% if experience_entries %}
    <section class="section">
      <div class="section-header">EXPERIENCE</div>
      {% for entry in experience_entries %}
      <div class="entry">
        {% if entry.organization %}
        <div class="entry-organization">{{ entry.organization }}</div>
        {% endif %}
        {% if entry.role or entry.date %}
        <div class="entry-meta">
          <span class="entry-role">{{ entry.role }}</span>
          {% if entry.date %}<span class="entry-date">{{ entry.date }}</span>{% endif %}
        </div>
        {% endif %}
        {% for bullet in entry.bullets %}
        <div class="bullet"><span class="bullet-marker">•</span><span class="bullet-text">{{ bullet }}</span></div>
        {% endfor %}
      </div>
      {% endfor %}
    </section>
    {% endif %}

    {% if project_entries %}
    <section class="section">
      <div class="section-header">PROJECTS</div>
      {% for entry in project_entries %}
      <div class="entry">
        {% if entry.organization %}
        <div class="entry-organization">{{ entry.organization }}</div>
        {% endif %}
        {% if entry.role or entry.date %}
        <div class="entry-meta">
          <span class="entry-role">{{ entry.role }}</span>
          {% if entry.date %}<span class="entry-date">{{ entry.date }}</span>{% endif %}
        </div>
        {% endif %}
        {% for bullet in entry.bullets %}
        <div class="bullet"><span class="bullet-marker">•</span><span class="bullet-text">{{ bullet }}</span></div>
        {% endfor %}
      </div>
      {% endfor %}
    </section>
    {% endif %}

    {% if education_lines %}
    <section class="section">
      <div class="section-header">EDUCATION</div>
      {% for line in education_lines %}
      <div class="line education-line">{{ line }}</div>
      {% endfor %}
    </section>
    {% endif %}

    {% if skills_rows %}
    <section class="section">
      <div class="section-header">SKILLS</div>
      {% for row in skills_rows %}
      <div class="line">
        {% if row.category %}<span class="skill-label">{{ row.category }}:</span> {% endif %}{{ row.value }}
      </div>
      {% endfor %}
    </section>
    {% endif %}
```

Delete the old skills-first block and the old `PROFESSIONAL EXPERIENCE` / `SKILLS &amp; ABILITIES` strings from the template.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_render.py -v`

Expected: PASS (full render file, including the two updated/new tests).

- [ ] **Step 5: Commit**

```bash
git add callback/render/resume_template.html.j2 tests/test_render.py \
  docs/superpowers/specs/2026-10-26-ats-readable-resume-template-design.md \
  docs/superpowers/plans/2026-10-26-ats-readable-resume-template.md
git commit -m "$(cat <<'EOF'
fix(render): use plain ATS section headers in Jeff order

Reorder the resume template to Summary → Experience → Projects →
Education → Skills and drop ornate heading wording for Rule 1 (#145).
EOF
)"
```

- [ ] **Step 6: Issue hygiene on #145**

Comment on https://github.com/thedandano/callback/issues/145 that the scoped pass shipped (plain headers + Jeff order). Leave the issue open for deferred follow-ups (experience date sort at render; optional PDF >2.5MB warn), or close it and open two small follow-up issues — ask the user which.

---

## Self-review (plan author)

1. **Spec coverage:** Rename + reorder covered in Task 1; deferred sort/PDF size explicitly out of Global Constraints.
2. **Placeholders:** None.
3. **Type consistency:** Uses existing `_render_html` / template variables only.

## Subagent review vs #145

[code-reviewer](fdc9768e-61c9-4a69-8560-081ae802c770): **PASS WITH NOTES**. Agreed scoped slice is covered; ATS patterns still match; leave #145 open (or split follow-ups) for deferred sort/PDF size. Notes above folded into Steps 1 and 6.
