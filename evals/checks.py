"""The one result shape every eval check returns."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""
    skipped: bool = False


def first_failure(checks: list[Check]) -> str | None:
    """`name: detail` of the first failed check, or None when all passed."""
    for check in checks:
        if not check.passed:
            return f"{check.name}: {check.detail}" if check.detail else check.name
    return None
