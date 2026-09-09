# Plan 00364 Phase 3 — strategies / utils / block_report

Agent: python-developer (Opus 5), worktree `worktree-plan-00364-p3-strategies`.
Source: `review-reports/260909-review-strategies-opus.md`, findings 1-7.

All seven tasks are implemented, each with a failing test written first. Six
commits on the phase branch, not pushed.

| Commit     | Task(s) | Subject                                                      |
| ---------- | ------- | ------------------------------------------------------------ |
| `ff3f7c7d` | 3.1     | reject a wide bracket range before materialising it          |
| `528dd919` | 3.2 3.3 | kotlin docstring matches its command; one shared lint outdir |
| `ffb5179a` | 3.4     | cron_cadence takes its temp name from the shared helper      |
| `ac2f0dad` | 3.6     | the partial rule index announces itself once                 |
| `b5d4f45b` | 3.5     | PipeBlockerHandler aggregates its strategies' tests          |
| `e1820171` | 3.7     | drop the redundant `str()` around `scratch_path()`           |

## What each task did

**3.1 — bracket range cap moved before materialisation.** The width check now
sits inside `_bracket_expression_members`, so a range wider than
`_MAX_BRACKET_EXPANSIONS` returns `None` instead of being built and handed to
the product cap. **Behaviour-preserving by construction**: a range that wide
yields more than the cap's worth of DISTINCT members, so it could never have
survived the product check either — early and late rejection return the same
`[token]`. That is why no fallback-semantics test needed changing. Two new
tests pin the boundary from both sides, so the cheap check cannot silently
narrow what the guard expands.

**3.2 — Kotlin docstring.** Now `kotlinc (compilation check, class files discarded)`. The runnable-as-declared suite guarded the constant but not the
prose; it now guards both.

**3.3 — one shared lint output directory.** `lint_output_dir()` in
`strategies/lint/common.py` returns an `mkdtemp` path, unguessable, created
0700, memoised once per process. Kotlin's `-d` and both Rust commands'
`--out-dir` resolve through it, so the fixed shared-temp names are gone and a
third strategy cannot reintroduce a literal.

**3.4 — `cron_cadence` uses `unique_temp_path`.** The `O_EXCL` private-mode
open is untouched: the helper owns the NAME, not the mode.

**3.5 — aggregated, not deleted.** See the decision below.

**3.6 — one WARNING on the uncached rule-index branch**, naming
`ProjectContext`, emitted once per process via `lru_cache` (which also gives
tests a `cache_clear()` to re-arm).

**3.7 — 92 redundant `str()` wrappers removed.** See the decision below.

## Decisions worth a second reader

**3.5: all eight strategy tests drive cleanly, so none was deleted.** Before
wiring anything I drove all eight payloads through a live `PipeBlockerHandler`
with this project's real config: every one DENIES, and both declared patterns
(`Pipe to tail/head`, `expensive`) appear in the reason. Deleting would have
discarded eight real probes for no reason.

Their `echo "<command> …"` shape appears to contradict the handler's own
comment saying never to use `echo` — but that comment is about `echo` as the
PRODUCER. Here the truncation sits inside a quoted ARGUMENT, so the producer
classified is the command named in that string, and a hook failing open merely
prints text. The comment now says so explicitly, since the aggregated tests
would otherwise read as violating it.

Aggregation goes through a new public `strategies()` accessor on the pipe
registry rather than reaching into `_strategies` (which `qa_suppression` still
does), and iterates the ACTIVE strategies, so a project that filtered the
registry by language is not handed playbook blocks for a strategy its config
switched off.

**3.7: scope widened past strategy files, deliberately.** The task named
strategy files. The identical wrapper also sat in nine handler modules
(`plan_workflow`, `sensitive_content`, `project_containment`,
`validate_instruction_content` among them). The finding's stated harm is that
the wrapper tells a reader `scratch_path` returns a `Path`; that harm is
identical in a handler, and fixing only the strategies leaves the next
consistency sweep to rediscover the rest. Total: 87 single-line plus 5 wrapped
occurrences across 70 files.

**3.7: done without sub-agents, because this agent has no `Task` tool.** The
task offered parallel Haiku sub-agents with the `Edit` tool; that route was
not available. I used a paren-MATCHING script
(`untracked/scratch/drop_str_wrapper.py`) rather than a regex: a regex cannot
know where `str(` closes once the argument list carries parentheses of its
own, which is exactly the failure mode the sed ban exists for. The script
walks characters, tracks nesting and string literals, and refuses to write any
file whose result stops parsing. The five multi-line cases were done by hand
with `Edit`.

