"""Pre-commit check discouraging piecemeal assertions in Python tests."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


MIN_PIECEMEAL_ASSERTS = 2


def main(argv: list[str]) -> int:
    staged_only = "--staged" in argv
    paths = [arg for arg in argv if arg != "--staged"]
    failures: list[str] = []
    for arg in paths:
        path = Path(arg)
        if not _should_check(path):
            continue
        failures.extend(_check_file(path, staged_only=staged_only))

    if failures:
        print("Use explicit expected objects instead of piecemeal field assertions.")
        print("Prefer: expected = {...}; assert actual == expected")
        print()
        print("\n".join(failures))
        return 1

    return 0


def _should_check(path: Path) -> bool:
    return path.suffix == ".py" and path.name.startswith("test_") and path.exists()


def _check_file(path: Path, *, staged_only: bool) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    changed_lines = _staged_lines(path) if staged_only else None
    if staged_only and not changed_lines:
        return []

    failures: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue

        piecemeal_asserts = [
            assertion
            for assertion in ast.walk(node)
            if isinstance(assertion, ast.Assert)
            and _is_checked_line(assertion.lineno, changed_lines)
            and _is_piecemeal_assert(assertion)
        ]
        if len(piecemeal_asserts) < MIN_PIECEMEAL_ASSERTS:
            continue

        lines = ", ".join(str(assertion.lineno) for assertion in piecemeal_asserts)
        failures.append(f"{path}:{node.lineno} {node.name} has piecemeal assertions on lines {lines}")

    return failures


def _is_checked_line(lineno: int, changed_lines: set[int] | None) -> bool:
    return changed_lines is None or lineno in changed_lines


def _staged_lines(path: Path) -> set[int]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--unified=0", "--", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    changed: set[int] = set()
    for line in result.stdout.splitlines():
        if not line.startswith("@@"):
            continue
        changed.update(_parse_added_range(line))
    return changed


def _parse_added_range(hunk_header: str) -> set[int]:
    added = hunk_header.split(" +", maxsplit=1)[1].split(" ", maxsplit=1)[0]
    start_text, _, count_text = added.partition(",")
    start = int(start_text)
    count = int(count_text or "1")
    return set(range(start, start + count))


def _is_piecemeal_assert(assertion: ast.Assert) -> bool:
    expression = assertion.test
    if isinstance(expression, ast.Compare):
        return _contains_field_access(expression.left)
    return _contains_field_access(expression)


def _contains_field_access(expression: ast.AST) -> bool:
    if isinstance(expression, ast.Call):
        return _is_get_call(expression) or any(_contains_field_access(arg) for arg in expression.args)
    if isinstance(expression, ast.Subscript):
        return isinstance(_root_name(expression.value), str)
    if isinstance(expression, ast.Attribute):
        return isinstance(_root_name(expression), str)
    return any(_contains_field_access(child) for child in ast.iter_child_nodes(expression))


def _is_get_call(expression: ast.Call) -> bool:
    return isinstance(expression.func, ast.Attribute) and expression.func.attr == "get"


def _root_name(expression: ast.AST) -> str | None:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return _root_name(expression.value)
    if isinstance(expression, ast.Subscript):
        return _root_name(expression.value)
    return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
