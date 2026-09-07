"""Feed each E1/E2 fixture to a host model, save its output, run the checks, print one table.

The runner is the only thing in the repo that calls a model. It shells out to
`claude -p` or `codex exec`, both non-interactive and isolated (no MCP servers,
tools, settings, or CLAUDE.md) from a scratch directory so nothing colors the
answer.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from langsmith.utils import LangSmithError

from callback.jd_data import EXTRACTION_PROTOCOL
from callback.server import _TAILOR_INSTRUCTIONS
from evals import experiments
from evals.cases import case_dirs, case_id
from evals.checks import Check, first_failure
from evals.extract_checks import run_checks as extract_run_checks
from evals.tailor_checks import TailorCase, missing_keywords
from evals.tailor_checks import run_checks as tailor_run_checks

logger = logging.getLogger("callback.evals")

EXTRACT_DIR = Path(__file__).resolve().parent / "extract"
HOSTS = ("claude", "codex")
EVALS = ("extract", "tailor")
CODEX_DEFAULT_MODEL = "gpt-5.6-terra"
HOST_TIMEOUT_S = 900
RunFn = Callable[..., subprocess.CompletedProcess]

EDIT_SCHEMA = (
    "Each edit is an object with:\n"
    "  section: str (summary | skills | experience | projects)\n"
    "  op: str (add | replace | remove)\n"
    "  target: str (required for experience/projects; exp-N-bM replaces or removes bullet M\n"
    "    of experience entry N, exp-N-context sets the context line, proj-N replaces a whole\n"
    "    project, proj-end appends one project, proj-N-desc / proj-N-bM edit a project's\n"
    "    description or bullet)\n"
    "  value: str | dict (required for add/replace; a project add/replacement is a\n"
    "    {name, description, bullets} object)\n"
    "  category: str (optional, the skills category to add into)\n"
)


class HostError(RuntimeError):
    """The host CLI failed; the message carries the exit code and stderr tail."""


@dataclass(frozen=True)
class EvalRow:
    eval_name: str
    fixture: str
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def status(self) -> str:
        """FAIL if any check failed, else SKIP if any check was skipped (thin-golden guard,
        drifted content, etc.), else PASS."""
        if not self.passed:
            return "FAIL"
        if any(c.skipped for c in self.checks):
            return "SKIP"
        return "PASS"

    @property
    def first_failure(self) -> str | None:
        return first_failure(self.checks)

    @property
    def note(self) -> str | None:
        """The detail of the first passed check that has one, e.g. a thin-golden skip notice."""
        for check in self.checks:
            if check.passed and check.detail:
                return check.detail
        return None


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def extract_json_object(text: str) -> dict | None:
    """The first `{` to the last `}` of a host reply, parsed; None when that is not an object."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("host reply is not JSON: %s", exc)
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_prompt(jd_text: str) -> str:
    return (
        f"{EXTRACTION_PROTOCOL}\n\n"
        "Respond with only the JSON object: no prose, no code fence.\n\n"
        f"<jd_text>\n{jd_text}\n</jd_text>"
    )


def _pages_block(pages: dict[str, str]) -> str:
    return "\n\n".join(f"## {page_id}\n{content.rstrip()}" for page_id, content in pages.items())


def _dump(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def tailor_prompt(case: TailorCase) -> str:
    return (
        "You are the host model in callback's resume tailoring step. Produce the arguments for "
        'submit_tailor as one JSON object: {"edits": [...], "no_coverage": false}. Respond with '
        "only that JSON object: no prose, no code fence.\n\n"
        f"{EDIT_SCHEMA}\n"
        'Set "no_coverage": true with "edits": [] only when no truthful, evidence-backed edit '
        "exists.\n\n"
        f"{_TAILOR_INSTRUCTIONS}\n"
        "- Add a keyword only when it is supported by dated experience or clear project evidence.\n"
        "- Rewrite bullets only when the mechanism and impact are supported by the resume or the "
        "wiki pages below.\n"
        "- Do not keyword-stuff skills. Prefer fewer strong edits over many weak edits.\n\n"
        f"<sections>\n{_dump(case.sections)}\n</sections>\n\n"
        f"<keywords>\n{_dump(case.keywords)}\n</keywords>\n\n"
        f"<score_gaps>\n{_dump(missing_keywords(case.sections, case.keywords))}\n</score_gaps>\n\n"
        f"<wiki_pages>\n{_pages_block(case.wiki_pages)}\n</wiki_pages>"
    )


def _claude_cmd(model: str | None) -> list[str]:
    # --bare disables keychain auth on this machine, so isolation instead comes from an
    # empty MCP config, no tools, no settings sources, and the scratch cwd below.
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--tools",
        "",
        "--setting-sources",
        "",
    ]
    return cmd + (["--model", model] if model else [])


