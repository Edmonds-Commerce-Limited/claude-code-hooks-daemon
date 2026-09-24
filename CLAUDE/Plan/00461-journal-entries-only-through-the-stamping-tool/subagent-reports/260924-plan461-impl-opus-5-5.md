# Plan 00461 implementation report

Branch `worktree-plan-461-journal`. Phase 1 (T1.1–T1.4) is done and
committed. Nothing is pushed or merged, and Phase 2 is left to the
coordinator.

## Result

- **QA**: `QA: 36/36 PASSED` (tests 25779 passed, 0 failed, 23 skipped;
  coverage 95.1%). This was the full `llm_qa.py all` run after a
  worktree-daemon restart, with no commit during the run.

- **Live DENY** from the running worktree daemon. An Edit that appended
  `## 14:30 · finding` to this plan's journal, piped into the worktree's
  `.claude/hooks/pre-tool-use`, returned `deny`:

  ```
  BLOCKED [R-JOURNAL-HAND-WRITTEN-ENTRY]: a plan journal entry written by hand (Edit/Write/Bash into a JOURNAL/ day-file)
  ...
  Target: `CLAUDE/Plan/00461-journal-entries-only-through-the-stamping-tool/JOURNAL/00461-Journal-26-09-24.md`
  ...
         CLAUDE/Plan/mkplan.bash --journal 461 <category> untracked/scratch/journal-461-entry.md --title "short title"
  ```

  A `cat >> <journal> <<'EOF'` was also denied, and
  `CLAUDE/Plan/mkplan.bash --journal 461 …` was allowed. This session's own
  tool calls go to the MAIN daemon, which does not have the handler until
  the merge, so the probe was fed to the worktree daemon directly rather
  than performing a real hand append.

## What was built

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_journal_guard.py`
  is a new terminal PreToolUse handler at priority 31. It carries the
  PLANNING tag, so the registry injects the plan dir and `plan_qa`. It has
  one rule, `R-JOURNAL-HAND-WRITTEN-ENTRY`, and 100% line and branch
  coverage.
  - **Edit/Write**: denied when the would-be content has MORE entry headings
    than the file has now, or a Write creates a day-file. `Completed/` is
    included. A deletion-only Edit (for example removing conflict markers)
    is allowed.
  - **Bash**: reuses `core.utils.get_bash_write_targets` (redirects, tee,
    heredocs, cp/mv/install/dd). Two additions cover what a shlex token hides:
    interpreter one-liners (`python -c`, `perl -e`, `node -e`, `bash -c`,
    awk), judged by the day-file the program names plus a write signal in it;
    and in-place `-i` on sed/perl/ruby. A `git` stage's relocations are never
    judged, but a redirect riding on git is. `mkplan.bash` is never judged.
  - **Gate**: the plan workflow is on and `mkplan.bash` is deployed, which is
    plan_number_helper's condition. On top of that, the script must contain
    `--journal`, `_JOURNAL_TEMPLATE_.md` must be present, journalling must
    not be off, and `dir_name` must be the default `JOURNAL`, because
    `--journal` writes nowhere else.
- The entry-heading parser was duplicated in two checks. It is now
  `plan_qa.model.journal_entry_headings`, shared by both checks and the
  guard. `JOURNAL_CATEGORIES` is pinned by the existing category-sync test.
- `utils.path_predicates.read_text_or_reason` gained an `errors`
  passthrough. The guard reads with `"replace"`, so an undecodable byte
  can't blind it.
- `mkplan.bash --help` (both copies) prints the `--journal` usage, says it
  is the only way, and gives an example.
- Docs: `PlanJournalling.md` has a new "Appending an entry" section, and two
  statements the guard made false are corrected. `PlanWorkflow.core.md` has
  a "Journal entries" section and tells coordinators to put the pattern in
  briefs (N21 remedy 3). `_JOURNAL_TEMPLATE_.md` names the tool. Every doc
  pair is byte-identical with its shipped template. There is also a
  `HANDLER_REFERENCE.md` entry.
- Release note `UNRELEASED/release-notes/11-hand-written-journal-entries-are-now-denied.md`
  and `UNRELEASED/config-changes/v3.67.0.yaml` (`recommended: true`).
- Acceptance probes: DENY `echo '## 00:00 …' >> CLAUDE/Plan/99999-…/JOURNAL/…`,
  ALLOW `CLAUDE/Plan/mkplan.bash --journal 99999 action …`.

## Found and fixed

- When `--journal` opened a NEW day-file, it copied the template's seeded
  "plan scaffolded" entry into it, so every day-2 file falsely recorded a
  scaffolding. With `--journal` mandatory, that would hit every multi-day
  plan. Reproduced in a scratch repo, fixed under TDD in `run_journal_mode`
  (both copies).

## For the coordinator (not fixed here)

1. **Worktree daemon idles out during QA.** `idle_timeout_seconds: 600`, and
   a worktree session's hooks go to the main daemon, so any `llm_qa.py all`
   longer than 10 minutes in a worktree fails `smoke_test` with "Daemon not
   running". I worked around it with a bounded keep-alive that sent a Read
   event every two minutes. Worth a ledger entry.
2. **`plan_number_helper` resolves a relative `mkdir` against the workspace
   root, not the command's `cwd`.** It denied
   `mkdir mkj/CLAUDE/Plan/00007-probe` run from `untracked/scratch/` as a
   plan-folder creation.
3. `UNRELEASED/config-changes/v3.67.0.yaml` is a new file. Another plan
   drafting the same version would conflict at merge (add/add).
4. Phase 2 remains: merge `--no-ff`, restart the MAIN daemon, confirm the
   live deny there, and mark 00422 N21 remedied.

## Commits

`a79e7a97` handler and shared parser · `29685042` docs, `--help`, day-file
fix · `6f877772` read through `read_text_or_reason` · plus the commit that
adds this report.
