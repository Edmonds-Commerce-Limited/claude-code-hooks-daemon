## 19:07 · action · — — remote-delete proof tier built on a branch; QA 43/43

Remote-delete proof tier: branch `agent-a20c91c23eca4e56e-43e33957` (commits 31c3325d8, 7ff0fa898, 4a152fd2c, f14aa3891), pushed, NOT merged (main is the target of a pending release and must not move).

What it adds: a `surviving-content` proof tier (an unmerged remote branch whose every added or changed file already has identical mode and blob on the default branch or a declared integration line is deletable; deletion-only and empty branches stay refused), the leased route `delete-branch --remote-only <name>` with the restore line `git push <remote> <sha>:refs/heads/<name>`, the R-GIT-PUSH-DELETE-REMOTE denial text pointing at that route, release note 077.

QA on a still tree (`llm_qa.py changed --base origin/main --allow-unmapped`): 43/43 passed. `--allow-unmapped` was used for the `[too-broad]` files only (CLAUDE.md, .claude/HOOKS-DAEMON.md, core/branch_cleanup.py, daemon/branch_safety.py, daemon/cli.py, handlers/pre_tool_use/destructive_git.py), as delegated in the advisor rulings (item 7). The branch is based on main at 98bfe657, so this run also covers the delete-gate, SSH-forwarding and stop-guard work already on main.

Next: merge with --no-ff after the release is cut, then retire the branch.