def _codex_cmd(model: str | None, out_file: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "-m",
        model or CODEX_DEFAULT_MODEL,
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "-o",
        str(out_file),
    ]


def _claude_result(stdout: str) -> str:
    """Parse claude -p's JSON stdout and return the `result` field, or raise HostError."""
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HostError(f"claude returned non-JSON stdout: {stdout[:200]!r}") from exc
    result = parsed.get("result") if isinstance(parsed, dict) else None
    if isinstance(result, str):
        return result
    extra = ""
    if isinstance(parsed, dict):
        flags = {k: parsed[k] for k in ("is_error", "error") if k in parsed}
        if flags:
            extra = f" ({flags})"
    raise HostError(f"claude reply has no result: {stdout[:200]!r}{extra}")


def call_host(host: str, model: str | None, prompt: str, run: RunFn = subprocess.run) -> str:
    """Send one prompt to the host CLI and return its reply text."""
    with tempfile.TemporaryDirectory(prefix="callback-eval-") as scratch:
        out_file = Path(scratch) / "reply.txt"
        cmd = _claude_cmd(model) if host == "claude" else _codex_cmd(model, out_file)
        proc = run(
            cmd, input=prompt, capture_output=True, text=True, cwd=scratch, timeout=HOST_TIMEOUT_S
        )
        if proc.returncode != 0:
            raise HostError(f"{host} exited {proc.returncode}: {proc.stderr.strip()[-500:]}")
        if host == "claude":
            return _claude_result(proc.stdout)
        return out_file.read_text(encoding="utf-8")


