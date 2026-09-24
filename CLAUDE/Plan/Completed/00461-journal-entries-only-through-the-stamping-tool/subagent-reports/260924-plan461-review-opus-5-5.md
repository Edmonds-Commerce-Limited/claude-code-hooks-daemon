# Plan 00461 review: `plan_journal_guard` (R-JOURNAL-HAND-WRITTEN-ENTRY)

Reviewer: Opus 5.5 (read-only). Scope: `git diff main...6fc17f90` on branch
`worktree-plan-461-journal`. Paths below are relative to the worktree
`/workspace/untracked/worktrees/worktree-plan-461-journal/`.

**Method.** I read the diff, PLAN.md, the JOURNAL and the implementation report.
I ran only targeted pytest (230 passed across the guard, `plan_qa/test_model`,
`test_mkplan_journal`, `test_journal_category_sync` and `test_path_predicates`).
I also ran about 75 probe payloads through `PlanJournalGuardHandler.matches()`
against a temp plan tree (harness: `/workspace/untracked/scratch/rv461/probe_setup.py`),
and ran `mkplan.bash --journal` and `--help` end to end in a scratch git repo.
Every ALLOW/DENY verdict below is an observed result, not an inference.

**Counts: 1 blocker, 4 major, 10 minor.**

## Verified correct

- The Edit/Write surface denies `## 14:30 · …`, `## 14:30 - …` and `## 14:30 * …`.
  The regex does not need the middot, so swapping the separator does not evade it.
  It also denies a Write that replaces the file with more headings, a Write that
  creates a day-file (`Completed/` included), and a Write into an archived plan.
- The Bash surface denies `printf >>`, `echo | tee -a`, `tee`, `>|`, `&>>`,
  `exec 3>>`, `cp /tmp/x`, `cp` into `JOURNAL/`, `mv -t`, `dd of=`, `install`,
  `perl -pi`/`-i -pe`, in-place sed, `bash -c`/`sh -c` with a redirect,
  `env python3 -c`, and `../` from a subdirectory.
- No false denies for: `mkplan.bash --journal` by relative path, absolute path,
  `./mkplan.bash` from the plan dir, or `bash mkplan.bash`; `mkplan.bash "new-plan"`;
  a quoted heredoc that writes a body file which mentions a day-file; `git mv`,
  `git merge`, `git checkout --theirs <dayfile>`, `git show … > scratch`;
  `grep`/`tail`/`diff`/`cp dayfile scratch/`; a conflict-marker deletion Edit; a
  conflict block retyped in full with the same headings.
- `read_text_or_reason(errors=…)` is correct. It passes straight through to
  `read_text`, and both the strict default and `"replace"` are tested.
- The mkplan day-file template fix works. A day-2 file holds the preamble,
  including the UTC sentinel, and then only the requested entry. The formatting
  is clean.
- Template copies are byte-identical (`cmp`): `mkplan.bash`,
  `_JOURNAL_TEMPLATE_.md`, `PlanJournalling.md` and `core/PlanWorkflow.core.md`.
- `--help` prints the `--journal` usage (exit 0).
- The shared `journal_entry_headings` gives the same results as the two parsers it
  replaced, with one exception (m5). `max(…, key=minutes)` keeps the old
  first-of-equal behaviour.

## Blocker

### B1. Day-files inside a git worktree are not guarded, and that is where sub-agents journal

`src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_journal_guard.py:287`
(`if not path.is_relative_to(layout.plan_root): return None`). The docstring at
271-273 states this intent, and
`tests/unit/handlers/pre_tool_use/test_plan_journal_guard.py:248-255` pins it.

- **Scenario.** A sub-agent dispatched into
  `untracked/worktrees/<wt>/` sends its hooks to the MAIN daemon. The
  implementation report says so, and ledger N27 records it. That daemon's
  `plan_root` is `/workspace/CLAUDE/Plan`, and
  `/workspace/untracked/worktrees/<wt>/CLAUDE/Plan/…/JOURNAL/…` is not under it.
- **Probed, all ALLOW:**
  - an Edit appending `## 14:30 · finding` to a worktree day-file;
  - `echo '## 14:30' >> <rel dayfile>` with cwd set to the worktree;
  - the same with an absolute path.
- **Why it is a blocker.** Every plan in this session ran "Sub-Agent
  Orchestration (worktree, TDD)". The incident was "a coordinator and five
  sub-agents", so the guard misses most of the population it was built for.
  PLAN.md Goal 4 ("every session and sub-agent") is not met.
