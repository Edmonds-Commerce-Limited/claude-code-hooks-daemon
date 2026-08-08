# Plan 00200: QA Gate Integrity and Dogfooding False Positives

**Status**: In Progress
**Created**: 2026-08-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Two defect classes found while auditing this repo for external presentation. Both are dogfooding
failures in the strict sense: each was hit during ordinary development work in this repo, and
each affects users too.

The first is a **QA gate that reports PASSED while checking nothing**. `scripts/qa/run_lint.sh`
records `total_files_checked: 0, total_violations: 0, passed: true` while ruff over the same
scope reports 47 violations. This defeats a gate that `CLAUDE.md` and `RELEASING.md` both
declare NON-NEGOTIABLE and blocking, and it is itself an instance of the error-hiding pattern
this project ships a blocking handler and a dedicated auditor to prevent.

The second is a set of **handler false positives** that block legitimate, safe commands. Each
costs an agent a turn and teaches it to distrust the guardrail — which is the more expensive
long-term cost.

## Goals

- `run_lint.sh` reports the truth, and cannot silently report zero again
- The same latent failure removed from every sibling QA script sharing the shape
- The 47 hidden lint violations surfaced and resolved
- Four handler false positives fixed, each with a regression test
- Every fix carries a test that fails before it and passes after

## Non-Goals

- Widening lint scope beyond `pyproject.toml`'s declared `src = ["src", "tests"]`. Not linting
  helper scripts is a deliberate project decision, not a defect.
- Rewriting the QA runner architecture. Fix the defects; do not redesign.

## Context & Background

### Defect 1 — the lint gate false pass

Three things compose:

1. `scripts/venv-include.bash:81` — `ensure_venv()` writes its success banner to **stdout**:
   `echo -e "${GREEN}✓${NC} Venv exists: ${VENV_DIR}"`. Its own error branches at `:91-95`
   correctly use `>&2`, so the inconsistency sits inside one function.
2. `scripts/venv-include.bash:159-173` — `venv_tool()` calls `ensure_venv` on **every**
   invocation, so that banner precedes every tool's output.
3. `scripts/qa/run_lint.sh:35` — redirects stdout into the file it then parses as JSON:
   `... --output-format=json > "${OUTPUT_FILE}.raw" 2>&1`. The raw file therefore begins with an
   ANSI venv banner and `json.loads` fails.

`scripts/qa/run_lint.sh:55-57` then converts that failure into a pass:

```python
    except json.JSONDecodeError:
        # Empty or invalid JSON means no violations
        ruff_output = []
```

`:82` sets `"passed": len(violations) == 0`, so the script exits 0.

`2>&1` alone is not the root cause — the banner is on **stdout**, so removing `2>&1` does not
fix it. Both the banner destination and the swallow must be corrected.

### Scope of the false pass — verified, and narrower than first assumed

Each gate's recorded artifact measured against ground truth:

| Gate         | Recorded                       | Ground truth       | Verdict                    |
| ------------ | ------------------------------ | ------------------ | -------------------------- |
| lint         | `files_checked: 0`, passed     | ruff: **47 found** | **BROKEN**                 |
| security     | `files_checked: 513`, 0 issues | bandit: 0          | Honest                     |
| type_check   | `files_checked: 0`, passed     | mypy: 0 errors     | Honest (count is cosmetic) |
| dependencies | 0 issues, passed               | —                  | Honest                     |
| format       | 0 violations, passed           | black: clean       | Honest                     |

The surviving gates survive because their tool writes JSON **to a file** via a flag
(`bandit -o`, `deptry --json-output`) rather than to stdout. Only ruff streams JSON to stdout,
so only lint is corrupted. That distinction is accidental, not designed — which is why the
latent cases below matter.

### Latent, not yet firing

The same swallow exists in three more scripts and would produce the same false pass the moment
their tool emitted anything non-JSON: `run_dependency_check.sh:74`, `run_security_check.sh:56`,
`run_smoke_test.sh:150`.

Four further echoes in `venv-include.bash` also write diagnostics to stdout and should not:
`:109`, `:113`, `:137`, `:168`.

`scripts/qa/run_capture_corruption_check.sh` exists precisely to catch stdout-capture corruption
and did not catch this. Worth understanding why.

