"""Pure ledger identity logic: URL normalization, job keys, salary and timestamp cleanup. No I/O."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from callback.config import paths

_log = logging.getLogger(__name__)

_DEFAULT_PORTS = {"http": ":80", "https": ":443"}
# Query parameters that only say where a click came from, compared lowercase. Everything else in
# the query string is kept, because boards name the posting in many different parameters
# (Taleo `job`, SuccessFactors `career_job_req_id`, LinkedIn `currentJobId`, ...).
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset(
    {
        "gh_src",
        "refid",
        "ref_id",
        "trk",
        "trackingid",
        "tracking_id",
        "lever-source",
        "lever-origin",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "vjs",
        "tk",
        "_ga",
        "igshid",
        "si",
        "refererurl",
        "referrer",
        "cmp",
        "campaign",
        "medium",
        "sharedid",
    }
)
_JD_HASH_CHARS = 8
_NAME_SEPARATOR = "\x1f"
_SALARY_PLACEHOLDERS = frozenset({"", "not listed", "n/a", "unknown", "ambiguous", "-", "tbd"})
_PLAIN_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def normalize_url(url: str) -> str:
    """Canonical form of a posting URL: https, lowercase host, no default port, no trailing slash.

    Drops the query parameters that only track the click (`_TRACKING_PARAMS`, any `utm_*`),
    compared case-insensitively, and keeps the rest in sorted order. A board that adds a new
    tracking parameter needs it added there, or its links split into two keys. Fragments are dropped
    unless they hold a recognized route ("#/job/1", "#!/job/1", Gmail "#all/<id>").
    A value that cannot be parsed is logged and kept as typed.

    ponytail: `www.` is kept, so "www.x.com/a" and "x.com/a" get two keys. Strip it here if
    that ever splits one posting in two.
    """
    stripped = url.strip()
    try:
        outer = urlsplit(stripped)
        if outer.scheme.lower() in _DEFAULT_PORTS and outer.netloc:
            candidate = stripped
        elif stripped.startswith("//"):
            candidate = f"https:{stripped}"
        else:
            candidate = f"https://{stripped}"
        parts = urlsplit(candidate)
    except ValueError as exc:
        _log.warning(
            json.dumps({"event": "ledger_url_unparsed", "url": stripped, "error": str(exc)})
        )
        return stripped
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower().removesuffix(_DEFAULT_PORTS.get(scheme, "\0"))
    if scheme == "http":
        scheme = "https"
    query = _normalized_query(parts.query)
    fragment = _normalized_route_fragment(parts.fragment, parts.hostname)
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), query, fragment))


def _normalized_query(query: str) -> str:
    return urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(query, keep_blank_values=True)
            if not _is_tracking(key)
        )
    )


def _normalized_route_fragment(fragment: str, hostname: str | None) -> str:
    """Keep hash routes (`#/x`, `#!/x`) and Gmail message ids; drop descriptive fragments."""
    prefix, body = ("!", fragment[1:]) if fragment.startswith("!/") else ("", fragment)
    route = urlsplit(body)
    if body.startswith("/"):
        path = route.path.rstrip("/")
        return prefix + urlunsplit(("", "", path, _normalized_query(route.query), ""))
    if hostname != "mail.google.com" or not _is_gmail_message_path(route.path):
        return ""
    return urlunsplit(("", "", route.path, _normalized_query(route.query), ""))


def _is_gmail_message_path(path: str) -> bool:
    mailbox, separator, message_id = path.partition("/")
    return mailbox in {"all", "inbox"} and bool(separator and message_id and "/" not in message_id)


def url_or_none(value: str | None) -> str | None:
    """The stripped value if it is an http(s) URL with a host, else None (a thread descriptor)."""
    text = (value or "").strip()
    try:
        parts = urlsplit(text)
        hostname, _port = parts.hostname, parts.port
    except ValueError as exc:
        _log.warning(json.dumps({"event": "ledger_url_unparseable", "error": str(exc)}))
        return None
    if parts.scheme.lower() not in {"http", "https"} or not hostname:
        return None
    return text if not any(character.isspace() for character in hostname) else None


def _is_tracking(param: str) -> bool:
    name = param.lower()
    return name.startswith(_TRACKING_PARAM_PREFIXES) or name in _TRACKING_PARAMS


def clean_url(url: str | None) -> str | None:
    """Normalized URL, or None when there is no URL (missing or blank)."""
    if url is None or not url.strip():
        return None
    return normalize_url(url)


def norm_text(value: str | None) -> str:
    """Casefolded text with runs of whitespace collapsed, so case and spacing never split keys."""
    return " ".join((value or "").casefold().split())


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:_JD_HASH_CHARS]


def optional_text(value: str | None) -> str | None:
    """Strip optional metadata, storing blank values as SQL NULL."""
    text = (value or "").strip()
    return text or None


def job_key(
    url: str | None, company: str | None, title: str | None, jd_text: str | None = None
) -> str:
    """URL postings key on the normalized URL; pasted job descriptions have none, so use
    company + title, folded for case and spacing.

    The key ends in a short hash of the folded pair joined by a separator that cannot be
    typed in a name, so ("Meta Platforms", "Engineer") and ("Meta", "Platforms Engineer")
    stay apart. When company or title is missing and the JD text is known, a short hash of
    the text is used instead, so unlabeled pasted jobs do not all merge into one row.

    ponytail: two different pasted postings with the same company and title share one job.
    """
    cleaned = clean_url(url)
    company = optional_text(company)
    title = optional_text(title)
    if cleaned:
        return cleaned
    folded_company, folded_title = norm_text(company), norm_text(title)
    slug = paths.slug(folded_company, folded_title)
    if (folded_company and folded_title) or not jd_text:
        pair = f"{folded_company}{_NAME_SEPARATOR}{folded_title}"
        return f"pasted:{slug}-{_short_hash(pair)}"
    digest = _short_hash(jd_text)
    _log.info(json.dumps({"event": "ledger_key_from_jd_text", "slug": slug, "hash": digest}))
    return f"pasted:{slug}-{digest}"


def canonical_timestamp(value: str) -> str:
    """UTC ISO form of a timestamp, so text and time order agree.

    A time with no offset is read as UTC. Plain `YYYY-MM-DD` dates and blanks come back stripped;
    text that is not ISO, or that overflows when converted to UTC, comes back as given and logs
    a warning.
    """
    stripped = value.strip()
    try:
        if not stripped or (_PLAIN_DATE.fullmatch(stripped) and date.fromisoformat(stripped)):
            return stripped
        parsed = datetime.fromisoformat(stripped)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    except (ValueError, OverflowError):
        _log.warning(json.dumps({"event": "ledger_timestamp_unparsed", "value": value}))
        return value


def clean_salary(value: str | None) -> str | None:
    """The salary text, or None when it is blank or a placeholder such as `Not listed`."""
    folded = norm_text(value)
    return None if folded in _SALARY_PLACEHOLDERS else (value or "").strip()
