# Local Model and Hermes Evals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. Work inline unless the user requests delegation.

**Goal:** Run the existing extraction and tailoring evals against Ollama, llama.cpp, or Hermes, with optional model overrides, native defaults where available, and local port overrides.

**Architecture:** Extend the existing runner's host boundary. Ollama and llama.cpp share one standard-library HTTP helper; Hermes uses the existing subprocess pattern. Reuse all prompts, fixtures, checks, output paths, and LangSmith recording.

**Tech Stack:** Python 3.12+, argparse, urllib.request, subprocess, existing pytest and Ruff.

**Spec:** The user's September 28 request in this conversation, the contract below, and `AGENTS.md`'s North Star: “Get the user past the ATS gate so they talk to a human recruiter.”

## Contract and assumptions

This is a bounded extension to the existing eval flow. This document is the requested plan; it does not authorize implementation or paid model calls.

| Option | Behavior |
|---|---|
| `--host` | Accept `claude`, `codex`, `ollama`, `llamacpp`, `hermes`; default remains `claude`. |
| `--model` | Required and nonblank for fresh Ollama and llama.cpp runs. Optional for Claude, Codex, and Hermes; omit the CLI model flag when absent so the harness uses its default. Reject an explicitly blank value for every host. |
| `--port` | Optional integer, 1–65535; valid only for Ollama and llama.cpp. Defaults: Ollama 11434, llama.cpp 8080. |
| `--provider` | Optional nonblank Hermes provider identifier, passed to Hermes. Reject it for other hosts. Without it, Hermes uses its native provider resolution; record `auto`. |
| `--checks-only` | Read saved output with no host process, HTTP request, model requirement, or experiment upload. Still reject invalid flag combinations and invalid ports. |

- Local requests use `http://127.0.0.1:<port>/v1/chat/completions`. A port override changes only the port.
- The user starts the local server and loads a model. Installing Ollama or llama.cpp alone does not start an eval endpoint. Require the llama.cpp server, not its interactive CLI.
- Send an explicitly selected model verbatim. Require `--model` for both local servers, including single-model llama.cpp. Reject a missing local model before any host call or output write. No discovery or selection of the first installed model.
- Claude, Codex, and Hermes must use their own defaults when `--model` is absent. Remove the runner's `CODEX_DEFAULT_MODEL` override. Read only saved model names before launching the isolated CLI; record the resolved name when available. Do not import other user settings or force the old Codex model.
- Hermes behavior: disable personal customizations with `--safe-mode`. Credentials remain managed by Hermes. This disables user config, rules, memory injection, plugins, and MCP; it does **not** promise that built-in tools are disabled. Hermes results measure the harness with those built-in behaviors, while local HTTP results measure a direct model reply. Record this distinction.
- Read the Hermes provider from its saved model settings when no provider override is supplied. Named custom providers defined only in ignored user config remain unavailable; document that limit. Hermes credentials remain managed by the harness.
- Local services must be unauthenticated loopback endpoints for this scope. Remote URLs, authenticated local proxies, and Hermes routing to a local endpoint are separate requests.

## Global constraints

- Add no dependencies, provider classes, registration framework, server-side LLM calls, or graph changes.
- Keep imports at the top. Catch only expected failures and raise `HostError` with context.
- Retain the existing 900-second host timeout and sequential fixture execution.
- No retry, provider fallback, model fallback, or reuse of stale answers after a failed fresh call.
- Keep the existing JSON reply extraction and deterministic checks; do not force JSON format or change sampling settings only for local hosts.
- CI calls no real model. Extend the existing tests with fake subprocesses and HTTP responses.
- Keep all existing output paths. Runs still overwrite the previous answer for each fixture; parallel multi-model runs are unsupported.
- Preserve existing Claude/Codex metadata shape. Add new routing fields only where applicable. Never store credentials, credential files, or full environment contents.

## Review focus

- Server unavailable, HTTP error, or timeout: show a failed fixture, clear stale output, continue the batch.
- HTTP 200 with missing/empty content or invalid JSON: fail the host call, not pass a blank response to checks.
- Unsupported Hermes flags or malformed event output: fail clearly; never silently run without isolation.
- Wrong port/provider/model arguments: fail before calling any host or overwriting output.
- Saved replies from another host: checks-only remains offline and never labels them as a fresh experiment.

## Sources checked during planning

- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility): local port 11434 and chat completions response.
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md): default port 8080 and `/v1/chat/completions`.
- [Hermes CLI parser](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/_parser.py): query files, safe mode, provider/model overrides, and stream-json output.
- Installed Hermes source also has `hermes_cli/stream_json.py`: terminal record uses `type: result`, `text`, and `exit_code`.
- The sandbox initially blocked the Hermes launcher's install lock. An authorized `hermes chat --help` subsequently verified all required flags. No Hermes installation repair or modification was needed.

---

### Task 1: Add local HTTP model calls and port selection