- **Fix.** Re-root through the existing SSoT
  `core/worktree_paths.effective_project_relative_path`, or match on
  `WORKTREE_DIR_PATTERNS`, as `markdown_organization` does. Take `plan_root`
  and the `_remedy_is_deployed` check from THAT checkout. Print that checkout's
  script and body path as absolute paths, or as `cd <wt> && CLAUDE/Plan/mkplan.bash …`.
  The docstring's worry ("the printed command would append to THIS checkout's
  plan") then no longer applies. Replace the "another checkout" test with two
  tests: a worktree day-file is DENIED and names the worktree's script, and a
  path outside the repo entirely is still allowed.

## Major

### M1. The Edit/Write surface counts one strict heading shape, so near-miss headings and untimed appends pass

The rule is at `plan_journal_guard.py:340`. The regex is
`plan_qa/model.py` `_JOURNAL_ENTRY_HEADING_RE = r"^## (\d{2}):(\d{2})\b"`.

- **Probed, all ALLOW as Edits appended to a day-file:**

  - `##  14:30` (two spaces), `##\t14:30`, `### 14:30`, ` ## 14:30`
    (leading space, which still renders as a heading);
  - `## 9:30`, `## [14:30]`, `## finding — no time`, `**14:30 · finding**`;
  - an Edit that opens an unclosed ```` ``` ```` and then adds `## 14:30 · finding`,
    which the fence-aware parser hides;
  - a paragraph appended under the last entry ("Addendum: …").

- **The addendum case is the defect class itself.** Text appended under the
  last entry inherits that entry's stamp, which is a wrong time with no
  timestamp typed at all. An agent that has just been denied will naturally
  reformat its heading or "add a note to the last entry".

- **Fix.** On an existing day-file, deny any Edit/Write where the
  would-be content has more NON-BLANK lines than the current content, in
  addition to the heading-count test. This allows:

  - deletions (conflict markers);
  - reordering (a merge resolution);
  - same-line-count replacements. The security-redaction case in
    `.claude/hooks-daemon.yaml` (the `today_only_mode` comment) keeps working.

  Add RED tests for each shape above.

### M2. `cd` into `JOURNAL/` and shell-built day-file names both escape the Bash surface

`plan_journal_guard.py:347-369`: the `_DAYFILE_MARKER` prefilter, targets from
`get_bash_write_targets`, and resolution against the payload `cwd` (349, 367).

- **Probed ALLOW:**
  - `cd <plan>/JOURNAL && cat >> 00461-Journal-26-09-24.md <<'EOF' …`;
  - `cd …; echo … >> <dayfile>` and `(cd … && echo … >> <dayfile>)`;
  - `cat >> <plan>/JOURNAL/00461-Journal-$(date -u +%y-%m-%d).md <<'EOF'`,
    which is exactly how an agent builds today's name by hand;
  - `echo … >> <plan>/JOURNAL/*.md`.
- **Why.** Relative targets are resolved against the payload cwd, not the
  command's own `cd`. This is the class Plan 00464 and ledger N23/N28 describe.
  `get_bash_write_targets` drops any target that needs expansion, by design.
  A `cd` made in a SEPARATE earlier call is fine, because the payload cwd
  carries it. Only the same-command `cd` escapes.
- **Fix.**
  - (a) Once 00464 lands, resolve targets with its command-directory resolver.
  - (b) Independently, add a guard-local scan for any redirect, `tee`,
    `cp`/`mv`/`dd`/`install` destination token that contains
    `/<plan_dir>/…/JOURNAL/` or matches `*-Journal-*`, even when it holds `$`,
    backticks or glob characters. Deny when its parent resolves to a plan
    `JOURNAL/`. A day-file basename already encodes the plan number, so the
    remedy can still be printed.

### M3. The prescribed body-file path is fixed per plan and trips R-WRITE-CLOBBER on the second entry

`plan_journal_guard.py:447` (`journal-{plan_number}-entry.md`) and 484/488. The
same fixed path appears in `PlanJournalling.md`, `PlanWorkflow.core.md` and the
release note.

- **Scenario.** The first entry's Write creates
  `untracked/scratch/journal-461-entry.md`, and mkplan leaves it in place. The
  next entry's Write to the same path is denied by `write_clobber_guard`, which
  does not record a session's own Write (ledger N29, open). Two sub-agents
  journalling on one plan also share the file: one either clobbers the other's
  body or is denied.