### Defect 2 — handler false positives observed in this session

| Handler                         | Blocked command                             | Why it is wrong                                                                                                                               |
| ------------------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `EnforceLlmQaHandler` (project) | `cat scripts/qa/run_all.sh`                 | Matches the filename anywhere in the command. `cat` inspects, it does not execute. The block message cites output volume, which cannot apply. |
| `destructive_git`               | `git tag -f v1.0.0 <sha>` (scratch fixture) | Reported as "git push --force" with no push present. `-f` is matched too broadly.                                                             |
| `pipe_blocker`                  | `git commit` with a multi-line `-m` body    | Parsed prose inside the message as shell; suggested whitelisting `^under\b`. Message bodies are not commands.                                 |
| `lsp_enforcement`               | `grep -n "hook_input" <one named file>`     | Treated a string search scoped to a single file as a project-wide symbol lookup. LSP cannot answer "where does this literal appear here".     |

## Tasks

### Phase 1: Lint gate integrity

- [x] ✅ **Task 1.1**: Regression test `tests/integration/test_qa_lint_gate_integrity.py` — three
  tests: `ensure_venv` writes nothing to stdout; the gate's own embedded parser (extracted from
  `run_lint.sh` by regex, so it cannot drift) fails non-zero on a banner-corrupted capture; and
  a control asserting it still reports violations from clean JSON, so a parser that failed
  unconditionally could not satisfy the suite. Confirmed RED (2 failed, control passed).
  Deliberately does NOT invoke `run_lint.sh` end to end — it runs `ruff check --fix`, which
  would rewrite the working tree as a side effect of running the test suite.
- [x] ✅ **Task 1.2**: Moved `ensure_venv`'s success banner to stderr (`venv-include.bash:81`)
  and the sibling echoes at `:109`, `:113`, `:137`, `:168`. Verified this `ensure_venv` is never
  `$(...)`-captured (per the `capture-audit` comment at `:76-78`); the captured variant in
  `scripts/install/venv.sh` is untouched.
- [x] ✅ **Task 1.3**: Removed `2>&1` from `run_lint.sh:35`.
- [x] ✅ **Task 1.4**: Replaced the `JSONDecodeError` swallow with a hard failure printing the
  parse error and the first 200 bytes of the corrupted capture, then `sys.exit(1)`.
- [x] ✅ **Task 1.5**: Same treatment for `run_dependency_check.sh:74`,
  `run_security_check.sh:56`, `run_smoke_test.sh:150` — plus a 4th the original list missed,
  `run_shell_check.sh`. Delivered by the Phase 5 agent's widened `audit_error_hiding.py` triage
  as a natural side effect, and shipped in `24b2e918`. This is the DBF principle paying out
  literally: nobody hand-swept for the sibling swallows; widening the *guard* surfaced all four
  and one the humans had not listed. See JOURNAL 09:05/09:34.
- [x] ✅ **Task 1.6**: Root cause: the auditor only recognised `$(...)`/backtick capture as risky
  stdout consumption, with no regex for a `cmd > file` redirect — exactly the shape that broke
  `run_lint.sh`. Extended `audit_capture_corruption.py` with redirect-consumption detection +
  bare-call-graph propagation (zero-tolerance, no terminal-position exemption); fixed two real
  bugs surfaced while building it (a cross-file name-collision false positive, and an
  over-broad function-level-marker suppression that was hiding a genuine still-shipping latent
  bug at `venv-include.bash:106`, now fixed). Verified against the actual pre-fix historical
  files, not just synthetic fixtures. Full analysis in JOURNAL 09:34.

### Phase 2: The hidden violations

