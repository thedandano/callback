"""The apply front door, exercised against a real graph on the per-test temp DB."""

from types import SimpleNamespace

import pytest

from callback.graphs.apply import api
from callback.graphs.apply.api import ApplySession
from callback.models.state import ApplyState

VALID_JD_DATA = {
    "title": "Backend Engineer",
    "company": "ExampleCo",
    "required": ["Python"],
    "preferred": [],
    "location": None,
    "seniority": "mid",
    "required_years": 0.0,
    "team": None,
    "key_responsibilities": [],
    "pay_range_min": None,
    "pay_range_max": None,
}


@pytest.fixture
def tmp_resume(tmp_path, monkeypatch):
    from callback.repositories.resumes import save_resume

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("John Doe\nSoftware Engineer\n10 years experience")
    save_resume("resume", str(resume_file))


def _start(session_id: str) -> None:
    state = ApplyState(session_id=session_id, jd_raw_text="Need Python", resume_label="resume")
    api.start(state, resume_label="resume")


def test_read_unknown_session_is_empty():
    assert api.read("nope", tool_name="submit_keywords") == ApplySession({}, None, None)


def test_start_leaves_session_waiting_for_keywords(tmp_resume):
    _start("s1")

    actual = api.read("s1", tool_name="submit_keywords")

    assert actual == ApplySession(actual.values, "keywords", None)
    assert actual.values["jd_text"] == "Need Python"


def test_accept_keywords_then_resume_waits_for_tailor(tmp_resume):
    _start("s2")
    api.accept_keywords("s2", VALID_JD_DATA)

    state = api.resume("s2", tool_name="submit_keywords")
    actual = api.read("s2", tool_name="submit_tailor")

    assert (state["keywords"], actual.waiting_for, actual.halted_at) == (
        VALID_JD_DATA,
        "tailor",
        None,
    )


def test_add_responsibilities_keeps_tailor_pending(tmp_resume):
    _start("s3")
    api.accept_keywords("s3", VALID_JD_DATA)
    api.resume("s3", tool_name="submit_keywords")
    keywords = {**VALID_JD_DATA, "key_responsibilities": ["Build APIs"]}

    api.add_responsibilities("s3", keywords)
    actual = api.read("s3", tool_name="submit_responsibilities")

    assert (actual.values["keywords"], actual.waiting_for) == (keywords, "tailor")


class _FakeGraph:
    def __init__(self, values: dict) -> None:
        self._values = values
        self.updates: list[dict] = []

    def get_state(self, config):
        return SimpleNamespace(values=self._values)

    def update_state(self, config, update, as_node):
        self.updates.append(update)


def test_queue_tailor_clears_every_stale_key_the_caller_did_not_supply(monkeypatch):
    graph = _FakeGraph({"error": "render: boom"})
    monkeypatch.setattr(api, "get_apply_graph", lambda: graph)

    api.queue_tailor("s4", {"no_coverage": True, "error": None})

    expected = {
        **dict.fromkeys(api._STALE_RETRY_KEYS),
        "no_coverage": True,
        "error": None,
    }
    assert graph.updates == [expected]


def test_queue_tailor_first_attempt_writes_only_caller_values(monkeypatch):
    graph = _FakeGraph({})
    monkeypatch.setattr(api, "get_apply_graph", lambda: graph)

    api.queue_tailor("s5", {"no_coverage": True})

    assert graph.updates == [{"no_coverage": True}]
