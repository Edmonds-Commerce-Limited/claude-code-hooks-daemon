"""Plan 00617 Task 1.1 reproduction: a merged branch parked by the real park writer.

Synthetic repositories only. Prints each consumer's verdict for each shape.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_cleanup, branch_inventory
from claude_code_hooks_daemon.core.branch_park import park_branch
from claude_code_hooks_daemon.core.remote_branch_proof import prove_remote_merged
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
    _remote_delete_note,
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def setup(root: Path) -> Path:
    bare = root / "remote.git"
    git(root, "init", "-q", "--bare", "-b", "main", str(bare))
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", "base.txt")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "remote", "set-head", "origin", "main")
    return repo


def work(repo: Path, name: str) -> None:
    git(repo, "checkout", "-q", "-b", name, "main")
    (repo / f"{name}.txt").write_text(f"{name}\n")
    git(repo, "add", f"{name}.txt")
    git(repo, "commit", "-q", "-m", f"work {name}")
    git(repo, "push", "-q", "-u", "origin", name)
    git(repo, "checkout", "-q", "main")


def merge(repo: Path, name: str, *, squash: bool) -> None:
    if squash:
        git(repo, "merge", "--squash", "-q", name)
        git(repo, "commit", "-q", "-m", f"squash {name}")
    else:
        git(repo, "merge", "--no-ff", "-q", "-m", f"Merge {name}", name)
    git(repo, "push", "-q", "origin", "main")


def report(repo: Path, name: str, config: BranchesConfig) -> None:
    git(repo, "fetch", "-q", "--prune", "origin")
    inv = branch_inventory.build_inventory(repo, config)
    rec = inv.records.get(name)
    print(f"  inventory state: {rec.state if rec else None}")
    proof = prove_remote_merged(repo, "origin", [name], "main", config)
    print(
        f"  prove_remote_merged: tips={list(proof.tips)} evidence={proof.evidence} problems={proof.problems}"
    )
    note = _remote_delete_note(f"git push origin --delete {name}", repo, config)
    print(f"  R-GIT-PUSH-DELETE-REMOTE: {'ALLOW' if note is None else 'DENY: ' + note[:160]}")
    if name in branch_safety.local_branches(repo):
        c = branch_safety.classify_branch(repo, name, protected_ref="main")
        print(f"  delete-branch classify (content tier): tier={c.tier} refusal={c.refusal}")
        c2 = branch_safety.classify_branch(repo, name, protected_ref="main", content_tier=False)
        print(f"  delete-branch classify (hook, no content tier): tier={c2.tier}")
    cleanup = branch_cleanup.clean_sweep(repo, config, dry_run=True, remote=True)
    print(f"  clean_sweep --remote dry: commands={cleanup.commands} skipped={cleanup.skipped}")
    applied = branch_cleanup.clean_sweep(repo, config, dry_run=False, remote=True)
    print(
        f"  clean_sweep --remote apply: local={applied.deleted} remote={applied.deleted_remote} skipped={applied.skipped}"
    )
    left_local = git(repo, "branch", "--list", name).strip()
    left_remote = git(repo, "ls-remote", "--heads", "origin", name).strip()
    print(f"  after apply: local left={bool(left_local)} remote left={bool(left_remote)}")


def scenario(title: str, *, squash: bool, keep_local: bool, commit: bool = True) -> None:
    with tempfile.TemporaryDirectory(dir=os.environ.get("SCRATCH")) as tmp:
        repo = setup(Path(tmp))
        config = BranchesConfig(default="main")
        work(repo, "feat")
        merge(repo, "feat", squash=squash)
        result = park_branch(
            repo, "feat", reason="merged; waiting on release", remote="origin", commit=commit
        )
        print(f"{title}: park pushed={result.pushed}")
        if not keep_local:
            git(repo, "branch", "-q", "-D", "feat")
        report(repo, "feat", config)


if __name__ == "__main__":
    for squash in (False, True):
        for keep_local in (True, False):
            scenario(f"[squash={squash} local={keep_local}]", squash=squash, keep_local=keep_local)
    sys.exit(0)