Verified rather than trusted: every one of the 104 removed lines in the diff
was read back and belongs to the wrapper removal; the only non-`scratch_path`
added lines are two blank lines; mypy is clean; and the generated playbook is
**byte-identical** across the edit.

## Verification

`./scripts/qa/llm_qa.py all` from the worktree root: **22/26 PASSED, 4/26
FAILED**, coverage 95.3%.

| Check                                              | Result                                          |
| -------------------------------------------------- | ----------------------------------------------- |
| `llm_qa.py` overall                                | 22/26, coverage 95.3%                           |
| format (black) / lint (ruff) / type_check (mypy)   | 0 / 0 / 0                                       |
| magic_values, security, semgrep, sensitive_content | 0 violations each                               |
| doc_truth, doc_snippets, handler_reference         | 0 violations each                               |
| repo_hygiene, git_history, british_english         | 0 violations each                               |
| project_handlers                                   | 87 passed, 0 failed                             |
| `pytest tests/unit tests/integration`              | 20828 passed, 4 failed                          |
| `pytest tests/acceptance` (daemon up)              | 75 passed, 11 skipped, 4 failed                 |
| `bin/hooks-daemon generate-playbook --format json` | exit 0, 312 blocks                              |
| `PipeBlockerHandler` playbook blocks               | 10 -> 18, every one carrying a payload          |
| `test_secret_file_matching.py` module runtime      | 16.83 s (subset, before) -> 0.99 s (all, after) |

**The four QA failures are worktree-environment artefacts, and Phase 3 changed
no code on any of their paths.** `git diff <branch-point> --name-only` over
`handlers/stop/`, `handlers/subagent_stop/`, `handlers/session_start/`,
`core/`, `daemon/` and `.claude/` returns **nothing**. Two distinct causes:

**Cause A — the worktree lives under an `untracked/` path segment.** Both QA
audits exclude any path containing that segment, and these worktrees are at
`/workspace/untracked/worktrees/…`, so every file in the repo is excluded.

- `capture_corruption` collects zero shell files and reports NO OUTPUT (its
  unit test trips the matching vacuity guard).
- `error_hiding` reports **172 violations, every one of rule
  `stale-exclusion`** and **zero** actual error-hiding findings. That
  breakdown is the proof: the audit found nothing to exclude, so all 177
  declared exclusions read as stale — including entries for files nobody in
  this plan has touched (`scripts/upgrade.sh`, `plugins/loader.py`).

**Cause B — the deployed hook wrapper cannot resolve its venv.** It looks for
`.claude/hooks-daemon/scripts/lib/resolve_venv.sh`, which does not exist in
self-install mode (`.claude/hooks-daemon/` holds only `untracked/` in the main
checkout too). The wrapper then returns a canned
`{"decision": "block", "reason": "Hooks daemon not installed …"}`.

- `tests` — 10 acceptance errors, all "Daemon not running". I started a daemon
  for this worktree (it has its own socket, `cmd_stop` kills only by this
  worktree's pid file, so the main daemon was never at risk) and they dropped
  to **75 passed, 11 skipped, 4 failed** — the 4 being the wrapper cases above.
- `smoke_test` — `stop_loop_guard` expects not-block and gets the canned
  block. Its two sibling probes expect a block and so pass regardless.

I did not attempt to fix Cause B: it is the deployed hook wrappers, which is
**Phase 5 Task 5.1's territory**, and repairing the deployment from here would
collide with that phase.

Fully green is therefore not reachable inside this worktree without either
relocating the worktrees out from under `untracked/` or deploying the hook
wrapper library into them. Both are environment decisions above this phase.

## For the coordinator

1. **`CLAUDE/UPGRADES/UNRELEASED/release-notes/02-lint-temp-dir-and-bracket-range-cost.md`**
   covers Phase 3's user-visible changes (the lint temp-directory fix, the
   `secret_file_guard` cost fix, the eight extra playbook blocks). The `NN`
   prefix is `02` because that was next in this worktree; if another phase also
   picked `02`, renumber on merge.
2. **The worktrees are missing the `untracked/venv` symlink** `llm_qa.py`
   hardcodes at line 30. The main checkout has it; the worktrees do not, so
   `llm_qa.py all` dies with `FileNotFoundError` before running any tool. I
   created it locally inside gitignored `untracked/`. The other phase agents
   will need the same.
3. **The interpreter named in the phase briefs does not work for pytest.**
   `untracked/venv-workspace_untracked_worktrees_worktr-2ab4-…/bin/python -m pytest` reports "No module named pytest" despite a `pytest` binary being
   present in that venv. `.venv` in the worktree is the one that works and is
   what ran the full suite.
4. **Nothing here touches Phase 5's territory** (the deployed hook wrappers),
   so this branch can merge before or after it.