- **Consequence.** The only sanctioned route fails on its second use, which
  teaches agents to route around it.
- **Fix.** Print a unique body path, for example
  `journal-<plan>-<short-slug>.md`, with a note to pick a fresh name, or tell
  the agent to Read before rewriting. An alternative outside this plan's
  Non-Goals is to have `--journal` remove the body file after a successful
  append. At minimum, link N29 in the deny text until it is fixed.

### M4. Client-facing surfaces still tell agents to hand-append, which sends them straight into the deny

T1.3 claims "`--journal` is THE way in every surface a client gets", but these
surfaces disagree:

- `plan_qa/checks/journal_entry_with_progress.py:82`: "Append a
  `## HH:MM · category · REF` entry to …/JOURNAL/ … and stage it".
- `plan_qa/checks/journal_completion_entry.py:75`: "Append a closing
  `## HH:MM · handoff` entry".
- `plan_qa/checks/journal_entry_future_dated.py:59-64`: "correct the timestamp
  before this write lands … write it to that day's file". This Edit-time check
  is now unreachable for an entry-adding Edit wherever the guard is active,
  because the guard is terminal at 31 and runs before `plan_qa_edit` at 44. The
  instruction is also impossible, because `--journal` only writes today's file.
- `CLAUDE/PlanJournalling.md:264` (both copies): "add a `## HH:MM · action` entry".
- `CLAUDE/PlanJournalling.md:266` (both copies): "Start a new
  `NNNNN-Journal-YY-MM-DD.md`". Creating one by Write is now denied.

**Fix.** Reword each remediation to "run `<plan_dir>/mkplan.bash --journal <N> <category> <body-file>`". Change the lifecycle rows to "`--journal` creates the
day-file". Drop the "correct the timestamp / other day's file" advice, or make
it conditional on the guard being inactive.

## Minor

**m1. Wrapper and interpreter-stdin evasions** (`plan_journal_guard.py:115`,
`143-144`, `584-585`). All of these probe as ALLOW:

- `timeout 5 bash -c "echo >> <dayfile>"` and `nohup sh -c '…'`;
- `uv run python -c "open(<dayfile>,'a')…"`;
- `python3 - <<'EOF' open(<dayfile>,'a') EOF` (a documented limit);
- `awk -i inplace` and `gawk -i inplace`. awk is not in `_IN_PLACE_EDITORS`,
  and `_inline_program` takes `inplace` as the program;
- `git apply x.patch` and `patch -p1 < x.patch`, where the patch is authored
  with Write elsewhere;
- `ln -sf /tmp/x <dayfile>`, `rsync … <dayfile>`, `sponge -a <dayfile>`.

**Fix:**

- add `timeout`, `nohup`, `nice`, `time`, `stdbuf` and `xargs` to the prefix
  set, and `uv run` / `poetry run` as two-word prefixes;
- handle awk's `-i inplace`, and skip the values of `-v`/`-f`/`-i`;
- treat a heredoc fed to an interpreter as program text;
- add `ln`/`rsync`/`sponge` destinations (ideally in
  `get_bash_write_targets`, so every guard gains them).

