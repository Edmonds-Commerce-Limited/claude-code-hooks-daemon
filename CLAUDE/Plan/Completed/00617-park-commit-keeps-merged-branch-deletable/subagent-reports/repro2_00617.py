"""Plan 00617 probe: unparked tip, re-park stack, remote-only park, all over merged work."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import repro_00617 as base

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_creation, branch_inventory
from claude_code_hooks_daemon.core.branch_park import park_branch
from claude_code_hooks_daemon.core.remote_branch_proof import prove_remote_merged
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import _remote_delete_note


def probe(title: str, steps: list[tuple[str, bool]], *, remote_only: bool) -> None:
    with tempfile.TemporaryDirectory(dir=os.environ.get("SCRATCH")) as tmp:
        repo = base.setup(Path(tmp))
        config = BranchesConfig(default="main")
        base.work(repo, "feat")
        base.merge(repo, "feat", squash=False)
        if remote_only:
            base.git(repo, "branch", "-q", "-D", "feat")
        for reason, clear in steps:
            park_branch(repo, "feat", reason=reason, remote="origin", clear=clear)
        if not remote_only:
            base.git(repo, "branch", "-q", "-D", "feat")
        base.git(repo, "fetch", "-q", "--prune", "origin")
        inv = branch_inventory.build_inventory(repo, config)
        print(f"{title}: inventory={inv.records['feat'].state}")
        proof = prove_remote_merged(repo, "origin", ["feat"], "main", config)
        print(
            f"  proof tips={list(proof.tips)} evidence={proof.evidence} problems={proof.problems}"
        )
        note = _remote_delete_note("git push origin --delete feat", repo, config)
        print(f"  guard: {'ALLOW' if note is None else 'DENY'}")
        pools = branch_creation.work_pools(repo, config)
        print(
            f"  creation pools: { {str(k): [sorted(w.names) for w in v] for k, v in pools.items()} }"
        )


if __name__ == "__main__":
    probe("[park, unpark]", [("r1", False), ("", True)], remote_only=False)
    probe("[park, repark]", [("r1", False), ("r2", False)], remote_only=False)
    probe("[remote-only park]", [("r1", False)], remote_only=True)
    probe("[remote-only park, unpark]", [("r1", False), ("", True)], remote_only=True)