def _write_host_file(
    path: Path, host: str, model: str | None, raw: str, output: dict | None, commit: str
) -> None:
    path.write_text(
        json.dumps(
            {
                "host": host,
                "model": model or "default",
                "commit": commit,
                "ran_at": _now(),
                "raw": raw,
                "output": output,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _record_host_reply(
    path: Path, host: str, model: str | None, raw: str, commit: str
) -> dict | None:
    output = extract_json_object(raw)
    if output is None:
        logger.warning("%s: no JSON object in host reply; recorded raw text only", path.name)
    _write_host_file(path, host, model, raw, output, commit)
    return output


def _host_output(
    path: Path,
    host: str,
    model: str | None,
    prompt: str,
    fixture: str,
    *,
    checks_only: bool,
    run: RunFn | None,
    commit: str,
) -> tuple[dict | None, Check | None]:
    """The host output for one fixture: freshly produced, or read back with --checks-only.

    A host call that times out or errors fails only this fixture's row; the batch continues.
    """
    if checks_only:
        if not path.exists():
            return None, Check(
                "host_output_present", False, f"{path.name} missing; run without --checks-only"
            )
        return json.loads(path.read_text(encoding="utf-8")).get("output"), None
    if run is None:
        raise ValueError("run is required unless checks_only")
    try:
        raw = call_host(host, model, prompt, run=run)
    except (HostError, subprocess.TimeoutExpired) as exc:
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("%s: host call failed: %s", fixture, message)
        # A stale host file from a prior successful run must not survive this failure:
        # LangSmith and --checks-only would otherwise silently replay the old output.
        _write_host_file(path, host, model, message, None, commit)
        return None, Check("host_call", False, message)
    return _record_host_reply(path, host, model, raw, commit), None


def run_extract(
    host: str,
    model: str | None,
    boards: list[str],
    *,
    checks_only: bool,
    run: RunFn | None,
    commit: str,
) -> list[EvalRow]:
    rows = []
    for board in boards:
        jd_text = (EXTRACT_DIR / f"{board}.md").read_text(encoding="utf-8")
        golden = json.loads((EXTRACT_DIR / f"{board}.golden.json").read_text(encoding="utf-8"))
        path = EXTRACT_DIR / f"{board}.host.json"
        output, gate = _host_output(
            path,
            host,
            model,
            extract_prompt(jd_text),
            board,
            checks_only=checks_only,
            run=run,
            commit=commit,
        )
        checks = [gate] if gate else extract_run_checks(json.dumps(output), golden, jd_text)
        rows.append(EvalRow("extract", board, checks))
        logger.info("extract %s: %s", board, "PASS" if rows[-1].passed else rows[-1].first_failure)
    return rows


def run_tailor(
    host: str,
    model: str | None,
    dirs: list[Path],
    *,
    checks_only: bool,
    run: RunFn | None,
    commit: str,
) -> list[EvalRow]:
    rows = []
    for case_dir in dirs:
        case = TailorCase.from_dir(case_dir)
        fixture = case_id(case_dir)
        path = case_dir / "host.json"
        output, gate = _host_output(
            path,
            host,
            model,
            tailor_prompt(case),
            fixture,
            checks_only=checks_only,
            run=run,
            commit=commit,
        )
        checks = [gate] if gate else tailor_run_checks(case, output)
        rows.append(EvalRow("tailor", fixture, checks))
        logger.info("tailor %s: %s", fixture, "PASS" if rows[-1].passed else rows[-1].first_failure)
    return rows


def format_table(rows: list[EvalRow]) -> str:
    width = max([len("fixture"), *(len(r.fixture) for r in rows)])
    lines = [f"{'eval':8} {'fixture':{width}}  result  first failing check / note"]
    for row in rows:
        last_column = row.first_failure if not row.passed else (row.note or "")
        lines.append(f"{row.eval_name:8} {row.fixture:{width}}  {row.status:6}  {last_column}")
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=HOSTS, default="claude")
    parser.add_argument(
        "--model", default=None, help="host model flag; default is the host's own default"
    )
    parser.add_argument(
        "--eval", choices=EVALS, action="append", help="run only this eval (repeatable)"
    )
    parser.add_argument(
        "--case", action="append", help="run only this board or case name (repeatable)"
    )
    parser.add_argument(
        "--checks-only", action="store_true", help="re-run checks on saved host outputs"
    )
    parser.add_argument(
        "--no-langsmith", action="store_true", help="do not record a LangSmith experiment"
    )
    parser.add_argument(
        "--upload-private-inputs",
        action="store_true",
        help="upload full private-fixture inputs to LangSmith too (default: metrics only)",
    )
    return parser.parse_args(argv)


def _selected_boards(only: list[str] | None) -> list[str]:
    boards = sorted(json.loads((EXTRACT_DIR / "sources.json").read_text(encoding="utf-8")))
    selected = [b for b in boards if not only or b in only]
    if only and not selected:
        raise ValueError(f"no extract fixtures match --case {only}")
    return selected


def _selected_cases(only: list[str] | None) -> list[Path]:
    selected = [d for d in case_dirs("tailor") if not only or d.name in only]
    if only and not selected:
        raise ValueError(f"no tailor fixtures match --case {only}")
    return selected


CHECKS_ONLY_SKIP_MESSAGE = (
    "checks-only run: LangSmith recording skipped because saved outputs may come from "
    "another host, model, or commit"
)


def _record_experiment(
    record_fn: Callable[..., str | None],
    rows: list[EvalRow],
    args: argparse.Namespace,
    run_meta: dict,
    name: str,
) -> None:
    """Record a LangSmith experiment for this eval, unless disabled or ineligible.

    --checks-only never records: the saved host outputs it replays may come from a
    different host, model, or commit than `run_meta` claims. A LangSmith failure (auth,
    network, dataset) is logged and swallowed so the local results are still printed.
    """
    if args.checks_only:
        logger.warning(CHECKS_ONLY_SKIP_MESSAGE)
        return
    if args.no_langsmith:
        return
    try:
        record_fn(rows, run_meta, upload_private=args.upload_private_inputs)
    except LangSmithError as exc:
        logger.warning(
            "%s: LangSmith recording failed (%s); local results kept; experiment not recorded",
            name,
            exc,
        )


def _run_one_eval(name: str, args: argparse.Namespace, run_meta: dict) -> list[EvalRow]:
    """Run one eval kind (extract or tailor), recording a LangSmith experiment unless disabled."""
    if name == "extract":
        rows = run_extract(
            args.host,
            args.model,
            _selected_boards(args.case),
            checks_only=args.checks_only,
            run=subprocess.run,
            commit=run_meta["commit"],
        )
        _record_experiment(experiments.record_extract, rows, args, run_meta, name)
        return rows
    rows = run_tailor(
        args.host,
        args.model,
        _selected_cases(args.case),
        checks_only=args.checks_only,
        run=subprocess.run,
        commit=run_meta["commit"],
    )
    _record_experiment(experiments.record_tailor, rows, args, run_meta, name)
    return rows


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    wanted = args.eval or list(EVALS)
    run_meta = {"host": args.host, "model": args.model or "default", "commit": _commit()}
    rows: list[EvalRow] = []
    try:
        for name in wanted:
            rows.extend(_run_one_eval(name, args, run_meta))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(format_table(rows))
    return 0 if all(r.passed for r in rows) else 1
