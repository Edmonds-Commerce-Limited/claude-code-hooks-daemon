# Plan 00634 build handoff 3

Branch `plan-00634-human-approval-check` (pushed). Worktree
`.claude/worktrees/agent-a6328547e60968275-2a1ab764`. No code changed since
handoff 2: this session spent its budget on orientation and settled the guard
design below (reviewed by the advisor). Start Task 2.2 from here, test-first,
one commit + push per numbered step.

## Facts established (do not re-derive)

- **Discovery registers every public concrete Handler subclass found in a
  module's namespace** (`registry.is_discoverable_handler`, no `__module__`
  filter). So the guard must NOT import `DangerousPermissionsHandler`,
  `MergeToMainApprovalHandler` or `DestructiveGitHandler`: each would register
  twice. Use module-level public functions instead (step 1).
- `team_seat` is NOT injected into handlers today. `Config.team_seat`
  (`config/models.py` `TeamSeatConfig`) is only read by
  `daemon/team_seat_cli.py`. Mirror the `scratch` plumbing (step 2).
- Chain: an ALLOW never ends the chain, even from a terminal handler
  (`core/chain.py` header). `terminal=True` is safe in advise mode.
- `destructive_git` (10), `dangerous_permissions` (15) deny first as terminal
  SAFETY handlers, so the guard only ever sees what they let through (normal
  push, merged-branch remote delete, pushed-branch forced delete, clean
  worktree remove, merges). Priority **21** (after `MERGE_TO_MAIN_APPROVAL` 20).
- `_deleted_branches` only sees FORCED deletes (`branch -D`/`-df`,
  `update-ref -d`); plain `branch -d` is not detected. Record as an open point,
  do not add a regex.
- `_deleted_branches`, `_worktree_removals`, `_remote_delete_targets` raise
  `_Unverifiable`; that must count as DELETE (fail closed), never as "no act".
- `MergeToMainApprovalHandler._merges_into_main_checkout_default_branch` returns
  False when the branch is unreadable; for the guard an unreadable branch with
  a merge named must count as MERGE_MAIN. A linked worktree stays a definite no.
  `gh pr merge` lands on the PR base on GitHub regardless of cwd: count it as
  MERGE_MAIN via the existing `_GH_PR_MERGE_RE` (no new regex); record as an
  open point.
- Tagging tests: `tests/unit/handlers/test_pretooluse_fail_closed_tagging.py`
  (BLOCKING without SAFETY needs a row in `_AUDITED_BLOCKING_ONLY_REASONS`) and
  `tests/integration/test_declared_behaviour_matches_source.py` (source with
  `Decision.DENY` must not be declared ADVISORY). Chosen: tags
  `[WORKFLOW, BLOCKING, TERMINAL]` plus an audited row: chain-level
  crash/saturation must fail OPEN because a seatless session must see no
  change; inside the handler every armed failure is the mode's refusal.
  Do NOT add the `git` tag (it triggers the worktree setattr for no use).
- Sibling for shape: `handlers/pre_tool_use/resume_guard.py` (`_mode` class
  attr, `validate_options`, advise = ALLOW + context, deny = `.under_rule`,
  `harness_cannot_produce` acceptance tests).

## Steps

1. **Public detector seams** (tests first, one test each):
   - `dangerous_permissions.sets_world_writable(command) -> bool`; the
     handler's `matches` delegates to it.
   - `merge_to_main_approval.merge_lands_on_main(cwd, target) -> bool | None`
     (None = unreadable); the handler's static method maps None to False
     (unchanged behaviour). Plus `is_pr_merge(command) -> bool` on
     `strip_inert_spans` text using `_GH_PR_MERGE_RE`.
   - `destructive_git.names_a_deletion(command) -> bool`: any forced branch
     delete, any push run with remote delete targets, any worktree remove;
     `_Unverifiable` -> True.
