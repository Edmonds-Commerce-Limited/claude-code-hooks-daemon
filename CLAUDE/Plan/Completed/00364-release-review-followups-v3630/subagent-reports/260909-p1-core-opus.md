# Plan 00364 Phase 1 — core / daemon / config_optimisation

Worktree `untracked/worktrees/worktree-plan-00364-p1-core`, branch of the same
name. Source: `review-reports/260909-review-core-opus.md` NOTEs 2-7. All six
tasks done, each started from a failing test.

## What changed, task by task

### Task 1.1 — venv lock race, and the misreport it caused (NOTE 2)

`_mkdir_lock` checked a held lock's age with a `stat()` on the line after its
`mkdir()` failed. The holder's `rmtree` landing in that gap — the exact
contention the lock exists for — made the `stat` raise `FileNotFoundError`,
which escaped the lock layer entirely and was caught three frames up by
`cmd_repair`'s handler, printing "'uv' not found. Install with: curl ...".

The gap now reads as "the lock just became free" and the lock is retaken. The
retry is bounded by the same deadline, and only the FIRST one is immediate, so
a lock name that can never be stat'ed (a dangling symlink at
`.venv-bootstrap.lock.d`) ends in `VenvLockTimeout` instead of spinning. Both
shapes have a test.

`cmd_repair`'s "install uv" message moved down to the `uv sync` spawn inside
`_repair_venv_locked`, the only place that can mean it. The post-sync
verification spawn got its own message naming the venv interpreter. The outer
handler now reports whichever path was actually missing.

- `src/claude_code_hooks_daemon/daemon/venv_lock.py`
- `src/claude_code_hooks_daemon/daemon/cli.py` (`cmd_repair`, `_repair_venv_locked`)
- `tests/unit/daemon/test_venv_lock.py`, `tests/unit/daemon/test_cli_repair.py`

The NOTE's lower-confidence second half (two waiters both judging a lock stale
and both `rmtree`-ing it) is untouched, per the plan's Non-Goals.

### Task 1.2 — a failing git listing no longer reads as a clean slate (NOTE 3)

`_git_lines` now returns `list[str] | None`, and a small `_GitReads` collector
records every read that failed. `SlateReport` gained `undetermined_reason`;
`is_clean` is False whenever it is set, `render()` prints
`Slate: UNDETERMINED — <what failed>`, and `cmd_release_slate_check` returns
`RELEASE_SLATE_UNDETERMINED`. That check runs BEFORE the `--accept` branch, so
acknowledging work in flight still does not acknowledge blindness. The `--json`
output carries the same field.

One subtlety worth keeping: `collect_slate` finishes every git read into locals
before constructing the report, because reading `reads.problem` inline would
capture only the failures seen up to that argument's position.

- `src/claude_code_hooks_daemon/core/release_slate.py`
- `src/claude_code_hooks_daemon/daemon/cli.py` (`cmd_release_slate_check`, `_slate_as_json`)
- `CLAUDE/development/RELEASING.md` — the exit-1 row now names a failing git listing
- `tests/unit/core/test_release_slate.py`, `tests/unit/daemon/test_cli_release_slate_check.py`

### Tasks 1.3 and 1.4 — the optimise checklist stops guessing (NOTEs 4, 5)

