# Plan 00558 Task 4.2 handoff (creation guard, creator and touch record)

State: NO code written. Worktree `/workspace/untracked/worktrees/worktree-558-create`, branch
`worktree-558-create`, at main 8d4ecfcc6 plus this file. Venv is built (`./bin/hooks-daemon repair` done). The previous agent spent its budget reading; everything it learnt is below so the
next agent need NOT re-read those files. Follow the brief `/workspace/untracked/scratch/brief-558-create.md`.

Cost warning: the project CLAUDE.md is injected again when you first touch the worktree (about
40k tokens). Do not grep broadly; use the facts below.

## Facts already established (do not re-read)

Config (`config/models.py` ~2263-2445): `BranchesConfig` has `default` ("auto"), `remote`
("origin"), `integration_lines`, `exempt`, `protected_names` (main, master, develop, trunk),
`wip: BranchWipConfig(cap=10, mode block|warn|off, count_remote=True)`,
`duplicates: BranchDuplicatesConfig(mode warn|off)`. A handler receives it by DECLARING
`self._branches: BranchesConfig = BranchesConfig()` in `__init__` (registry.py ~889 injects by
attribute).

`core/branch_inventory.py`:

- `_never_work(name, config, default) -> BranchState | None` (private, line 489): exempt,
  default, integration line, protected. Add a small PUBLIC wrapper (e.g. `is_work_branch`) rather
  than importing the private name.
- `_worktrees(repo) -> dict[str, Path] | None` (line 379): branch -> worktree path, None on git
  failure. Add a public wrapper (e.g. `worktrees_by_branch`) and call it ONLY when a deny or a
  duplicate warning needs the worktree column (rare path).
- `_short(ref)`, `_HEADS`, `_REMOTES` constants; `build_inventory` is the full (slow) pass; do
  NOT call it at PreToolUse.
- There is NO label cache today: `untracked/branch-inventory/cache.json` holds only per-pair
  facts. "Labels from the inventory cache" needs a new small snapshot, e.g.
  `untracked/branch-inventory/labels.json` `{name: {group, age_days, worktree, action}}`,
  written by `handlers/session_start/branch_sweep.py` after `build_inventory` (it already has the
  inventory and `self._branches`). Groups/actions come from `core/branch_sweep.py`:
  `_group_name(record)` (private; groups `merged`, `patch-equivalent`, `contained-nowhere`,
  `dormant`, `live`, `parked`, `unclassified`, `not-work`) and the public
  `delete_action(record, inventory, config)`; `report_json` already emits exactly
  `group` and `action` per record, so the snapshot can be built from `report_json(...)["branches"]`.
  When the snapshot is absent, list names only (age is free from the for-each-ref
  `%(committerdate:unix)`).
- `core/branch_sweep.py`: `DELETE_COMMAND = "bin/hooks-daemon delete-branch"`, `_age`, `_where`
  helpers, `open_work_count`.

`constants/branch_guard.py`: `BRANCH_LIMIT_PRINCIPLE` (append to every deny).

Git helpers: `utils/git_repo.run_git(repo, *args, timeout=Timeout.GIT_CONTEXT)` NEVER raises; a
timeout or missing git is a non-zero `returncode` with the reason in `stderr` -> "could not
judge" advisory, allow. `GitRepo.resolve_for(path)`; `branch_ref(name)`.
Command parsing: `utils/git_commit_parsing.git_invocations(command) -> list[GitInvocation]`
(`subcommand`, `global_options`, `arguments`, `assignments`, `directory`), and
`is_shell_resolved(word)` (True when the word contains shell expansion chars -> unreadable name,
allow per DESIGN section 3). Directory of a run: `utils/git_invocation_directory.placement_problem(run, cwd)`
(None when placeable) and `invocation_directory(run, cwd)`; see `utils/merge_scope.merge_directory`
for the exact idiom. `core.utils.get_bash_command(hook_input)`.

Constants: `ToolName.BASH/WRITE/EDIT/NOTEBOOK_EDIT/TASK/AGENT`, `SUBAGENT_DISPATCH_TOOL_NAMES`
(constants/tools.py); `HookInputField.SESSION_ID/AGENT_ID/TOOL_INPUT/TOOL_USE_ID/CWD`.
Handler registration (copy commit 8a5d1b871, cleanup_after_merge): `HandlerIDMeta` in
`constants/handlers.py`, a slot in `constants/priority.py` (36-55 workflow band for the
PreToolUse guard; PostToolUse recorder near CLEANUP_AFTER_MERGE=39), export in the event
package `__init__.py`, init template line in `daemon/init_config.py` (~line 386), manifest entry
in `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.72.0.yaml` (see lines 62-90 for the shape).
The repo yaml (`.claude/hooks-daemon.yaml`) is OFF LIMITS for this task: tell the coordinator
the two new handlers need enabling there.
Rule IDs: add e.g. `BRANCH_WIP_CAP = "R-BRANCH-WIP-CAP"` to `constants/rule_ids.py`; deny via a
`Rule` + `RuleFormatter` (template: `handlers/pre_tool_use/gh_issue_comments.py`, which also shows
`get_rules`, `get_claude_md`, `get_acceptance_tests`). Every deny must start with the rule's
headline (a test plugin enforces it).

Spend-ledger state (`utils/spend_ledger.py`): `state_path(untracked, session_id, kind, key)`,
`read_state(path) -> dict` (`{}` when absent), `write_state(path, data)` (atomic, logs on
failure). Untracked dir: `ProjectContext.daemon_untracked_dir()` (resume_guard.py line 162 uses
an `_untracked_override` for tests; copy that).

