"""Pin the exact reply shape of the project swap and layout recommendations."""

from callback.services.project_ranking import (
    project_layout_recommendation,
    project_swap_recommendation,
)

KEYWORDS = {"required": ["Kafka"], "preferred": []}
SECTIONS = {
    "projects": [
        {"name": "Blog", "description": "Static site", "bullets": []},
        {"name": "Notes", "description": "Todo app", "bullets": []},
    ]
}
CANDIDATE = {"page_id": "projects/streaming", "score": 5}


def test_swap_recommendation_keys():
    actual = project_swap_recommendation([CANDIDATE], KEYWORDS, SECTIONS)

    expected = {
        "replace_target": "proj-0",
        "visible_project_score": 0,
        "candidate": CANDIDATE,
    }
    assert actual == expected


def test_layout_recommendation_replace_keys():
    actual = project_layout_recommendation([CANDIDATE], KEYWORDS, SECTIONS)

    expected = {
        "strategy": "replace",
        "max_visible_projects": 2,
        "replace_target": "proj-0",
        "visible_project_score": 0,
        "candidate": CANDIDATE,
    }
    assert actual == expected
