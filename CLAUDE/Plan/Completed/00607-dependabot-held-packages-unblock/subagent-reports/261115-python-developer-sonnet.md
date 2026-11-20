# Plan 00607 report: dev-tool pins removed from uv.lock

## What changed

- `safety` removed from the `dev` extra. Nothing ran it (no script, workflow, pre-commit hook, import or doc).
- `semgrep` removed from the `dev` extra. `scripts/qa/run_semgrep_check.sh` now runs it with
  `uv tool run --from semgrep==<pin> semgrep`. The pin (1.185.0) lives only in `scripts/qa/semgrep-version.txt`.
- Fail-closed: the wrapper writes the existing error JSON and exits 1 when the pin file is missing, uv is missing,
  or the tool does not report the pinned version.
- `.github/actions/setup-env/action.yml` cache key now also hashes the pin file. CI already has uv on PATH.
- `CLAUDE/QA.md` documents the new home. `tests/unit/qa/test_run_semgrep_check.py` gains resolution tests and drops the
  obsolete "remedy syncs from the lock" test.
- deptry config unchanged: DEP002 is already ignored and neither tool was imported.

## Lock movement (uv lock --upgrade)

- filelock 3.32.7 -> 4.2.10 (patched at 4.2.1).
- Removed: safety, safety-schemas, semgrep 1.184.0, mcp 1.29.0, all opentelemetry-\* 1.37.0 / 0.58b0, and their
  transitive packages (httpx, starlette, uvicorn, pydantic-settings, jinja2, and others; 50 removals in all).
- Also upgraded: ruff 0.17.4 -> 0.17.5, coverage 7.13.5 -> 7.17.3, click 8.4.2 -> 8.5.1, requests 2.33.1 -> 2.34.2,
  and others. `uv tree --invert --package mcp` and `--package opentelemetry-api` find nothing.

## Verification

- `llm_qa.py semgrep`: 0 violations, also with `UV_OFFLINE=1` once warmed.
- shellcheck clean on the wrapper.
- `scripts/install/venv.sh` adds `--extra dev` only for a self-install (not under `.claude/hooks-daemon`), so a client
  install never gets the dev extra. No release note is needed.

## Review fixes

- Five rule-pinning tests (freshness_verdict, unlocked_eviction, unbounded_source_reads, stdlib_shlex_quadratic,
  pathlib_quadratic_containment) ran `.venv/bin/semgrep`, which a fresh `uv sync --frozen` no longer has. New shared
  helper `tests/support/semgrep_tool.py` (`semgrep_argv()`) builds the pinned `uv tool run --from semgrep==<pin>` argv
  from `scripts/qa/semgrep-version.txt`; all five tests use it. No other semgrep invocation exists under `tests/`.
- Red: with a synced venv (no semgrep, no safety, filelock 4.2.10) the five files gave 2 failed, 15 errors, 5 passed.
  Green after the helper: 22 passed.
- `run_semgrep_check.sh` now writes the real probe error into the error JSON (`semgrep unavailable: <cause>`),
  JSON-escaped via `json.dumps`; `test_run_semgrep_check.py` asserts the cause is present.
- `CLAUDE/QA.md` notes that the pin fixes semgrep, not its unlocked transitive dependencies.
