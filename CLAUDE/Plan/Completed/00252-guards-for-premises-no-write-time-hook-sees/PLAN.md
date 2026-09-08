# Plan 00252: guards for premises no write-time hook sees

**Status**: Complete
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Two defects found while executing Plans 00245/00248/00251 share one shape, and
it is the shape Core Standard 15's corollary names: **a guard that only fires at
write time does not cover what arrives by any other route.** In both cases the
matcher, the rule and the knowledge all existed — what was missing was a guard
positioned where the failure actually happens.

They are filed together because the argument for each is the same argument, and
because fixing one while leaving the other is how a "class" quietly becomes a
"recurrence". Either phase can ship independently.

## Verified findings

| ID  | Route the guard cannot see                       | Consequence                                          |
| --- | ------------------------------------------------ | ---------------------------------------------------- |
| A   | A test takes its git premise from ambient config | Red on a fresh runner, green locally — 7 occurrences |
| B   | A file arrives by `mv`, not `Write`/`Edit`       | A secret-list term reached a pushed commit           |

### A — the ambient-git-premise class, and its count

A test that needs a git repo takes its identity premise from the developer's
environment instead of establishing it. It passes locally and fails on a runner
— or worse, passes on both while asserting nothing.

| When                | Where                                 | Symptom                                |
| ------------------- | ------------------------------------- | -------------------------------------- |
| Plan 00245 Phase 3  | 6 files, ~41 tests                    | red on any fresh runner, green locally |
| Plan 00245 Task 3.4 | `test_git_sync_rewrite_detection` (3) | identity set on 3 of 4 repos           |
| Plan 00248          | `test_git_repo.py::…not_valid_utf8`   | `fatal: invalid object name 'HEAD'`    |

Seven distinct occurrences across two plans. Plan 00245 fixed six **by hand and
added no guard for the class** — exactly the DBF failure mode Core Standard 15
describes. The seventh landed in the commit that closed 00245.

**Remembering demonstrably cannot fix this.** The `tmp_git_repo` fixture in
`tests/conftest.py` does it correctly and its docstring names this precise defect
class. The seventh instance was written in the SAME commit that hardened that
fixture, 140 lines away in a file with its own local `_git_init`. The ambient
premise has to stop being *available*.

### B — no guard inspects STAGED CONTENT for secret-list terms

A field report was moved into a plan folder with `mv` (it came from `untracked/`,
so `git mv` refused it). One line named the reporting client's repo path, which
matched an entry in the secret word list. It reached a pushed commit.

Each of the three existing layers missed it for a different, specific reason:

1. **Write-time** (`sensitive_content`, PreToolUse) inspects `Write`/`Edit`
   content. The file arrived by `mv` — a Bash file move — so the handler never
   saw the content. **A rename is not a write.**
