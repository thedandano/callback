import pytest

import callback.wiki as wiki_module
from callback.wiki import WikiStore, company_slug


def store(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path)
    return WikiStore()


def test_write_read_index_round_trip(tmp_path, monkeypatch):
    s = store(tmp_path, monkeypatch)
    content = "# Index\n\n- [Acme](experience/acme.md)"
    s.write_index("my-resume", content)
    assert s.read_index("my-resume") == content


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
