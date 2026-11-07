"""Creating a name that is never a work branch cannot raise the work count.

`git branch -f main main` in a checkout with no local `main` (a CI pull-request
checkout is detached) creates `refs/heads/main`. The default branch, an exempt
name and a protected name are never counted as open work, so the cap and
dormancy have nothing to say about creating one; denying it blocked the
playbook's own probe whenever the repository sat at the cap.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_creation import creation_verdict


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo_at_cap(tmp_path: Path, cap: int) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "f").write_text("x", encoding="utf-8")
    _git(repo, "add", "f")
    _git(repo, "commit", "-q", "-m", "init")
    for index in range(cap):
        _git(repo, "checkout", "-q", "-b", f"work-{index}")
        (repo / f"w{index}").write_text(str(index), encoding="utf-8")
        _git(repo, "add", f"w{index}")
        _git(repo, "commit", "-q", "-m", f"w{index}")
    _git(repo, "checkout", "-q", "--detach")
    _git(repo, "branch", "-D", "main")
    return repo


def _config(cap: int) -> BranchesConfig:
    return BranchesConfig.model_validate({"wip": {"cap": cap}, "default": "main"})


def test_creating_the_default_branch_at_the_cap_is_allowed(tmp_path: Path) -> None:
    repo = _repo_at_cap(tmp_path, cap=2)
    verdict = creation_verdict(repo, _config(2), "main")
    assert verdict.decision == "allow", verdict


def test_a_work_branch_at_the_cap_is_still_denied(tmp_path: Path) -> None:
    repo = _repo_at_cap(tmp_path, cap=2)
    verdict = creation_verdict(repo, _config(2), "feature-x")
    assert verdict.decision == "deny", verdict


def test_an_exempt_name_at_the_cap_is_allowed(tmp_path: Path) -> None:
    repo = _repo_at_cap(tmp_path, cap=2)
    config = BranchesConfig.model_validate(
        {"wip": {"cap": 2}, "default": "main", "exempt": ["release/*"]}
    )
    assert creation_verdict(repo, config, "release/9.9.9").decision == "allow"