**Files:** Modify `evals/runner.py`, `evals/test_runner.py`.

**Interfaces:**
- Extend `call_host(host: str, model: str | None, prompt: str, run: RunFn = subprocess.run, *, port: int | None = None, provider: str | None = None) -> str` without breaking existing callers.
- Add `_call_local_host(host: str, model: str, prompt: str, port: int) -> str`.
- Add `_local_port(host: str, port: int | None) -> int`, resolving the two documented defaults.
- Thread optional `port` and `provider` keyword arguments through `_host_output`, `run_extract`, and `run_tailor`; `_run_one_eval` passes parsed values.
- Add `_validate_args(args: argparse.Namespace) -> None`; call it before `_commit()` and any fixture work. `main` prints a validation error and returns 1, using the existing ValueError handling pattern.

- [x] **Step 1: Extend the existing tests.**

  Parameterize request tests for `ollama:11434`, `llamacpp:8080`, and overrides `ollama:12345`, `llamacpp:8081`. Patch `build_opener` to return a fake opener; assert proxy handling is explicitly disabled, and assert the exact URL, POST, JSON content type, timeout 900, and body:

  ```python
  {"model": "chosen-model", "messages": [{"role": "user", "content": "PROMPT"}], "stream": False}
  ```

  Return `{"choices": [{"message": {"content": "MODEL REPLY"}}]}` and assert the helper returns `MODEL REPLY`. Assert the subprocess fake is never called.

  Parameterize missing-model validation for Ollama and llama.cpp. Assert a fresh run returns 1 with `--model is required for --host <host>` before any host call or output write. Assert an explicit model is forwarded verbatim. Add argument tests for explicitly blank models for every host; ports 0, -1, 65536, noninteger, 1, and 65535; a port supplied to Claude/Codex/Hermes; and a provider supplied to a non-Hermes host. Assert invalid arguments cause no host call or output write. Checks-only never requires a model, including for Ollama and llama.cpp.

  Parameterize failures for `HTTPError`, `URLError`, timeout, malformed response JSON, wrong response shape, empty choices, nonstring content, and blank content. Expect `HostError` naming the host and port. Avoid catching arbitrary exceptions.

  Extend the stale-file/batch-continuation tests to a local connection failure. Assert the failed output becomes null and the next fixture runs. Extend the offline test to local hosts with HTTP/subprocess sentinels.

- [x] **Step 2: Run `uv run pytest evals/test_runner.py -v`.** New tests fail because local routing and validation are absent.
- [x] **Step 3: Implement the minimal local helper.** Use top-level stdlib imports for `Request`, `build_opener`, `ProxyHandler`, `HTTPError`, and `URLError`. Use `build_opener(ProxyHandler({})).open(request, timeout=HOST_TIMEOUT_S)` so a shell's proxy settings cannot redirect the loopback request. Decode the outer response and validate the first message's content. Convert expected HTTP/network/response failures into contextual `HostError` so existing fixture failure handling applies. Do not request `response_format` or send tool definitions.
- [x] **Step 4: Wire the flags through both eval kinds.** Require `run` only for CLI hosts; checks-only must return before transport selection. Resolve the local default once when forming run metadata and use the same value for requests.
- [x] **Step 5: Run `uv run pytest evals/test_runner.py -v` and `uv run ruff check evals/runner.py evals/test_runner.py`.** All pass; split small helpers only if the existing complexity limit of 7 requires it.
- [x] **Step 6: Commit only the task's files:** `feat: run evals against local model servers`.

### Task 2: Add Hermes subprocess support

**Files:** Modify `evals/runner.py`, `evals/test_runner.py`.

**Interfaces:**
- Add `_hermes_cmd(model: str | None, provider: str | None) -> list[str]`.
- Add `_hermes_result(stdout: str) -> str`, returning only the terminal event's answer text.
- Reuse Task 1's optional provider argument and model validation. Omit `--model` when absent so Hermes resolves its native default. Read saved model/provider names separately before safe mode; pass those routing choices explicitly.

- [x] **Step 1: Add subprocess contract tests.** Assert this command and unchanged prompt passed as stdin in the existing scratch directory:

  ```text
  hermes chat --query-file - --oneshot --quiet --format stream-json --safe-mode --model chosen-model
  ```

  With a provider, append `--provider <selected-provider>`. With no model, omit the entire `--model chosen-model` pair. Add a Codex regression test asserting no `-m` argument when its model is omitted; preserve explicit-model behavior. No shell invocation, session resume, plugin activation, or approval-bypass flag. Test nonzero process exits and missing executable as `HostError` failures; the batch continues through the existing failure path.

  Add parser tests using JSON lines: system/init, text deltas, optional tool events, then `{"type":"result","exit_code":0,"text":"MODEL REPLY"}`. Assert only final text is returned. Malformed JSON lines, missing/duplicate result records, nonzero result exit code, reported error, nonstring/blank text all raise `HostError`, even if the process exits zero. Do not apply first-brace/last-brace parsing to the full event stream.

  Assert checks-only never launches Hermes, including when model/provider are absent.

