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
- [ ] ⬜ **Task 1.5**: Same treatment for `run_dependency_check.sh:74`,
  `run_security_check.sh:56`, `run_smoke_test.sh:150`.
- [ ] ⬜ **Task 1.6**: Investigate why `run_capture_corruption_check.sh` missed this; extend it
  if it reasonably could have caught it.

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

- [ ] 🔄 **Task 2.2**: Fix the 28 `PTH*` pathlib migrations. Highest count, mechanical, but
  touches real I/O — verify tests after each file rather than in bulk.

- [ ] ⬜ **Task 2.3**: Fix the 21 remaining. No `noqa` — the `qa_suppression` handler blocks it,
  correctly.

### Phase 3: Handler false positives

- [ ] ⬜ **Task 3.1**: `EnforceLlmQaHandler` — match invocation, not mention. Regression tests
  for `cat` / `less` / `grep` / Read against the path.
- [ ] ⬜ **Task 3.2**: `destructive_git` — stop matching `-f` outside an actual force-push.
  Regression test for `git tag -f`; assert every real force-push still blocks.
- [ ] ⬜ **Task 3.3**: `pipe_blocker` — ignore `-m` / `-F` message bodies when parsing.
- [ ] ⬜ **Task 3.4**: `lsp_enforcement` — do not redirect a grep already scoped to one named
  file.
- [ ] ⬜ **Task 3.5**: `plan_qa_commit_gate` — `same-commit-plan-doc` fires a false positive on
  the `git commit <pathspec>` form. That form commits unstaged working-tree changes for the
  named paths, but the check inspects only the staged index, so it advises "does not update its
  PLAN.md" on a commit that demonstrably does. Reproduced on `fad60fa6`, whose `--stat` shows
  `PLAN.md` present. Resolve the pathspec arguments against the working tree, not just the index.
- [ ] ⬜ **Task 3.6**: Audit sibling handlers for the same mention-vs-invocation confusion.

### Phase 4: Verification

- [ ] ⬜ **Task 4.1**: Full QA green — with lint genuinely checking files this time.
- [ ] ⬜ **Task 4.2**: Daemon restart RUNNING.
- [ ] ⬜ **Task 4.3**: Correct `CLAUDE.md:45` and `CLAUDE/development/RELEASING.md` — both claim
  "ALL 10 checks" and name a "Smoke Test"; `run_all.sh` runs 13 and has no such check. Prefer
  removing the hardcoded count so it cannot drift again.

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
