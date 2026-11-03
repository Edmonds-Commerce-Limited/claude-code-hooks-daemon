Answers below. Every path is relative to `/workspace/src/claude_code_hooks_daemon/` unless it starts with `/workspace/`.

**1. branch_count_advisor and worktree_create**
- **What it counts:** local branches only. It runs `git for-each-ref` over `refs/heads/worktree-*` and `refs/heads/agent-*` (`handlers/session_start/branch_count_advisor.py:78-90`). The prefixes come from `WORK_BRANCH_PREFIXES` (`utils/git_repo.py:79-84`). No remote refs are counted.
- **Options:**
  - `max_open_branches` defaults to 3 (`:40`).
  - `behind_main_threshold` defaults to 50 (`:43`).
  - It checks how far behind only the first 20 branches are (`MAX_BEHIND_CHECKS`, `:47`).
  - This repo sets both options at `/workspace/.claude/hooks-daemon.yaml:1105-1106`.
- **When it fires:** SessionStart, new sessions only, never on resume (`:109-111`).
- **What "behind" means:** `rev-list --count branch..base`, where base comes from `git_sync.default_branch` (`:92-107`, `:120`).
- **Can it block:** no. It always returns `Decision.ALLOW` with context text (`:118`, `:154`), and is tagged ADVISORY and non-terminal (`:59-65`).
- **worktree_create:** handles the WorktreeCreate event (`handlers/worktree_create/worktree_create_handler.py:103-141`).
  - It runs `git worktree add -b <branch> <path>` (`:198-199`).
  - The branch is named `<slug>-<8hex>`, not `agent-*` or `worktree-*` (`:136`; `core/worktree_naming.py:71-74`).
  - The slug falls back to `worktree` when the name is empty (`core/worktree_naming.py:28,56`).
  - The path is `.claude/worktrees/<name>` (`core/worktree_naming.py:77-81`).
  - If the add fails, it removes the worktree and deletes any branch it created with `branch -D` (`:206-227`).
  - Inference: because of this naming, branch_count_advisor misses branches this handler makes, unless the slug happens to start with `agent-` or `worktree-`.

**2. destructive_git delete rules**
- **R-GIT-PUSH-DELETE-REMOTE:** `_remote_delete_note` (`handlers/pre_tool_use/destructive_git.py:638-673`).
  - The default branch comes from `default_branch(directory)` (`:660`). If it can't be found, the delete is unverified and denied (`:661-662`).
  - `default_branch` (`utils/git_sync.py:372-395`) first reads `symbolic-ref refs/remotes/origin/HEAD`, then falls back to a local `main`, then `master`.
  - Per branch (`:563-609`):
    - Refused if it is the default branch, a tag, or shares its name with a tag.
    - Requires `refs/remotes/<remote>/<name>` to exist.
    - Requires `merge-base --is-ancestor` against `refs/remotes/<remote>/<default>` or the local `refs/heads/<default>`.
  - It then checks the live remote: `git ls-remote <remote> refs/heads/<name>` must equal the tracking tip exactly (`:612-635`).
- **Other merge targets (e.g. `release/*`):** no config option exists. The only merge target is the one default branch. The handler's `__init__` takes no options (`:784`).
- **R-GIT-BRANCH-FORCE-DELETE (`git branch -D`, `-d --force`, `update-ref -d`):** `_branch_delete_note` (`:474-505`).
  - It is allowed only when a remote-tracking ref under `refs/remotes/` contains the branch tip (`for-each-ref --contains`, `:442-467`).
  - There is no merge-target check and no option.

**3. branch_safety, delete-branch, worktree-reap**
- **`daemon/branch_safety.py`:**
  - "Protected ref" is the ref every proof is measured against; the default is `"main"` (`:85-86`).
  - Separately, protected names are `main`, `master`, `develop`, `trunk` (`:83`); these are always refused (`:528-533`).
  - Before deleting, it refuses a branch that isn't local, is the current branch, or is checked out in a worktree (`:516-539`).
  - It then proves one of these tiers (`:551-608`):
    - **merged:** ancestor of the protected ref.
    - **patch-equivalent:** `git cherry` count is 0.
    - **content-preserved:** every blob is reachable from the protected ref.
    - **unproven:** anything else. This needs `allow_unproven`, a reason and a human confirm callback (`:698-739`).
  - It writes a recovery bundle first (`:741-743`), re-checks that the tip hasn't moved (`:751`), and deletes via git (`:760`).
- **delete-branch CLI:**
  - Defined at `daemon/cli.py:12794-12838`.
  - `--protected-ref` defaults to `main` (`:12807-12810`); the bundle defaults to `untracked/deleted-branches.bundle`.
  - It calls `delete_branches` (`daemon/cli.py:6504-6507`).
  - It does not use `git_sync.default_branch`.