- [x] **Step 2: Run `uv run pytest evals/test_runner.py -v`.** New Hermes tests fail.
- [x] **Step 3: Add command selection and event parsing.** Keep Claude/Codex isolation flags; remove the hardcoded Codex default and pass a saved model name when available. Add narrow handling of `FileNotFoundError` for a missing host CLI. Catch unsupported CLI versions through nonzero exit status; include stderr and require upgrading, with no permissive fallback.
- [x] **Step 4: Run `uv run pytest evals/test_runner.py -v` and `uv run ruff check evals/runner.py evals/test_runner.py`.** Existing isolation and output tests still pass.
- [x] **Step 5: Commit only the task's files:** `feat: add Hermes eval host`.

### Task 3: Record routing, make calls visible, and document usage

**Files:** Modify `evals/runner.py`, `evals/test_runner.py`, `evals/test_experiments.py`, `scripts/run_evals.py`, `README.md`, `AGENTS.md`.

**Interfaces:**
- `_write_host_file` and `_record_host_reply` accept optional keyword `routing: dict | None = None`; add its fields only for new hosts. Pass the same routing on successful and failed calls.
- Local routing fields: `port` (resolved integer), `transport: "http"`.
- Hermes routing fields: `provider` (selected value or `"auto"`), `transport: "cli"`, `isolation: "customizations_disabled"`, `builtin_tools: true`.
- Add those fields to `run_meta`; `evals/experiments.py` already forwards the dictionary, so no new experiment recorder is needed.

- [ ] **Step 1: Add metadata and log tests.** Assert a local default port, port override, and Hermes provider appear consistently in host files and experiment metadata. Assert legacy Claude/Codex exact output dictionaries still pass. Assert failed calls retain routing metadata and null output. Checks-only invokes neither host nor experiment recording.

  Add INFO log assertions for `calling host=<host> model=<model> fixture=<fixture>` before a fresh call, plus port/provider when applicable. Log `checking saved output fixture=<fixture>` for checks-only. Do not log prompts, environment values, or credentials.

- [ ] **Step 2: Run `uv run pytest evals/test_runner.py evals/test_experiments.py -v`.** New metadata/log tests fail.
- [ ] **Step 3: Add routing metadata and the two log messages.** Preserve current experiment name format `<commit>-<host>-<model>`; routing differences live in experiment metadata. Record explicit new-host models verbatim. Document that Hermes `auto` is a request to the harness, not a verified resolved provider.
- [ ] **Step 4: Update usage docs and runner docstrings.** Include the examples below, server prerequisites, model/alias requirements, Hermes isolation limits, offline checks-only behavior, and existing output overwrite behavior. Replace the outdated claim that all supported hosts run without tools. Keep the server's host-owned reasoning boundary explicit in `AGENTS.md`.

  ```bash
  uv run python scripts/run_evals.py --host ollama --model qwen3:8b --eval extract --case reddit
  uv run python scripts/run_evals.py --host ollama --model qwen3:8b --port 12345 --eval extract --case reddit
  uv run python scripts/run_evals.py --host llamacpp --model resume-eval --port 8081 --eval tailor --case jane-doe-backend
  uv run python scripts/run_evals.py --host hermes --provider openrouter --model <model-id> --eval extract --case reddit
  uv run python scripts/run_evals.py --host hermes --eval extract --case reddit
  uv run python scripts/run_evals.py --checks-only
  ```

  Mark model names as examples; `resume-eval` must be the configured llama.cpp server alias, and `<model-id>` must be replaced. Show the llama.cpp default 8080 separately so an override example does not hide it.

- [ ] **Step 5: Run repository checks.**

  ```bash
  uv run pytest -m "not local"
  uv run ruff check .
  uv run ruff format --check .
  uv run pyright
  ```

  Expect no regressions. Run existing local checks over saved outputs with `uv run pytest -m local evals/`; distinguish known baseline model-quality failures from implementation regressions. Do not change expected checks or fabricate replies to make the baseline pass.

- [ ] **Step 6: After implementation is approved, perform one live fixture per installed target.** Verify Hermes CLI help first. Use `--no-langsmith`, an already running local server, and an explicitly selected model. Obtain model-call authorization if the implementation request does not cover paid Hermes inference. Report unavailable services honestly. These calls overwrite host files; restore only generated fixture changes from this smoke run, preserving any pre-existing user edits. Successful transport need not mean the model passes every quality check.
- [ ] **Step 7: Commit only the task's files:** `docs: explain local and Hermes eval runs`.

## Ponytail scope

One shared local request helper; one Hermes subprocess path; existing runner tests. Skip remote endpoints, API-key flags, automatic model discovery/download, starting servers, retries, parallel runs, per-model output directories, and a general provider framework. Add those only when a concrete eval run needs them.