2. **Commit-time** (the same handler's Bash path) checks the git MESSAGE, tag
   names and branch names — not the staged blobs. Verified rather than assumed:
   `sensitive_content.py` references neither `diff --cached` nor staged content
   anywhere.
3. **Batch** (`scripts/qa/check_sensitive_content.py`) does scan the working tree
   and DID catch it — but only on the next full QA run, two commits and one push
   later.

So the hole is narrow and closeable, and every piece needed already exists: the
matcher, the word list, and a commit-gate handler that already reads the staged
tree (`plan_qa_commit_gate` → `plan-qa --check-staged`).

**The asymmetry is what makes this worth doing.** A term in the working tree is
one edit from clean. A term in a pushed commit needs a history rewrite — a human
decision with real cost. The guard is cheap exactly where the failure is
expensive.

## Goals

- A local test run has the same bare git environment as a CI runner, so the
  ambient-git-premise class cannot be written again.
- A `git commit` whose STAGED CONTENT carries a secret-list term is denied,
  converting a post-hoc detection into a prevention.
- Both guards are verified by reproducing the original failure against them, not
  only by unit tests.

## Non-Goals

- Adding a git identity to `.github/workflows/qa.yml`. See Decision 1 — this is
  the trap, not the fix.
- Rewriting history for the term already pushed. That is a human decision, is
  recorded as such, and is not this plan's work.
- Widening the secret-word-list disclosure rules. A term must still never appear
  in a deny reason, a log, or a capture; the staged-content check reports an
  index exactly as the existing checks do.

## Tasks

### Phase 1: Measure before choosing (finding A)

- [x] ✅ **Task 1.1**: Run the whole suite under a neutralised git environment
  (`GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_SYSTEM=/dev/null`, and with
  `GIT_AUTHOR_*`/`GIT_COMMITTER_*` unset) and record every failure
  (`772ef675`, Plan 00362 Task 2.6 — full unit and integration suites under
  the fixture: zero failures attributable to the neutralised config; the only
  errors were the tracked-doc guard catching an external `CLAUDE.md`
  regeneration, unrelated)
  - [x] ✅ This is the same invocation already used to prove the Plan 00248 fix
    RED and GREEN, so it is known to work; what is unknown is how many other
    tests depend on the ambient premise
  - [x] ✅ The result decides Phase 2's shape — do not choose the mechanism first
- [x] ✅ **Task 1.2**: Confirm no test legitimately reads global or system git
  config (a prior grep found zero matches for `config --global`,
  `GIT_CONFIG_GLOBAL` and `config … --system` under `tests/`; re-verify, since a
  single legitimate reader changes the design) (`772ef675` — re-verified: the
  only readers are the guard's own proof test)

### Phase 2: Remove the opportunity (finding A)

- [x] ✅ **Task 2.1**: Apply the neutralisation as an autouse session fixture in
  `tests/conftest.py`, unless Task 1.1 found a genuine dependency
  (`772ef675` — `hermetic_git_environment`: empty global/system config files
  under a session temp dir, `GIT_CONFIG_NOSYSTEM=1`, ambient
  `GIT_AUTHOR_*`/`GIT_COMMITTER_*` cleared and a fixed identity pinned so a
  commit still succeeds with the same author on every machine)
  - [x] ✅ Preferred over `scripts/qa/run_tests.sh` alone: a developer running
    `pytest` directly still gets the ambient premise there, and that is precisely
    how the seventh instance was written
- [x] ✅ **Task 2.2**: Prove the guard catches the class — revert one known
  instance and confirm it now fails LOCALLY, not only in CI (`772ef675` —
  `tests/unit/test_hermetic_git_environment.py` asserts `git config --get user.name` resolves to nothing and that no config value originates under
  `HOME`; without the fixture it prints the developer's name locally, which
  is the RED that was confirmed before the fixture landed)
- [x] ✅ **Task 2.3**: Consolidate `test_git_repo.py`'s local `_git_init` onto the
  shared fixture, as a complementary narrowing (`7b94bac3` — `_git_init`,
  `_give_identity` and `_commit_a_file` removed; every test takes `tmp_git_repo`,
  whose identity + committed `tracked.txt` is exactly what the helpers built; the
  one nested-repo test keeps a single inline `git init` because a repo INSIDE
  another is the one shape the fixture cannot give)
  - [x] ✅ Note for the record: `_git_init` PREDATES the fixture (`074b9de1`,
    Plan 00113) by roughly three months, so it is not a divergence from
    `tmp_git_repo` (`013b48e7`, Plan 00246) — the fixture is the later arrival
    and never displaced it. Treat this as complementary, never as the guard: it
    would not catch a test that used the fixture and then committed by hand

### Phase 3: Check staged content for secret terms (finding B)

Delivered by Plan 00362 Task 2.4 (commit recorded under Delivery below).

- [x] ✅ **Task 3.1**: RED — a `git commit` staging a file whose CONTENT carries a
  secret-list term is currently allowed
  (`TestStagedContentSurface` in `tests/unit/handlers/pre_tool_use/test_sensitive_content.py`)
- [x] ✅ **Task 3.2**: Extend the commit-time check from "message and metadata"
  to "message, metadata and staged blob contents"
  - [x] ✅ Reuse the existing matcher and word-list loader; a second copy of
    either would be the defect Plan 00251 spent a phase removing elsewhere
    (`sr.find_first_match_index` / `_secret_terms()` — no new matcher)
  - [x] ✅ Report only an index (`entry N of M`), never the term — in the deny
    reason, in logs, and in any capture (the deny names the staged PATH and
    the index; the added line is never echoed, and the log lines name paths only)
  - [x] ✅ Bound the work: `MAX_STAGED_FILE_BYTES` = 512 KiB of added lines per
    file and `MAX_STAGED_TOTAL_BYTES` = 4 MiB per commit; past either the file
    (or the rest of the commit) is stood down with a log line, never scanned
    partially. `--unified=0` keeps the diff to added lines; binary blobs print
    no added lines and are skipped inherently
- [x] ✅ **Task 3.3**: Verify against the ACTUAL sequence that failed — a file
  moved into place with `mv`, then staged, then committed — not only against a
  synthesised `Write` (the tests write the bytes with no tool call, `git add`,
  then dispatch `git commit`)
- [x] ✅ **Task 3.4**: Confirm the batch checker and the new commit gate agree on
  what matches, so a commit that passes cannot fail the next QA run (both call
  `secret_redaction.term_matches`, the single matching predicate)

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Full QA green, daemon restart RUNNING (full QA 26/26 on
  main after the Plan 00362 merges; daemon RUNNING)
- [x] ✅ **Task 4.2**: Client-mode verification for Phase 3 — it changes a
  blocking Bash handler, and a client repo's word list lives at a different path
  (verified on a `scripts/dummy-client-repo.sh` install with
  `secret_word_list_path: .claude/smoke-words.txt`: a file moved in with `mv`,
  staged and committed through the deployed `pre-tool-use` hook is denied
  naming only the path and `entry 1 of 1`; a clean commit returns `{}`)
- [x] ✅ **Task 4.3**: Record the `sensitive_content` behaviour change in the
  handler's `get_claude_md()` and `docs/guides/HANDLER_REFERENCE.md`, since a
  newly denied commit shape needs to be discoverable before it surprises
  someone. No `config-changes` entry: no option was added or changed, so the
  release-notes callout (`UNRELEASED/release-notes/23-secret-guard-covers-staged-content-and-gh-bodies.md`)
  is the upgrade-time surface

## Dependencies

- Follows: Plan 00245 (Complete) — Phase 1/2 close the class it fixed by hand.
- Follows: Plan 00248 (Complete) and Plan 00251 (Complete), during which the
  seventh instance and finding B were found.
- Related: Plan 00250 — also about a guard that could not fire, but a different
  one (acceptance gates skipping in CI for want of a socket).

## Technical Decisions

### Decision 1: never give CI a git identity

**Context**: the cheapest way to make these seven failures stop is one line in
`.github/workflows/qa.yml` setting `user.email` and `user.name`.

**Decision**: forbidden, and recorded here so it is not proposed again. CI
currently sets NO identity, and that is the ONLY reason any of the seven were
ever caught. Supplying one would turn every future instance green and make the
runner permanently blind to the class. The fix runs in the opposite direction:
make the LOCAL environment as bare as the runner's.

**Date**: 2026-08-17

### Decision 2: prevention at the commit, not detection in the sweep

**Context**: finding B was caught by the batch checker, so one option is "no
change — the sweep works".

**Decision**: not sufficient, because of where the two failures sit. The sweep
catches a term in the WORKING TREE, which is one edit from clean. It ran after
the push, and a term in a pushed commit needs a history rewrite — a human
decision with real cost. Only the commit gate is positioned to stop a push, so
that is where the guard belongs. The sweep stays as the backstop for terms that
arrive by routes no hook sees at all.

**Date**: 2026-08-17

## Success Criteria

- [x] The whole suite passes with ambient git configuration neutralised, and a
  reverted known instance now fails locally (`772ef675`)
- [x] A `git commit` staging content that carries a secret-list term is denied,
  naming only an index
- [x] The original `mv`-then-commit sequence is reproduced and blocked
- [x] No secret-list term appears in any deny reason, log or capture
- [x] QA green, daemon restart RUNNING, client-mode verified
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/23-secret-guard-covers-staged-content-and-gh-bodies.md`

## Risks & Mitigations

| Risk                                                                          | Impact | Probability | Mitigation                                                                                        |
| ----------------------------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------- |
| Neutralising git config breaks tests that legitimately need it                | Medium | Low         | Phase 1 measures before Phase 2 chooses; a prior grep found zero readers of global/system config  |
| Scanning staged blobs exceeds the hook budget on a large commit               | High   | Medium      | Task 3.2 requires deciding and recording a bound, rather than meeting it as a field timeout       |
| The new gate and the batch checker disagree, so a commit passes then fails QA | Medium | Medium      | Task 3.4 makes agreement an explicit acceptance condition, sharing one matcher                    |
| Someone "fixes" CI later by adding an identity                                | High   | Medium      | Decision 1 records the trap by name; Phase 2's local guard also makes the CI-only dependency moot |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.
- Phase 3 and Task 4.3 delivered by Plan 00362 Task 2.4: `6c9a6f6f`.
- Phases 1 and 2 delivered by Plan 00362 Task 2.6 (`772ef675`) and Task 2.3
  here (`7b94bac3`); verified by the full QA run after the Plan 00362 merges.
