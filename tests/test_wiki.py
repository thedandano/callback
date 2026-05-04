import pytest
import pi_apply.wiki as wiki_module
from pi_apply.wiki import WikiStore, company_slug


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki_module, "BASE_DIR", tmp_path)
    return WikiStore()


def test_write_read_index_round_trip(store):
    content = "# Index\n\n- [Acme](experience/acme.md)"
    store.write_index("my-resume", content)
    assert store.read_index("my-resume") == content


def test_write_read_experience_page(store):
    store.write_experience_page("my-resume", "acme-corp", "# Acme Corp\n\nSBI story here")
    pages = store.read_pages("my-resume", ["experience/acme-corp.md"])
    assert pages["experience/acme-corp.md"] == "# Acme Corp\n\nSBI story here"


def test_missing_page_returns_empty_string(store):
    pages = store.read_pages("my-resume", ["nonexistent.md"])
    assert pages["nonexistent.md"] == ""


def test_wildcard_returns_all_pages(store):
    store.write_index("my-resume", "index content")
    store.write_experience_page("my-resume", "acme", "acme content")
    store.write_page("my-resume", "summary.md", "summary content")
    pages = store.read_pages("my-resume", ["*"])
    assert len(pages) == 3
    assert "index.md" in pages
    assert "experience/acme.md" in pages
    assert "summary.md" in pages


def test_company_slug_basic():
    assert company_slug("Acme Corp.") == "acme-corp"


def test_company_slug_special_chars():
    assert company_slug("AT&T") == "at-t"


def test_company_slug_leading_trailing():
    assert company_slug("  Foo  Bar  ") == "foo-bar"


def test_company_slug_numbers():
    assert company_slug("123 Inc") == "123-inc"