2. **`team_seat` injection**: parameter at `handlers/registry.py`
   `register_all` (signature ~634, injection beside `_scratch` ~897),
   `daemon/controller.py` (~260 and ~385), `daemon/cli.py` (~4591,
   `team_seat=config.team_seat`). Test shaped like
   `tests/unit/handlers/test_registry_branches_injection.py`.
3. **RED handler tests** `tests/unit/handlers/pre_tool_use/test_human_approval_check.py`.
   Reuse `tests/support/teamchat.py` fixtures and the shapes in
   `tests/unit/utils/test_human_approval.py` (MAIN/SUBAGENT inputs,
   `parse_whoami(fx.COORDINATOR_ONLY)` etc.). Inject a fake resolver/verifier
   on the instance. Cases: no runtime -> matches False and NO subprocess; worker
   seat -> silent (Q5 on), armed with Q5 off; unknown role -> armed; sub-agent
   -> silent; each act class detected; `git push` inside `-m`/quoted heredoc is
   prose; trailing cite comment still classifies as PUSH; no cite -> NO_CITE;
   malformed or two cites -> NO_CITE; default verifier -> CONTRACT_UNCONFIRMED
   deny in block, context in advise, never the word "verified" on a refusal;
   pass -> ALLOW, and never relaxes another handler; exception after arming ->
   refusal (block) / advisory (advise), exception before arming -> silent;
   mode off -> dormant; nothing under seat store / run dir opened (mirror the
   verifier suite's `builtins.open` test). Messages built only from
   `verdict.reason` + act names, never from cite text.
4. **GREEN handler** `handlers/pre_tool_use/human_approval_check.py`.
   `matches`: mode off -> False; not Bash -> False; signals runtime empty ->
   False; classify acts (pure) -> none -> False; resolve seat lazily from
   `self._team_seat` (`SeatContextResolver.from_config`, built on first use,
   module-level `ApprovalRecords`); `is_armed(..., coordinator_seats_only=)`.
   Cite: trailing comment on the last line
   `# human-approval team=<T> id=<$id>` -> `parse_cite`. Constants:
   `HandlerID.HUMAN_APPROVAL_CHECK`, `Priority.HUMAN_APPROVAL_CHECK = 21`,
   `RuleID.HUMAN_APPROVAL_MISSING = "R-HUMAN-APPROVAL-MISSING"`.
5. **Config, docs, release note**: `.claude/hooks-daemon.yaml` (mode advise),
   `.claude/hooks-daemon.yaml.example`, `daemon/init_config.py`, append to
   `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`, release note
   `CLAUDE/UPGRADES/UNRELEASED/release-notes/087-human-approval-check.md`
   (check the README there for numbering), `docs/guides/HANDLER_REFERENCE.md`,
   `docs/guides/CONFIGURATION.md`, `.claude/HOOKS-DAEMON.md` (check whether it
   is generated), `tests/integration/test_claude_md_guidance_coverage.py`,
   `tests/integration/test_handler_scope_defaults.py`, audited row in the
   fail-closed tagging test. State in the yaml comment and release note that
   `block` denies every coordinator push until issue 369 lands (the default
   verifier refuses every cite).
6. Tick Task 2.2 and the proved success criteria; add the new open points
   (forced-only deletes, `gh pr merge` always MERGE_MAIN, permission scope is
   world-writable chmod only) to PLAN.md; keep Q4/Q5 "proposed, owner ruling
   pending"; open the PR (body lists open design points, ends with the Claude
   Code attribution line). Do NOT merge.

## Running

`PYTHONPATH=src nice -n 19 /workspace/untracked/venv-workspace-py313-0d6d49c6/bin/python -m pytest <files> -q -p no:cacheprovider --no-cov`.
ruff, black, mypy from the same venv `bin/` on touched files. `&&` chains only.
Recursive `grep`/`git grep` over `tests/` must exclude
`tests/fixtures/cyber-flag` (`':!tests/fixtures/cyber-flag'`) and avoid
protected secret paths.