WorktreeCreate (`handlers/worktree_create/worktree_create_handler.py`): `handle()` line 107;
insert the verdict inside `if not path.exists():` before `_git_worktree_add` (line 137); the
branch name is `worktree_dir_name(name, prompt_id, session_id)`. Refuse by RAISING (a raise
exits non-zero and aborts creation, same as `_WorktreeAddError`). BUDGET TRAP: the event has a
pinned worst-case git budget, `constants/timeout.py` ~line 195
(`GIT_WORKTREE + GIT_WORKTREE_CLEANUP * GIT_WORKTREE_CLEANUP_CALLS`), mirrored in
`.claude/init.sh` line 3708 (`WorktreeCreate) _event_socket_wait=60`) and pinned equal by
`test_event_budgets.py`. Each extra git call (the for-each-ref, the creator `git config` writes)
must be added to that budget and to init.sh, or the add can finish after the hook answered.

## Design decided (implement this)

1. `utils/git_branch_creation.py` (new shared argv parser): `created_branches(command) -> list[Creation]` with `name`, `route`, `dwim: bool`, and the `GitInvocation`. Forms:
   `switch -c/-C/--create/--force-create/--orphan <n>` (also `--create=<n>`, `-c<n>`),
   `checkout -b/-B/--orphan <n>` (also `-b<n>`), `branch <n> [start]` only when every option is in
   an allowlist (`-f --force -t --track --track=* --no-track -q --quiet --create-reflog --recurse-submodules`) and there are 1-2 positionals, `worktree add -b/-B <n> <path>`, and
   bare `worktree add <path>` with exactly one positional and no `--detach`/`-d` (name =
   basename(path), `dwim=True`). A name that `is_shell_resolved` is skipped (allowed).
   Uniform rule at decision time: a name already in `refs/heads` is NOT a creation (covers
   `-B`/`-C`/`branch -f` resets and the DWIM existing-branch case).
2. `core/branch_creation.py`: `creation_verdict(repo, config, new_name | None, *, now=None) -> CreationVerdict(decision: allow|warn|deny, lines)`. ONE `git for-each-ref --format=%(refname)%00%(objectname)%00%(committerdate:unix)%00%(symref)` over `refs/heads`
   and (when `count_remote`) `refs/remotes/<remote>`; default = `config.default` unless "auto",
   else the `<remote>/HEAD` symref target (protected_names cover main/master anyway); skip
   `<remote>/HEAD`; keep work names; count = connected groups joining same name OR same tip
   (union-find). `count >= cap`: deny on `block`, warn on `warn`, nothing on `off`. Deny body:
   merged + patch-equivalent first with their `action`, then contained-nowhere/dormant, then
   live, then the rest; each with age and worktree; 20 lines then "and N more"; then
   `BRANCH_LIMIT_PRINCIPLE`. Git failure -> allow + "could not judge" line.
   `stem(name, remote)` and `number_tokens(name)` per DESIGN section 3 (suffix regex
   `[-_](\d{1,2}|r\d+|v\d+|orig|old|new|retry\d*|again|redo|copy|bak|backup|[0-9a-f]{8})$`
   stripped repeatedly; prefixes `worktree-`, `agent-`, `<remote>/`; numbers = 2-5 digit tokens
   of the stem split on `[-_/.]` plus `issue-N`/`gh-N`). Duplicate warning (`duplicates.mode`
   warn) names the existing branch, age, worktree, "continue there instead". Never denies.
3. PreToolUse `branch_creation_guard` (Bash creations; Agent/Task with
   `tool_input.isolation == "worktree"`, new_name = `tool_input.name` for the duplicate check
   only). GatingResult deny with the rule headline, or allow with context lines.
4. `core/branch_records.py` + PostToolUse `branch_touch_recorder`: creator keys
   `branch.<n>.hooksDaemonCreator` (`<session>:<agent>`), `hooksDaemonCreated` (unix),
   `hooksDaemonRoute`, written only after `show-ref --verify refs/heads/<n>` succeeds and only
   when no creator is recorded yet (a reset of an existing branch must not claim it). Touches:
   Bash `commit merge rebase cherry-pick am revert reset switch checkout pull` (branch from
   `git -C <dir> symbolic-ref -q HEAD`), and Write/Edit/NotebookEdit (the file's directory).
   `git config --get-all` then `--add` `hooksDaemonTouchedBy` when absent. Once per branch per
   session+agent via `state_path(untracked, session, "branch-touch", f"{session}:{agent}")`.
   Binding: a call with an `agent_id` touching a branch whose creator is `<same session>:` (empty
   agent, written by WorktreeCreate) rewrites the creator to `<session>:<agent>`. A failed config
   write logs (`log_and_continue`) and allows. Export
   `touched_branches(untracked, session_id, agent_id) -> frozenset[str]` for Task 4.4.

## Left to do

Everything in the brief: tests first, the four modules above, registration, the labels snapshot
writer, budget update, release note 097, manifest entries, guidance, acceptance tests, targeted
QA, report `subagent-reports/261103-task42.md`.

## Addition from the coordinator (after the creator record exists)

`handlers/worktree_remove/worktree_remove_handler.py` decides a branch is eligible for its
merged-branch delete by name shape alone (`is_worktree_create_name`, `<slug>-<8hex>`). Make it
prefer the creator record: eligible when `branch.<name>.hooksDaemonRoute` is `worktree_create`
(so WorktreeCreate must write exactly that route value); fall back to the name shape ONLY when
the branch has no creator record at all; a record with any other route is NOT eligible. RED test
first for each of the three cases. Grep for `is_worktree_create_name` to find the call and read
only that function. Note the WorktreeRemove event also has a pinned git budget
(`constants/timeout.py`, `2 * GIT_WORKTREE`), so count the extra `git config --get` read.