Three functions now live in `handlers/registry.py` and are the only place the
enablement rule is written: `config_skip_reason` (gates 1-2, decided before
construction), `tag_skip_reason` (gates 3-4, which need the instance's tags)
and `handler_is_enabled` (all four, for a caller that already has the tags).
`register_all` calls the first two at the two points it already gated; the
checklist calls the composite. `build_checklist` gained `disabled_handlers`,
which is the fourth gate — registry runtime state, so a caller with no live
registry leaves it empty.

Two divergences the copy had already accumulated are gone:
`HandlerRegistry.is_disabled` was not mirrored at all, and `enable_tags` was
required to be a `list` where registration accepts any truthy value. That
second one is not academic: YAML `enable_tags: safety` is a STRING, iterates as
characters, matches no handler and takes the whole event dark — while the
report called every handler on that event enabled.

The pin is a cross-check test: register handlers for one config through a real
`HandlerRegistry` and `EventRouter`, then assert the checklist's `enabled`
matches whether registration actually registered it, for every built-in.

For Task 1.4, `_probe()` wraps construction, `get_default_enabled()` and
`get_relevance()` together — all three are arbitrary handler code. A failure
becomes a `ChecklistItem` carrying `construction_error` and the new
`ItemStatus.UNASSESSED`, rendered under "could not be assessed" with the error
and counted separately in the JSON summary, rather than aborting the verb and
losing the other 113 verdicts.

- `src/claude_code_hooks_daemon/handlers/registry.py`
- `src/claude_code_hooks_daemon/config_optimisation/checklist.py`
- `tests/unit/config_optimisation/test_checklist.py`

### Task 1.5 — the constant spellings are read, not copied (NOTE 6)

`_LANGUAGE_MARKERS` is keyed on `HandlerTag.PYTHON` and friends;
`_AGENT_BEHAVIOUR_EVENTS` and `_SESSION_ENV_EVENTS` are built from
`EventID.*.config_key` and `pseudo_events.registry.NITPICK`.

This is a refactor, so there was no red-first behaviour test to write. What the
new tests pin instead is the invariant the finding is about: every marker key
must be a tag the catalogue declares, and every named event must exist in the
event catalogue. Those assertions fail on a rename, which is precisely the
drift that used to be silent.

`core/relevance.py`'s docstring claimed the module was pure stdlib. It now
depends on the constants catalogue, so the docstring says that instead. No
cycle: nothing under `constants/` imports from `core/`.

- `src/claude_code_hooks_daemon/core/relevance.py`,
  `src/claude_code_hooks_daemon/config_optimisation/areas.py`
- `tests/unit/core/test_relevance.py`, `tests/unit/config_optimisation/test_areas.py`

### Task 1.6 — the error names what the author declared (NOTE 7)

The `hook_input` + `dispatch_as_bash` pair is refused before
`_derive_bash_payload()` runs. The invariant is unchanged; the message now says
`hook_input and dispatch_as_bash`, not `tool_payload` — a field the derivation
had just populated and the author never wrote.

- `src/claude_code_hooks_daemon/core/acceptance_test.py`,
  `tests/unit/core/test_acceptance_test.py`

## Release-notes callouts

Four, in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`:
`02-repair-names-the-real-failure.md`,
`03-release-slate-fails-loud-on-a-git-failure.md`,
`04-optimise-report-agrees-with-the-daemon.md`,
`05-acceptance-test-error-names-what-you-wrote.md`. Task 1.5 has no
user-visible consequence and gets none.

## QA

`./scripts/qa/llm_qa.py all` from the worktree root: **21/26 passed**. Every
one of the five failures is an artefact of WHERE this worktree lives, not of
anything in Phase 1, and each was traced to its root cause rather than assumed.

| Tool                 | Verdict             | Cause                                    |
| -------------------- | ------------------- | ---------------------------------------- |
| `format`             | green on re-run     | black auto-fixed my two files in the run |
| `lint`, `type_check` | green               | 0 violations, 0 errors over 539 files    |
| coverage             | 95.4%               | above the 95% floor                      |
| `tests`              | 14 failed           | see below                                |
| `error_hiding`       | 172 stale-exclusion | the `untracked/` path artefact           |
| `capture_corruption` | no output at all    | same artefact                            |
| `smoke_test`         | 0/3 probes          | no daemon socket for this checkout       |

**The `untracked/` path artefact.** Both audit scripts exclude any path
containing `untracked`, and this worktree's absolute path is
`/workspace/untracked/worktrees/...` — so every file in it is excluded and each
audit scans nothing:

```
audit_capture_corruption.py: _EXCLUDE_DIR_PARTS = {"untracked", ...}
                             any(part in _EXCLUDE_DIR_PARTS for part in path.parts)
audit_error_hiding.py:       _DEFAULT_EXCLUDE_PATTERNS = ("untracked/", ...)
                             any(pattern in str(py_file) for pattern in ...)
```

Re-running each with the exclusion matched on the repo-root-PREFIXED path
instead settles it: capture-corruption finds 62 shell files and 0 violations;
error-hiding collects 203 violations against 177 exclusions with **0 stale**.
Both are clean. The two failing QA-audit unit tests
(`test_default_scan_dirs_clean`, `test_the_live_exclusions_file_has_no_stale_entries`)
are the same artefact reaching pytest.

**The daemon-dependent failures.** Ten `tests/acceptance/` tests and two
`tests/integration/test_forwarder_socket_stdin.py` tests need a live daemon
answering for THIS checkout, and `smoke_test` says so outright ("Daemon not
running — no socket found"). This worktree's deployed forwarder dials the MAIN
repository's daemon, which is Task 5.1 of this very plan. I did not start a
daemon here: `bin/hooks-daemon restart` from a worktree that relays to the main
repo could stop the daemon the coordinator's live session depends on, and that
is a state change worth a deliberate decision rather than a subagent's guess.

`tests/unit/handlers/test_sed_blocker.py`'s heredoc-markdown case appears in a
naive summary grep but is a declared `xfail` (Plan 00260 Task 3.1), not a
failure.

## For the coordinator

1. **Re-run QA after merge**, from the main checkout. All five failures above
   should clear there; if `error_hiding` or `capture_corruption` is red in
   `/workspace`, that IS a real finding and not this artefact.
2. **Worth filing as its own defect**: the QA audits cannot run from a worktree
   under `untracked/worktrees/`, which is one of the project's own two
   sanctioned worktree roots (`core/worktree_paths.WORKTREE_DIR_PATTERNS`). The
   fix is to match the exclusion against the repo-relative path. Silent in
   `capture_corruption`'s library path (its CLI does print "no shell files
   found"; the function the test calls does not), and actively misleading in
   `error_hiding`, where an empty violation set makes all 177 exclusions look
   stale.
3. `untracked/venv` in this worktree is a symlink I created to the
   fingerprint-keyed venv, because `scripts/qa/llm_qa.py` hardcodes
   `untracked/venv/bin/python`. It is gitignored and matches the main repo's
   own layout.
