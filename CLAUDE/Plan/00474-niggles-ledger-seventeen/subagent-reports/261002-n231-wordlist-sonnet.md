# N231: an unreadable secret word list must not mean "no terms"

Branch `worktree-n231-wordlist`. Rebuilt fresh on main; the dropped branch's names
(`require_active_secret_terms`, `check_git_blobs`) do not exist here.

## Decision: what counts as "exists"

`load_secret_terms` stats the path. Not found or not-a-directory-component means
ABSENT (inert), unless the path is a dangling symlink. Everything else is an
error: any other stat failure, a non-regular file (directory, FIFO), and any
OSError on read. Rationale: any filesystem entry at the configured path is the
project opting in, so only a readable regular file may stand in for the list.
The error subclasses `OSError` so the sinks that already catch `OSError` skip
their write. The message names the path and the OS reason, never content.
`get_cached_secret_terms` never caches a failure.

## Consumers and behaviour now

| Consumer                                            | Behaviour                                                                                                                                                                                                                                           |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sensitive_content` `matches`/`handle`              | matches() returns True, handle() DENIES with a purpose-built reason (path named, no term). Without the catch, chain.py would deny with the generic "evaluation error" text for a SAFETY+BLOCKING handler.                                           |
| `sensitive_content.scan_text` (remote-docs capture) | returns a "cannot be checked" finding, so the capture is refused                                                                                                                                                                                    |
| `scripts/qa/check_sensitive_content.py`             | `ConfigError`, run fails with a config violation                                                                                                                                                                                                    |
| `scripts/qa/check_git_history.py`                   | `ConfigError`, run fails with a config violation                                                                                                                                                                                                    |
| `core/router.py` PreToolUse debug log               | payload replaced by `[WITHHELD: ...]` (withhold)                                                                                                                                                                                                    |
| `core/front_controller.py` error log                | exception line still written, hook input withheld                                                                                                                                                                                                   |
| `daemon/server.py` blocking-response log            | response withheld                                                                                                                                                                                                                                   |
| `daemon/server.py` payload capture                  | the error is an OSError, caught by the existing handler, so the capture is skipped (fail closed)                                                                                                                                                    |
| `model_fallback_detector` snapshot                  | no snapshot written, advisory says it was withheld                                                                                                                                                                                                  |
| `cli.py` skill-scan, bug-report, issue-report       | `main()` catches the error, prints it to stderr, exit 1 (refuse)                                                                                                                                                                                    |
| `scripts/debug_info.py`                             | unchanged: it already catches OSError and prefixes the report with a "Secret word list not applied ... check by hand" banner, so it now shows that banner instead of silently scrubbing nothing. Left as a warned degrade by its documented design. |

Shared helper: `redact_structure_active` and `WITHHELD_PLACEHOLDER` in
`utils/secret_redaction.py`.

## What remains (not done)

- `_resolve_active_path` still goes inert (WARNING log) when the project CONFIG
  cannot load. That is a different defect (unreadable config, not an unreadable
  list) and was not touched.
- `get_active_secret_terms` previously documented "never raises"; it now raises
  for an unreadable configured list. All src/ callers were enumerated above;
  none outside src/scripts were checked.

## RED evidence

Before the implementation, `tests/unit/utils/test_secret_word_list_unreadable.py`:
17 failed, 5 passed (the 5 are the absent-list and pass-through controls).
Failures: `AttributeError: ... has no attribute 'SecretWordListUnreadableError'`
for the load/cache/sink tests; handler `assert False is True` (matches) and
`ALLOW == DENY` (handle); QA checks `DID NOT RAISE ConfigError`.

## QA (targeted)

- new test file: 24 passed
- 31 related unit/integration files (secret, sensitive, router, front_controller,
  server, fallback, check_git_history, check_sensitive_content, payload capture,
  leak coverage): 1917 passed, 4 failed. The 4 patched the old names imported into
  `core/router.py` and `core/front_controller.py`; retargeted to patch
  `secret_redaction.get_active_secret_terms`, then front_controller + router +
  new file: 105 passed. `tests/unit/daemon/test_cli.py` matched no tests.
- black --check --target-version py311: clean; ruff check: clean
- mypy on the 10 changed files: no issues
- `scripts/qa/audit_error_hiding.py`: pass; `check_input_contract.py`: pass;
  `run_pyright_check.py --json`: 0 errors, 0 warnings
- No suppressions, no allowlist or exclusion entries. Full suite not run.