The `test_blocking_handler_evasion.py:434` exemption rationale ("respelling the
writer does not move where the bytes land") is wrong for wrappers. Soften it.

**m2. False denies on read-only commands** (`plan_journal_guard.py:149-151`,
`410-413`, `380`). One write signal anywhere, plus any day-file path anywhere in
the program, is enough to deny. Probed DENY:

- `python3 -c "…open(<dayfile>).read()…count('a')"`, where `'a'` is read as a mode;
- `sys.stdout.write(open(<dayfile>).read())`;
- `print(len(…) > 3)`;
- `bash -c "wc -l <dayfile> > untracked/scratch/n.txt"`;
- `perl -Ilib script.pl <dayfile>`, where `-Ilib` matches the in-place regex;
- an UNQUOTED heredoc body line (`cat > scratch <<EOF`) that quotes a
  `python3 -c` write. `_stages` strips only quoted bodies.

**Fix:**

- for `sh/bash -c`, recurse with `get_bash_write_targets` on the program text;
- for Python, tie the signal to the path (`open(<path>, 'w|a|x|r+')`,
  `Path(<path>).write_*`);
- require `-i` to be a separate flag or a cluster that does not start with `-I`;
- strip data-sink heredoc bodies whether quoted or not.

The deny wording ("entry written by hand") also misleads on a read.

**m3. The guard switches off silently** (`plan_journal_guard.py:225-239`,
`248-262`). It stands down with no log line and no advisory when:

- `journal.dir_name` is not `JOURNAL`;
- `mkplan.bash` predates `--journal`;
- `_JOURNAL_TEMPLATE_.md` is missing.

Only the unreadable-script case logs. `plan_workflow_asset_checker` reports only
a missing `mkplan.bash`. Meanwhile `get_claude_md()` still injects "journal
entries go through `mkplan.bash --journal`" into CLAUDE.md, including where
`--journal` does not exist. In this repo the gate is satisfied, so the guard is
live. **Fix:** log once at INFO which condition disabled the guard. Surface it
in the asset checker or doctor. Consider making `get_claude_md` conditional.

**m4. Same-count rewrites pass.** A Write that replaces
`## 13:30 · action … plan scaffolded` with `## 15:00 · finding … replaced`
(probed ALLOW) leaves only `journal-append-only`, which is ADVISE here. That is
acceptable by design, but it is worth one test documenting it. M1's line-count
rule does not catch it either.

**m5. The shared parser silently changes fence semantics.** The old per-check
regex toggled on any fence line. `utils/markdown_fences.lines_outside_fences`
closes only on the SAME marker, so a ```` ``` ```` line inside a `~~~` block no
longer ends it. For the ordering and future-dated checks this is probably a fix,
but it is a behaviour change with no test of mixed markers. Add one.
(`plan_qa/model.py`, the new `journal_entry_headings`.)

**m6. Dead values and duplication.**

- `_Layout.journal_dir` (`plan_journal_guard.py:163`, 238) is always
  `DEFAULT_JOURNAL_DIR_NAME`. Drop the field.
- `_JOURNAL_MODE_OFF` (97) duplicates `plan_qa_edit.py:72`. Hoist a shared
  constant into `plan_qa/types.py` beside `DEFAULT_JOURNAL_MODE`.
- `_target()` runs in both `matches()` and `handle()` (435-443), so each deny
  reads `mkplan.bash` and the day-file twice. That matches the house pattern,
  so this is noted only.

**m7. The deny prints relative paths** (`plan_journal_guard.py:446-457`):
`CLAUDE/Plan/mkplan.bash …` and `untracked/scratch/…`. In a main session whose
Bash cwd has persisted after a `cd`, both fail ("body file not found" or
command not found). **Fix:** print absolute paths, or prefix `cd <root> &&`.
The B1 fix needs this anyway.

**m8. Tests coupled to the implementation.**

- `_refuse_to_read` and `test_unstattable_dayfile_is_not_judged` monkeypatch
  the module-level imported names `read_text_or_reason` and `path_is_file`.
  Renaming an import breaks them without any behaviour change.
- `test_says_why` asserts the prose "40 minutes".
- `test_a_dayfile_in_another_checkout_is_not_judged` pins B1 as intended
  behaviour.

**Fix:** drive unreadability through the filesystem, or a seam on the handler.
Assert the rule id and the command instead of prose.

**m9. Docs list incomplete gate conditions.**

- `docs/guides/HANDLER_REFERENCE.md` says "active only when the plan workflow is
  on and `mkplan.bash --journal` is deployed". It omits the template and the
  `JOURNAL` dir-name conditions.
- The POLICY paragraph in `CLAUDE/PlanJournalling.md` names only
  `enabled`/`mode`.
- The release note and manifest describe coverage ("a Bash command that writes
  into one") that B1 and M2 currently contradict. Re-check the wording after
  the fixes.

**m10. The config-changes manifest is a new
`UNRELEASED/config-changes/v3.67.0.yaml`.** Any other plan drafting 3.67.0 will
conflict add/add (as the implementer noted). Its `example_yaml` omits the
`handlers:` root. Past manifests mix both forms, so this is only a consistency
nit. `.claude/HOOKS-DAEMON.md` also regenerates unrelated rows
(`subagent_cache_aggregator`, `prompt_cache_indicator`), which is harmless drift
catch-up but a likely merge-conflict site.

## Suggested order

1. B1 (worktree re-rooting and absolute remedy paths, which also closes m7).
2. M1 (non-blank line-count rule).
3. M2 (a scan for JOURNAL/ destinations; the command-cwd resolver after 00464).
4. M3 (unique body path).
5. M4 (reword the remediations and lifecycle rows).
6. The minors.

Add each probe above that returned the wrong verdict as a RED test first.
