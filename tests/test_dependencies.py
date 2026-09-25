import re
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"
# M2.5 added pyyaml for OKF frontmatter; declared rather than imported transitively.
_MAX_RUNTIME_DEPENDENCIES = 12
_REMOVED = {"crawl4ai", "dataclass-wizard", "httpx", "rapidfuzz", "pypdf", "rich", "langchain-core"}


def _runtime_dependency_names() -> list[str]:
    deps = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    return [re.split(r"[<>=!~\[ ]", dep, maxsplit=1)[0].lower() for dep in deps]


def test_runtime_dependencies_stay_within_the_m4_ceiling():
    names = _runtime_dependency_names()
    actual = {
        "count_ok": len(names) <= _MAX_RUNTIME_DEPENDENCIES,
        "removed_present": sorted(_REMOVED & set(names)),
    }
    expected = {"count_ok": True, "removed_present": []}
    assert actual == expected
