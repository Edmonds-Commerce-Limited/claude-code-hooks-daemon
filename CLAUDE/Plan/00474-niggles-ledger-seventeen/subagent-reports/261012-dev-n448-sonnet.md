# N448 (GitHub #100): error hiding now covers a broad suppress()

Branch `worktree-issue-100-suppress`, one implementation commit (the hash is in the final reply; this report is committed with it).

## Red first

Run over the three touched test files before any source change: 37 failed, 266 passed. After the change the five touched/affected files ran 533 passed, 0 failed.

## What changed

- `strategies/error_hiding/python_strategy.py`: new pattern `broad suppress()`. Regex: `^[^#\n]*?\bsuppress\s*\(\s*\(?\s*(?:[\w.]+\s*,\s*)*(?:builtins\.)?(?:Base)?Exception\s*[,)]`. Matches `contextlib.suppress`, bare `suppress`, `BaseException`, a tuple member at any position, a parenthesised tuple, `builtins.`-qualified names, whitespace and newlines inside the parentheses, a trailing comma. `Exception` must be a whole name, so `ExceptionGroup`, `MyException`, `errors.Exception`, `asyncio.CancelledError` and `OSError` do not match. The `^[^#\n]*?` prefix keeps a trailing `# ...` comment that mentions the form clear. A string literal holding the form still matches (a regex over file content cannot tell, as for every other pattern in the strategy); the release note says so. The `example` is built by concatenation so the strategy file does not contain the form it blocks.
- `handlers/pre_tool_use/error_hiding_blocker.py`: `get_claude_md()` Python bullet now names the broad `suppress(...)` form and says a narrow one is allowed. The `CLAUDE.md` handler block is generated from this on daemon restart; I did not hand-edit it. No other doc enumerates the Python patterns (searched CLAUDE/, docs/, src/, README).
- `scripts/qa/audit_error_hiding.py`: `visit_With` / `visit_AsyncWith` flag a `With` item whose context expression is a call to `suppress` (bare or attribute) with `Exception` / `BaseException` (or `builtins.` form, or a tuple holding one) among its positional args. New rule `broad-suppress` in `VIOLATION_TYPES`, the module docstring, and `scripts/qa/qa-rules.json` (the rule-registry tests require the registry entry). Any item of a multi-item `with` is checked; module-level `with` is covered; the violation carries the enclosing function.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/048-error-hiding-now-blocks-a-broad-suppress-block.md` (Audience: client projects).

## Tests added

- `tests/unit/strategies/error_hiding/test_python_strategy.py`: `TestPythonStrategyBroadSuppress` (11 positive forms, 11 negative forms including comments, suggestion text).
- `tests/unit/handlers/pre_tool_use/test_error_hiding_blocker.py`: `TestErrorHidingBlockerBroadSuppress` (Write deny, Edit tuple deny, narrow allow, guidance names it).
- `tests/unit/qa/test_audit_error_hiding.py`: `TestBroadSuppressRule` (7 flagged headers, async with, second with item, module level, 9 not-flagged headers, non-call with, description present).
- All fixtures build the broad name by concatenation, so these files do not themselves trip the handler once it is live.

## In-tree fixes (not exempted)

1. `daemon/server.py` `_probe_socket_liveness`: `await writer.wait_closed()` after `writer.close()` on an already-connected unix socket. What can really come out of `wait_closed` there is the peer resetting or breaking the pipe during close: `ConnectionResetError` / `BrokenPipeError`, both `OSError`. The LIVE verdict was already earned by the successful connect, so these must not change it. Narrowed to `contextlib.suppress(OSError)`, with a comment saying why. Anything else (a programming error) now propagates instead of being eaten. Behaviour for the real failure modes is unchanged.
2. `tests/unit/daemon/test_server_liveness_reuse.py` finally-block: `await asyncio.wait_for(task, timeout=...)` on the two start tasks. The loser's task ends with `DaemonAlreadyRunningError` (the test asserts that); the winner's start task may still be serving when `wait_for` times out and cancels it, which surfaces as `TimeoutError`. Narrowed to `suppress(DaemonAlreadyRunningError, TimeoutError)`, with a comment. A cancelled task is `CancelledError` (a `BaseException`), which the old `Exception` form never caught either, so nothing regresses. The file's tests (all of `test_server_liveness_reuse.py`) pass.

## QA

- pytest over `tests/unit/strategies/error_hiding`, `test_error_hiding_blocker.py`, `test_audit_error_hiding.py`, `test_qa_rules.py`, `test_server_liveness_reuse.py`: 533 passed, 0 failed.
- `scripts/qa/audit_error_hiding.py`: clean (0 violations). A scan of every `.py` under `src/`, `tests/`, `scripts/` with the new regex finds no remaining match.
- `./scripts/qa/llm_qa.py changed` (in the worktree): 39/40. The one red is `changed_tests`: 3528 passed, 0 failed, 9 skipped, failing only because two changed files are unmapped as too broad (`daemon/server.py`, `handlers/pre_tool_use/error_hiding_blocker.py`), the same condition recorded for N446. All lint, format, type_check, pyright, error_hiding, docs_qa, plan_qa, doc_truth, generated_doc_drift, sensitive_content, security and the rest were green.

## Deviations / notes

- No full suite, as briefed.
- `changed_tests` red is the unmapped-file rule, not a test failure; mapping those two files is a coordinator call (I did not add a map rule).
- The narrow `suppress(OSError)` vs `except OSError: pass` inconsistency is left as ruled.
