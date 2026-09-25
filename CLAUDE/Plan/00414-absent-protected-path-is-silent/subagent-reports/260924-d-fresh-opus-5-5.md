# Delivery report: Plan 00414 (d-fresh, Opus 5.5)

Branch `worktree-d-fresh`, commit `7632d265`. Plan 00415 was delivered on the
same branch; see its own report.

## Reproduction

This worktree is a live instance of the defect. Its config names
`secret_word_list_path` explicitly, and `hooks-daemon secret-meta` reports
that path `"exists": false`. So `sensitive_content`'s word-list source is inert
here: the `sensitive_content` QA gate reports "0 terms". Before the change, the
SessionStart hygiene advisory said nothing about it.

## Rulings (recorded in PLAN.md beside each question)

1. Report "absent" only when the project's config names the protected path
   explicitly.
2. Report it once per config or content change, reusing the content-hash
   caching pattern.
3. Assumption recorded: 00414 is classed as a defect, because a silently inert
   guard is reported the same as a healthy one.

"Names explicitly" means one of two things, each only while that handler is
enabled: `sensitive_content`'s `secret_word_list_path` option, or an entry in
`secret_file_guard`'s `protected_paths` that is a path-shaped literal (no
`*`/`?`/`[`, and a `/` inside it). A bare file name matches that basename
anywhere in the tree, so it declares a pattern, not a path whose absence means
anything.

## Per-task outcomes

| Task                                     | Outcome                                                                                                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1.1 settle the questions                 | Done: the rulings above.                                                                                                                                                                                                                                                                                                                                                                               |
| 1.2 read how others decide when to speak | Done. `deployed_artefact_drift` speaks every session while drift lasts, keyed on presence. It has no once-only cache. `gitignore_safety_checker` keeps a content-hash JSON cache under the daemon's untracked dir. The once-only key reuses that shape as a plain-text sha256 (`secret_file_absence_told.sha256`).                                                                                     |
| 1.3 failing test first                   | Fixed. `tests/unit/handlers/session_start/test_secret_file_hygiene_checker.py::TestAbsentDeclaredPath` (16 tests) was confirmed RED before the implementation. The headline test is `test_declared_word_list_absent_is_reported_naming_the_inert_guard`, paired with `test_declared_word_list_present_and_healthy_is_silent`. The RED tests were not committed separately from the fix; see DBF below. |
| 1.4 implement, metadata only             | Fixed. `TestAbsentDeclaredPath::test_no_code_path_opens_a_protected_file` records every `open`/`io.open`/`os.open` during `handle()`, with one declared path present and one absent, and asserts neither is opened. Plan 00459 has since added one sanctioned in-daemon format read (`classify_at_rest`). The test stubs it, so any other open would show.                                             |

Success criteria 1 to 3 are met. I added a fourth, unticked criterion (full QA
over the merged batch plus CI). It is the coordinator's to tick. It also keeps
the header honest, because plan QA blocks an `In Progress` header over a fully
ticked body, and I was told not to flip the status.

## Behaviour

