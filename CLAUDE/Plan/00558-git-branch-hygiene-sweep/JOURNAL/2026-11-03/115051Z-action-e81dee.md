## 11:50 · action · —

Tasks 2.0 and 2.1 built in worktree-558-inventory (TDD, red then green).

2.0: `BranchesConfig` (config/models.py) with every DESIGN.md section 1 key, extra=forbid, dormancy validated on effective values (standard 7/14/30, strict 3/3/7). `git_sync.resolve_default_branch`. `delete-branch --protected-ref` and `worktree-reap --base-branch` default to None and resolve through it (explicit flag wins; unresolvable is exit 2). `branch_safety.DEFAULT_PROTECTED_NAMES` now reads the model default; delete-branch passes the configured names plus the resolved default. `branch_count_advisor` reads `branches.wip.cap` / `branches.sweep.behind_threshold` when set, else its own options (unchanged defaults 3/50). The block is injected as `_branches` by the registry. Manifest `added`/`renamed` entries and the init_config template block added.

2.1: `core/branch_inventory.py` per DESIGN.md section 2: one for-each-ref, worktree list, --merged per target, then a cached (tip, target) step with a budget cut-off. Park commits are excluded from ahead and from patch uniqueness by a `log --boundary` walk. New `branch_safety.cherry_unique_shas` fails closed (None on git failure).

Found: Python `str.splitlines()` splits on \\x1c-\\x1e, so a %x1d trailer separator broke parsing; the module splits on "\\n" only. Detail in subagent-reports/261103-phase2-inventory.md.
