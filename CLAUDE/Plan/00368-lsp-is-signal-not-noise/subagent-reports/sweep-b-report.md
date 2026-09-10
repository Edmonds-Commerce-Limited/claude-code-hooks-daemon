# Plan 00368 Task 3.1 — Partition B report (`tests/unit/handlers/**`)

**Worktree**: `worktree-plan-00368c`, branch `worktree-plan-00368c`.
**Commit**: `7be5d9ee` (pushed to `origin/worktree-plan-00368c`).

## Error count

|                                                              | pyright errors under `tests/unit/handlers/` |
| ------------------------------------------------------------ | ------------------------------------------- |
| Before (partition baseline, per journal 09:05 entry)         | 433 (50 files)                              |
| At session start (49 of 50 files already fixed, uncommitted) | 3 (1 file: `test_registry.py`)              |
| After this session                                           | 0                                           |

## What I did

The previous agent's parallel sub-agents had already fixed 49 of the 50
files in this partition (Optional narrowing via `getattr(obj, "_attr", None)`

- `assert x is not None`, matching the pattern the team lead specified). I
  verified those edits pass pytest, then fixed the one remaining file:

* `tests/unit/handlers/test_registry.py` — three `reportArgumentType`
  errors, all on calls to `HandlerRegistry.register_all(router, config=...)`. Cause: `register_all`'s declared parameter type
  (`dict[str, dict[str, dict[str, Any]]] | None`, in
  `src/claude_code_hooks_daemon/handlers/registry.py:403`) models every
  per-event config entry as a handler-name-keyed nested dict, but the
  function's own body also reads event-level `enable_tags`/`disable_tags`
  keys straight off the same dict as a plain `list[str]`/`str` — a shape
  the declared type doesn't structurally capture, so a dict literal built
  for that test shape doesn't unify with the invariant parameter type.
  This is a `src/` typing gap, not a test bug, and is out of my partition
  (partition A owns `src/`) — I did not touch `src/`. Fixed test-side by
  annotating the three local `config` fixtures as `dict[str, Any]`
  (`Any` is bidirectionally compatible through Python's invariant dict
  generics, so this resolves cleanly with no `cast`, no `# type: ignore`,
  no `# pyright: ignore`). Each annotation carries a one-line comment
  explaining why.

## Verification

- `pyright --project . --pythonpath <worktree venv>/bin/python` (scoped to
  `tests/unit/handlers/test_registry.py`, then whole-tree): 0 errors under
  `tests/unit/handlers/` in both runs.
- `pytest tests/unit/handlers -q`: **6256 passed, 1 skipped, 1 xfailed**
  (skip/xfail both pre-existing and expected — a documented design-test
  skip and a Plan 00260 Task 3.1 known-behaviour marker).
- `./scripts/qa/llm_qa.py all` (whole repo): **24/26 PASSED**. The 2
  failures are both **pre-existing on `main`**, introduced by Plan 00367
  (`d4791899`, `68c1510e`), and **outside this partition**:
  - `error_hiding`: 1 `silent-continue` violation in
    `src/claude_code_hooks_daemon/docs_qa/checks/unenforced_approval_gate.py:196`.
  - `tests`: 12 failing/errored tests, all under `tests/acceptance/`,
    `tests/integration/test_plan_index_navigability.py`, and
    `tests/unit/qa/test_audit_error_hiding.py::TestRealRepoSelfScan::test_repo_is_clean_under_widened_scope`
    — none under `tests/unit/handlers/`.
  - `type_check` (mypy) passed with 0 errors. Note: the whole-repo pyright
    gate is not yet wired into `llm_qa.py`, so this run does not surface
    partition A's remaining `src/` pyright errors — that will only show
    once Plan 00368's pyright-gate task lands.

## Decisions

1. **No `src/` changes.** The `register_all` config-type gap is a real
   typing imprecision in `src/claude_code_hooks_daemon/handlers/registry.py`
   (its `dict[str, dict[str, dict[str, Any]]]` signature doesn't model the
   `enable_tags`/`disable_tags` event-level keys it also accepts), but
   fixing it belongs to partition A. Flagging it here per the task
   instructions rather than crossing the partition boundary.
2. **`dict[str, Any]` over `cast`.** Both resolve the invariance mismatch;
   `dict[str, Any]` was chosen as it needed no import and reads as "this
   fixture's shape is heterogeneous by design," which is accurate here.
3. Committed the 49 prior-agent fixes and my 1-file fix together as a
   single batch (`7be5d9ee`) since the prior agent's work was already
   verified green together with mine — no benefit to splitting the commit
   further, and the team lead's given batching guidance was single-commit
   after the first-batch pytest confirmation.

## Remaining errors needing `src/` changes

None strictly required for this partition to be clean. The one
type-imprecision noted above (`register_all`'s `config` parameter type)
is worth partition A's attention if it wants the signature to be
self-documenting, but it is not blocking: the test-side `dict[str, Any]`
fixture typing is a legitimate, permanent fix, not a workaround pending a
`src/` change.