With the gate repaired it reports the truth: `total_files_checked: 27, total_violations: 49, passed: false`, exit 1. (49 rather than the 47 first measured — this
plan's own two new test files contribute the difference.)

- [x] ✅ **Task 2.1**: Enumerated. `ruff --fix` auto-fixes **none** of them — the earlier
  "11 auto-fixable" estimate did not survive contact. All 49 need manual work, across 27 files:

  | Rules                                | Count | Nature                                               |
  | ------------------------------------ | ----- | ---------------------------------------------------- |
  | `PTH211/105/101/118/116/115/110/103` | 28    | `os.path` → `pathlib` migrations                     |
  | `UP042`                              | 5     | `class X(str, Enum)` → `StrEnum`                     |
  | `RUF002/001/003`                     | 7     | Ambiguous unicode in docstrings/strings              |
  | `RUF012`                             | 3     | Mutable class attribute needs `ClassVar`             |
  | `SIM110`                             | 2     | Loop replaceable by `any()`                          |
  | `RUF059/022/005`                     | 4     | Unused unpacked var; unsorted `__all__`; list concat |

- [x] ✅ **Task 2.2**: The 28 `PTH*` pathlib migrations, across 11 files (6 src, 5 test). The one
  subtlety worth keeping here: a test monkeypatching `settings_repair.os.replace` had to move to
  patching `Path.replace`, while two sibling tests needed no change because `Path.replace()`
  calls `os.replace()` via the same shared module object.

- [x] ✅ **Task 2.3**: The remaining 21 (`UP042`, `RUF001/002/003/005/012/022/059`, `SIM110`).
  The one that mattered: `RUF001` flagged an EN DASH inside a **load-bearing** regex character
  class, so the proper fix was extracting it into a `_STATUS_SEP_CHARS` constant built from
  escapes — naming the ambiguous characters in source rather than suppressing or changing
  semantics. **No `noqa` anywhere**; every fix is a real code change.

  Full per-file detail for both tasks is relocated to `JOURNAL/`.

### Phase 3: Handler false positives

- [x] ✅ **Task 3.1**: `EnforceLlmQaHandler` — match invocation, not mention. Regression tests
  for `cat` / `less` / `grep` / Read against the path.

- [x] ✅ **Task 3.2**: `destructive_git` — already correctly scoped (verified, not weakened);
  added a permanent regression test pinning `git tag -f` plus a guardrail that a real forced
  push still blocks.

- [x] ✅ **Task 3.3**: `pipe_blocker` — ignore `-m` / `-F` message bodies when parsing.

- [x] ✅ **Task 3.4**: `lsp_enforcement` — do not redirect a grep already scoped to one named
  file.

- [x] ✅ **Task 3.5**: `plan_qa_commit_gate` — `same-commit-plan-doc` fires a false positive on
  the `git commit <pathspec>` form. That form commits unstaged working-tree changes for the
  named paths, but the check inspects only the staged index, so it advises "does not update its
  PLAN.md" on a commit that demonstrably does. Reproduced on `fad60fa6`, whose `--stat` shows
  `PLAN.md` present. Resolve the pathspec arguments against the working tree, not just the index.

- [x] ✅ **Task 3.6**: Audited every handler resolving an invoked command from a Bash string.
  Only **two** segment at all — `pipe_blocker` and the project's `enforce_llm_qa` (verified by
  search; the other first-word uses are message-builders that cannot misfire). Found three more
  defects in `pipe_blocker`: newline missing from the chain separators and a non-quote-aware
  chain split (both false **positives**), and a quote scanner blind to the backslash — a false
  **negative** that let an escaped quote hide a chain separator, so an expensive producer
  inherited a whitelisted one and the handler was bypassed outright. That last one is the
  audit's real yield. Delivered in `a92d2931`, `fc65f8cf`; full narrative in `JOURNAL/`.

