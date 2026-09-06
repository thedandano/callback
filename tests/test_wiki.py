import pytest

from callback.wiki import (
    WikiPageError,
    WikiPageIdError,
    WikiStore,
    company_slug,
    join_frontmatter,
    split_frontmatter,
)


def store(tmp_path, monkeypatch):
    monkeypatch.setattr("callback.paths.wiki_dir", lambda: tmp_path)
    return WikiStore()


def test_write_read_index_round_trip(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    content = "# Index\n\n- [Acme](experience/acme.md)"
    s.write_index("my-resume", content)
    assert s.read_pages("my-resume", ["index.md"]) == {"index.md": content}


def test_write_read_experience_page(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    s.write_experience_page("my-resume", "acme-corp", "# Acme Corp\n\nSBI story here")
    pages = s.read_pages("my-resume", ["experience/acme-corp.md"])
    assert pages["experience/acme-corp.md"] == "# Acme Corp\n\nSBI story here"


def test_missing_page_returns_empty_string(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    pages = s.read_pages("my-resume", ["nonexistent.md"])
    assert pages["nonexistent.md"] == ""


def test_multiple_pages_fetched(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    s.write_experience_page("r", "acme", "acme content")
    s.write_page("r", "summary.md", "summary content")
    expected = {"experience/acme.md": "acme content", "summary.md": "summary content"}
    assert s.read_pages("r", ["experience/acme.md", "summary.md"]) == expected


def test_company_slug_basic():
    assert company_slug("Acme Corp.") == "acme-corp"


def test_company_slug_special_chars():
    assert company_slug("AT&T") == "at-t"


def test_company_slug_leading_trailing():
    assert company_slug("  Foo  Bar  ") == "foo-bar"


def test_company_slug_numbers():
    assert company_slug("123 Inc") == "123-inc"


def test_read_pages_rejects_parent_traversal(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("hunter2", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes wiki root"):
        s.read_pages("r", ["../../outside-secret.txt"])


def test_read_pages_rejects_absolute_path(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("hunter2", encoding="utf-8")
    with pytest.raises(ValueError, match="escapes wiki root"):
        s.read_pages("r", [str(outside)])


def test_write_page_rejects_parent_traversal(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="escapes wiki root"):
        s.write_page("r", "../escaped.md", "x")


def test_read_pages_allows_nested_ids(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    s.write_page("r", "experience/acme.md", "acme")
    assert s.read_pages("r", ["experience/acme.md", "./experience/acme.md"]) == {
        "experience/acme.md": "acme",
        "./experience/acme.md": "acme",
    }


def test_read_pages_returns_empty_for_directory_ids(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    s.write_page("r", "experience/acme.md", "acme")
    assert s.read_pages("r", ["", ".", "experience"]) == {"": "", ".": "", "experience": ""}


def test_is_valid_page_id_rejects_traversal_and_accepts_nested(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    assert s.is_valid_page_id("r", "../x.md") is False
    assert s.is_valid_page_id("r", "/etc/passwd") is False
    assert s.is_valid_page_id("r", "experience/a/b.md") is True


def test_read_pages_rejects_embedded_nul(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    with pytest.raises(WikiPageIdError):
        s.read_pages("r", ["a\x00b.md"])


def test_is_valid_page_id_rejects_embedded_nul(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    assert s.is_valid_page_id("r", "a\x00b.md") is False


def test_split_frontmatter_returns_meta_and_body():
    page = "---\ntype: project\ntags:\n- Python\n- AWS\n---\n# Title\n\n**Situation:** x\n"
    actual = split_frontmatter(page)
    expected = ({"type": "project", "tags": ["Python", "AWS"]}, "# Title\n\n**Situation:** x\n")
    assert actual == expected


def test_split_frontmatter_without_fence_returns_empty_meta_and_whole_content():
    actual = split_frontmatter("# Just markdown\n")
    expected = ({}, "# Just markdown\n")
    assert actual == expected


def test_split_frontmatter_rejects_unterminated_fence():
    with pytest.raises(WikiPageError) as exc_info:
        split_frontmatter("---\ntype: story\n# no closing fence\n")
    assert "closing" in str(exc_info.value)


def test_split_frontmatter_rejects_non_mapping_yaml():
    with pytest.raises(WikiPageError) as exc_info:
        split_frontmatter("---\n- just\n- a list\n---\nbody\n")
    assert "mapping" in str(exc_info.value)


def test_join_then_split_round_trips_and_keeps_key_order():
    meta = {"type": "story", "title": "REST APIs", "tags": ["Node.js", "C++"], "n": 3}
    page = join_frontmatter(meta, "# REST APIs\n\nbody\n")
    actual = {
        "page_starts": page.startswith("---\ntype: story\ntitle: REST APIs\n"),
        "round": split_frontmatter(page),
    }
    expected = {"page_starts": True, "round": (meta, "# REST APIs\n\nbody\n")}
    assert actual == expected