- **worktree-reap CLI:**
  - Defined at `daemon/cli.py:12426-12464`, with `--base-branch` defaulting to `main`. It only reports unless `--reap` is given; `--reap-branches` is a separate flag.
  - It only considers worktrees under the sanctioned worktree dirs (`core/worktree_reaping.py:293-315`).
  - Before reaping, it requires all of these (`:227-278`):
    - no uncommitted paths
    - zero `rev-list base..HEAD`
    - zero `git cherry` "+" lines
    - no live process with its working directory inside
    - age of at least 15 minutes (`:105`)
  - It removes the worktree without `--force` and the branch with `branch -d` (`:444-538`).
  - Orphan pruning covers only `agent-*` branches that `git branch --merged` lists (`:558-560`, `:601-694`).
  - It has no "protected ref" concept; it uses only the base branch.

**4. Branches the daemon creates**
- **WorktreeCreate:** `<slug>-<hash>`, as in Q1.
  - The WorktreeRemove handler runs only `worktree remove --force` and `prune`, never a branch delete (`handlers/worktree_remove/worktree_remove_handler.py:65-68`). So the branch outlives its worktree.
  - `worktree-reap --reap` deletes it with `-d` only while the worktree still exists. Once orphaned, it is outside the `agent-*` pruning.
- **`/workspace/scripts/setup_worktree.sh:295-297`:** `git worktree add -b ${BRANCH_NAME}`, and the name must start with `worktree-` (`:104`). It does not remove the branch.
- **`/workspace/scripts/dummy-client-repo.sh:221`:** `worktree add --detach`, so no branch.
- **`/workspace/scripts/qa/llm_qa.py`:** uses `update-ref` on `refs/integration/{base,certified,changed-green}/<branch>` (`:1849-1850`, `:2135`). These are not `refs/heads`. It deletes the base ref at `:2063`.
- **Not found:** no preserve, auto-commit or backup branch. I grepped `src/` and `scripts/` for `checkout -b`, `switch -c`, `worktree add`, `update-ref`, `"branch", <name>` and preserve/backup patterns.

**5. Stop / SubagentStop handlers that touch git**
- None found. I grepped `handlers/stop/*.py` and `handlers/subagent_stop/*.py` for `run_git`, `git_sync`, `"git"`, `rev-list` and `unpushed`.
- `subagent_handoff_gate.py` and `subagent_report_path_verifier.py` only mention the worktree in prose (`:12,42,60,139` and `:155,173-174`).
- **Stop handlers:** `auto_continue_stop`, `background_task_recorder`, `cron_stop_enforcer`, `goal_loop_detector`, `idle_workable_issue_stop_gate`, `teammate_reap_advisor`, `usage_pause_stop_gate`.
- **SubagentStop handlers:** `cron_subagent_stop_enforcer`, `subagent_cache_aggregator`, `subagent_handoff_gate`, `subagent_report_path_verifier`, `subagent_report_persistence`, `subagent_report_size_blocker`.

**6. Hooks on branch creation**
- **No WIP-limit gate exists.** Related hooks:
  - **WorktreeCreate handler (Q1):** it creates the branch and enforces no limit.
  - **`handlers/pre_tool_use/agent_isolation_advisor.py`:** advises *adding* `isolation: worktree` and never blocks (`:125-147`).
  - **`handlers/pre_tool_use/sensitive_content.py`:** scans branch names in `git branch`, `checkout -b` and `switch -c` for sensitive words only (`:1496`, `:1834`).
  - **`handlers/pre_tool_use/merge_qa_advisor.py`:** fires on `git merge` of a work branch, not on creation (`:14`, `:44`).

**7. Config**
- **Where options live:**
  - The model is `HandlerConfig.options: dict[str, Any]` (`config/models.py:87`), read through `handler_options()` (`config/models.py:123-142`).
  - There is no per-handler options schema. The registry applies each option as `setattr(instance, "_<key>")` (`handlers/registry.py:386-427`).
  - The template line for this handler is in `daemon/init_config.py:386`.
- **Project-wide default/integration branch setting:** not found. I grepped `config/`, `constants/`, `core/project_context.py` and `.claude/hooks-daemon.yaml` for `default_branch`, `integration_branch`, `protected_branch`, `base_branch` and `release/`.
- The default branch is resolved separately in three places: `git_sync.default_branch` (Q2), `main` hard-coded in the `delete-branch` / `worktree-reap` CLI defaults (Q3), and `DEFAULT_PROTECTED_NAMES` in branch_safety.