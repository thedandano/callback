"""Years of experience from resume entries, with overlapping jobs counted once."""

import json
import logging
import re
from datetime import UTC, datetime

from callback.config.observability import record_decision

# Same logger name the function logged under before the split, so log routing is unchanged.
logger = logging.getLogger("callback.apply_nodes")


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _parse_resume_month(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"present", "current"}:
        now = datetime.now(UTC)
        return now.year, now.month
    if match := re.fullmatch(r"(\d{4})-(\d{1,2})", normalized):
        return int(match.group(1)), int(match.group(2))
    if match := re.fullmatch(r"([a-z]+)\s+(\d{4})", normalized):
        month = _MONTHS.get(match.group(1))
        if month:
            return int(match.group(2)), month
    if match := re.fullmatch(r"(\d{4})", normalized):
        return int(match.group(1)), 1
    return None


def _merge_interval_months(intervals: list[tuple[int, int]]) -> int:
    """Total months spanned by the union of inclusive [start, end] month indices."""
    intervals.sort()
    months = 0
    cur_start, cur_end = intervals[0]
    for start_index, end_index in intervals[1:]:
        if start_index <= cur_end:
            cur_end = max(cur_end, end_index)
        else:
            months += cur_end - cur_start + 1
            cur_start, cur_end = start_index, end_index
    months += cur_end - cur_start + 1
    return months


def candidate_experience_years(experience) -> float | None:
    intervals: list[tuple[int, int]] = []
    skipped = 0
    for exp in experience:
        start = _parse_resume_month(exp.start_date)
        end = _parse_resume_month(exp.end_date)
        if not start or not end:
            skipped += 1
            continue
        start_index = start[0] * 12 + start[1]
        end_index = end[0] * 12 + end[1]
        if end_index >= start_index:
            intervals.append((start_index, end_index))
    if skipped:
        logger.warning(
            json.dumps(
                {
                    "event": "experience_years_entries_skipped",
                    "skipped": skipped,
                    "parsed": len(intervals),
                }
            )
        )
    if not intervals:
        record_decision("experience_years", "unavailable")
        return None
    # An entry can also be dropped without counting as skipped (end date before start).
    usable_all = len(intervals) == len(experience)
    record_decision("experience_years", "computed" if usable_all else "partial")
    return round(_merge_interval_months(intervals) / 12, 2)