- It reports once, naming the path, the declaring option, and the consequence
  ("sensitive_content's secret word-list source is INERT until it exists", or
  for a guarded path "if the file lives under another name, that copy is
  unprotected").
- It speaks again when the findings change: a new declaration, a moved path,
  or a file lost again after being restored (`test_a_config_change_reports_again`,
  `test_a_presence_change_reports_again`).
- A dangling symlink counts as absent (`test_dangling_symlink_counts_as_absent`).
  This matters because the worktree seed links the list.
- A disabled declaring handler, an unconfigured default, a glob or a bare
  name: all silent.
- The check's own failures are said, never hidden. An unloadable config, or a
  told record that cannot be read or written, appears under "the
  absent-protected-path check did not run cleanly" every session it happens
  (`test_unloadable_config_is_said_not_hidden`,
  `test_unreadable_told_record_is_said_and_the_finding_told`,
  `test_unwritable_told_record_still_reports_and_says_it_will_repeat`). A
  failed record write still reports the finding, and it repeats next session,
  which is the safe direction.
- The same section appears in the non-git fallback and alongside existing
  findings.
- With nothing missing, the output is byte-identical to before: no
  declarations means an early return before any cache I/O.

## Live verification (worktree daemon)

Two SessionStart probes went through `.claude/hooks/session-start` after a
restart. The first carried the "a protected path the config names is ABSENT"
section naming the word list and "INERT until it exists". The second was
silent.

## Defence Before Fix

- **Class**: a guard whose input is missing goes inert, and nothing reports it,
  so inert and healthy look the same.
- **Detector**: no practical code-reading detector exists. The defect is a
  runtime property of which files exist in a checkout, not a code shape a rule
  can read. This is recorded as a toolchain gap and fixed conventionally. The
  handler itself is the runtime detector: it reads config and disk. Because no
  code detector existed, there was no red-before-fix detector commit.
- **Other instances found while working**, reported rather than fixed because
  they are outside this brief:
  - `utils/secret_redaction.py::_resolve_active_path` tests
    `isinstance(handler_cfg, dict)`. Config coerces every handler entry to
    `HandlerConfig`, so a configured `secret_word_list_path` is never read
    there, and payload-capture and log redaction always use the default list
    path. This repository is unaffected because its configured path equals the
    default. I sent this to team-lead during the run.

## Shared files and n466-guard-defects

- I did not touch `handlers/pre_tool_use/secret_file_guard.py` or
  `utils/secret_file_matching.py`. The hygiene checker only calls
  `resolve_configured_patterns`/`path_is_protected` read-only, and neither
  signature changed.
- n466-guard-defects replied after my commits (its branch HEAD `dd73b459`).
  It changed `utils/secret_file_matching.py` (private helpers only),
  `secret_file_guard.py`, `project_containment.py`, `utils/path_exclusion.py`
  and `constants/rule_ids.py`. None of those is in this branch. It confirmed
  that `resolve_configured_patterns()` and `path_is_protected()` are unchanged,
  and that it did not touch the hygiene checker or its test. The file lists
  are disjoint. This branch no longer adds entries to
  `scripts/qa/error_hiding_exclusions.json` (see below), so that file only
  has removals here.

## Files changed

- `src/claude_code_hooks_daemon/handlers/session_start/secret_file_hygiene_checker.py`
- `tests/unit/handlers/session_start/test_secret_file_hygiene_checker.py`. It
  gains an autouse fixture that keeps every test off the real project config
  and the real absence cache.
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py`
  (guidance sentence)
- `docs/guides/HANDLER_REFERENCE.md`, `.claude/hooks-daemon.yaml` (seed
  comment). Neither says "silently" inert any more.
- No QA exclusions. The first delivery exempted three sites (`_load_config`,
  `_read_absence_hash`, `_write_absence_hash`) in
  `scripts/qa/error_hiding_exclusions.json`. Team-lead rejected that, so those
  entries are gone (commit `f21ffa55`): `_load_config` raises, and the caller
  catches `OSError`/`ValueError` and reports it. The told-record read and
  write append a problem the advisory renders. `llm_qa.py error_hiding`
  passes with zero new entries.
- Release note 53, and a truth-change entry in
  `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.67.0.yaml` (topic
  `blocking-handlers`).

## QA run (targeted, per the wave rules)

`format lint type_check pyright magic_values error_hiding shell_check semgrep docs_qa plan_qa handler_reference british_english smoke_test fail_open_inventory sensitive_content` all passed. pytest passed for the
hygiene checker, `gitignore_safety_checker`, `sensitive_content` and the
release-staging tests. `repo_hygiene` reports 2 `plan-stats-arithmetic`
findings in `CLAUDE/Plan/README.md`. They are present on main, and I was told
not to edit that file.