- [x] ✅ **Task 3.7**: Consolidated both scanners into `utils/shell_segmentation.split_unquoted`
  (17 tests, both production bypass shapes pinned). This was initially deferred as a "design
  decision"; probing showed that was wrong twice over. The boundary objection was weak — project
  handlers already import `core`, `constants.timeout` and `constants.tags`, and `utils/` is an
  established 20-module package. And it was never tidiness: the two scanners held **opposite**
  halves of the escape rule and each produced the *same* bypass. `enforce_llm_qa` escaped inside
  single quotes (where bash treats `\` as literal), so a trailing backslash in a single-quoted
  argument swallowed the closing quote, nothing split, and `run_all.sh` rode through on an
  allowlisted leading word — **still live until this task**. Delivered in `5b8eb887`.

A sixth instance surfaced alongside Task 6.4 (below): `plan_number_helper` blocked a `find`
piped to `wc -l` (a plan *count* for a statistics line) as if it were number *discovery* —
fixed the same session; see `JOURNAL/`.

### Phase 4: Verification

- [x] ✅ **Task 4.1**: Full QA green — **19/19, 11,105 tests, 0 failed, coverage 95.3%**, with
  `lint` genuinely reporting a non-zero file count rather than the false pass it began as.
- [x] ✅ **Task 4.2**: Daemon restart RUNNING, verified after every handler change (the fixes are
  invisible until restart, which is this repo's most common dogfooding failure).
- [x] ✅ **Task 4.3**: Done via Task 6.2's `qa-check-count-hardcoded` rule — the hardcoded counts
  in `CLAUDE.md`, `RELEASING.md` and `README.md` were replaced with "every check", so the runner
  is the single source of truth and the number cannot drift again. Verified: the sole surviving
  mention of "10" is the sentence *explaining* the historical drift, and the rule reports 0
  violations. Removing the count beat correcting it, exactly as the task proposed.

### Phase 5: The error-hiding guard does not guard the guards

The Phase 1 swallow was textbook error hiding in a repo shipping **two** defences against
exactly that, and neither fired. Root cause in brief — full analysis in `JOURNAL/`:

- `audit_error_hiding.py:298-299` scans `src/` only, commented *"production code only"*, so the
  QA scripts that **implement the gates** are exempt from the gate. `:182` globs `*.py` only,
  and the swallow lived in Python inside a bash heredoc — invisible twice over.
- `error_hiding_blocker` + `shell_strategy` do know the shell patterns, but fire only on
  **Write/Edit**. Nothing sweeps what is already on disk.

Blind-spot inventory: 77 `2>/dev/null`, 6 `|| true`, 12 broad `except` in `scripts/*.py`, 2
confirmed swallows (`handler_status.py:74`, `debug_info.py:330`). **Not a defect count** — many
`2>/dev/null` uses are legitimate `command -v` probes. Triage required; blind removal breaks
things.

- [x] ✅ **Task 5.1**: Widened `audit_error_hiding.py` beyond `src/` via named constants
  `AUDITED_DIRECTORIES = ("src", "scripts")` and `AUDITED_ROOT_FILES` (`install.py`, `daemon.sh`,
  `init.sh`, `install.sh`, root `test_*.sh`).
- [x] ✅ **Task 5.2**: Added `extract_heredoc_python_blocks()` / `audit_heredoc_python()` — finds
  python/python3/`${VENV_PYTHON}`-style heredocs in `.sh` files, `ast.parse`s the body, offsets
  line numbers via `ast.increment_lineno` so violations point at the real file:line. Also added a
  third rule, `silent-fallback` (single-statement `except X: <bare assign>`) — the pre-fix
  visitor had no rule matching the run_lint.sh swallow's shape, so scope alone wasn't enough.
- [x] ✅ **Task 5.3**: Added `audit_shell_patterns()`, reusing `ShellErrorHidingStrategy.patterns`
  directly (no reimplementation).
- [x] ✅ **Task 5.4**: Triaged 61 surfaced findings: ~53 legitimate (if-checked probes, documented
  fallback contracts) got narrow function/line-based exclusions in `error_hiding_exclusions.json`;
  8 genuine swallows fixed (see Task 5.5 + `daemon/project_handler_health.py`,
  `daemon/cli.py::cmd_validate_project_handlers`/`cmd_test_project_handlers`,
  `init.sh::start_daemon`'s discarded launcher diagnostics).
- [x] ✅ **Task 5.5**: Fixed the two confirmed swallows (`handler_status.py::_detect_self_install_mode`,
  `debug_info.py` process-details block) plus the same shape found by the widened audit in
  `run_dependency_check.sh`, `run_security_check.sh`, `run_shell_check.sh` (not in the original
  list), and `run_smoke_test.sh` — all four sibling QA scripts now hard-fail with a diagnostic
  instead of silently defaulting on unparseable capture, matching the `fad60fa6` `run_lint.sh` fix.
- [x] ✅ **Task 5.6**: `run_all.sh` already invoked `audit_error_hiding.py --json`, so the widened
  scope is enforced automatically; added `TestAuditedRootsCannotSilentlyNarrow` asserting
  `"scripts" in AUDITED_DIRECTORIES`. Centrepiece regression:
  `TestPreFixRunLintFixtureIsCaught` points the fixed auditor at the exact pre-fix
  `run_lint.sh` content (`tests/fixtures/error_hiding/pre_fix_run_lint.sh`, recovered via
  `git show fad60fa6^:...`) and requires it to flag the swallow.

### Phase 6: DBF gap analysis — every finding mapped to the guard that should have caught it

Governing principle (now recorded as `CLAUDE.md` Core Standard 15): **Defence Before Fix.** A
defect is a symptom; the bug worth fixing is the blind or missing guard. Fixing instances by
hand leaves the guard blind and the class recurs.

Applying that to the presentation-quality audit findings — where a defence already exists, the
fix is legitimate backlog; where the cell says **NONE**, the defence is the actual work.

| Finding                                                           | Guard that should have caught it      | State                                                  |
| ----------------------------------------------------------------- | ------------------------------------- | ------------------------------------------------------ |
| Lint gate blind (47 hidden violations)                            | Gate-integrity test                   | **Built** (`test_qa_lint_gate_integrity.py`, Phase 1)  |
| Error hiding in `scripts/`                                        | `audit_error_hiding.py`               | **Blind** — being fixed (Phase 5)                      |
| Tracked absolute/dangling symlinks                                | Symlink-hygiene test                  | **Built** (`test_repo_symlink_hygiene.py`, Plan 00198) |
| Employer/client identifiers in source                             | `sensitive_content` handler + QA gate | **Being built** (Plan 00201)                           |
| Journal written to wrong day-file                                 | `journal-dayfile-is-today`            | **Built** (Plan 00197)                                 |
| Plan-tree drift                                                   | plan QA (edit/commit/sweep)           | **Exists and works**                                   |
| `coverage.json` (1.4 MB artifact) tracked                         | Tracked-build-artifact check          | **NONE**                                               |
| README describes 2 handlers as doing the OPPOSITE of what they do | Doc-vs-generated-truth check          | **NONE**                                               |
| `CLAUDE.md` claims "10 QA checks"; `run_all.sh` runs 13           | Same                                  | **NONE**                                               |
| 4 stray root `test_*.sh`, `settings.json.bak`                     | Repo-hygiene check                    | **NONE**                                               |
| Handler false positives (6 found)                                 | Negative-case acceptance tests        | **Built** (Task 6.4)                                   |

The four **NONE** rows are the remaining defence work. Note the README one is unusually cheap to
close: `.claude/HOOKS-DAEMON.md` is already **generated from live config**, so it is trustworthy
ground truth to diff prose claims against — the data exists, nothing consumes it.

- [x] ✅ **Task 6.1**: Tracked-build-artifact rule, in `scripts/qa/check_repo_hygiene.py`
  (merged with 6.3 — one `git ls-files` scan, two rule families; see JOURNAL). Surfaced and
  fixed `coverage.json` (1.4 MB) and `.claude/settings.json.bak`; `.gitignore` now covers both
  plus the daemon's own runtime `.bak.*` shape.

- [x] ✅ **Task 6.2**: `scripts/qa/check_doc_truth.py` — four rules against generated truth
  (`handler-ref-unknown`, `handler-claim-mismatch`, `handler-count-drift`,
  `qa-check-count-hardcoded`). Surfaced 3 hardcoded QA counts (README, `CLAUDE.md`,
  `RELEASING.md`), all replaced with "every check". Hand-audit of the 15 README bullets found
  **5** wrong descriptions, not the 2 reported; all fixed and each bullet now names its handler
  key so the claim rule engages.

- [x] ✅ **Task 6.3**: Root-test-script rule (same script as 6.1). Deleted the four stray root
  `test_*.sh`; no coverage lost — `test_forwarder_jq_free.py:284` already supersedes the
  control-char case.

- [x] ✅ **Task 6.4**: Require a **negative** acceptance case per blocking handler. Built
  `find_deny_capable_handlers_without_allow_case()` (`daemon/playbook_generator.py`) plus a
  dated, shrink-only allowlist test (`tests/integration/test_acceptance_negative_case_requirement.py`)
  run against the real production handler set (library + project). All six false positives
  fixed with a pinned regression test each; 16 pre-existing library handlers remain on the
  allowlist as tracked, deferred work — see `JOURNAL/` for the full inventory and rationale.

- [ ] ⬜ **Task 6.5**: Concurrent-agent isolation advisory (**the upstream fix**). Four agents
  were run in one `/workspace` checkout; the shared `.git/index` produced three incidents
  (logged in `JOURNAL/`) where staged work was absorbed or lost. The proximate cause is that
  bare `git commit` commits the whole index, but **the real defect was dispatching concurrent
  writers into a shared tree at all** — this repo already ships a `worktree_create` handler that
  makes isolation a one-flag decision.

  Only one of the four agents genuinely needed the shared tree: daemon-restart verification and
  `dummy-client-repo.sh` client-mode testing are anchored to the project root. The other three
  (plan authoring, lint fixes, a QA script) were isolatable and were not isolated. A constraint
  binding one agent was applied to four.

  The daemon already tracks live threads (`handlers/status_line/thread_registry.py`,
  `multithread_indicator.py`), so it can advise at dispatch time: *"N agents already active in
  this checkout — use `isolation: worktree` unless this agent needs live daemon verification."*
  Advisory, not blocking; single-agent sessions unaffected. A narrower fallback (warn on bare
  `git commit` while >1 thread is live) is worth keeping as a second layer, since pathspec
  scoping protects the committer but **not** an agent whose staged work a bare-committing peer
  absorbs — a process rule only works if every writer follows it, which is the argument for a
  guard.

Task 6.4 is the highest-leverage item here: it converts a recurring class into a structural
requirement rather than five individual fixes. Task 6.5 is the most *novel* — a defect class
created by the agent-orchestration model itself, which no single-developer tooling would surface.

## Technical Decisions

### Decision 1: Fail loudly on unparseable tool output

**Context**: The swallow was presumably written to tolerate ruff's empty output on a clean run.
**Options considered**: (a) keep swallowing but require non-empty output; (b) fail hard on any
parse error.
**Decision**: (b). Empty output is already handled by the `st_size > 0` guard at `:49`. Anything
non-empty and unparseable is a defect. A quality gate that cannot distinguish "clean" from
"broken" is worse than no gate, because it manufactures false confidence.
**Date**: 2026-08-07

### Decision 2: Fix the banner at source, not per-caller

**Context**: The banner could be suppressed in `run_lint.sh` alone.
**Decision**: Fix `venv-include.bash`. Diagnostic chatter on stdout is wrong for every caller;
lint merely happened to be the one parsing stdout as JSON. A per-caller fix leaves the trap
armed for the next script that captures stdout.
**Date**: 2026-08-07

## Success Criteria

- [ ] `run_lint.sh` reports a non-zero `total_files_checked` and the true violation count
- [ ] A deliberately-introduced violation makes the gate fail
- [ ] Unparseable tool output fails the gate rather than passing it
- [ ] 0 ruff violations in the declared scope
- [ ] Four false positives fixed, each with a regression test
- [ ] Full QA green, daemon RUNNING

## Risks & Mitigations

| Risk                                                     | Impact | Probability | Mitigation                                                                              |
| -------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------- |
| Moving echoes to stderr breaks a caller capturing stdout | High   | Low         | `run_capture_corruption_check.sh` exists for this; run it plus full QA                  |
| The 47 violations include genuine behaviour changes      | Medium | Medium      | Review each auto-fix diff; do not bulk-accept                                           |
| Relaxing `destructive_git` weakens a safety handler      | High   | Low         | Narrow only the `-f` match; keep every real force-push blocked, with tests asserting so |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only. Narrative goes in JOURNAL/. -->

- Plan created; lint-gate false pass reproduced and root-caused
- Task 6.4 (negative-case requirement) + six handler false-positive fixes, at
  `96646410`, `58b64c64`, `70c8d333`, `b2e819dd`, `9d276773` — **all verified
  present in `main`** (they were authored on a worktree branch and the earlier
  "pending merge" note here was stale)
- Task 3.6 sibling audit + the three `pipe_blocker` segmentation defects it
  found, at `a92d2931` and `fc65f8cf`. Phase 4 verified and closed at the same
  point: QA 19/19, 11,105 tests, coverage 95.3%, daemon RUNNING
