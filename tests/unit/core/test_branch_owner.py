"""Pools are counted per owner (Plan 00594 Task 4.4, DESIGN.md section 2.2).

A branch is mine when this clone recorded its creator, or it has a local ref,
or its remote tip's author email is this clone's ``user.email``. Anything else
is foreign: listed in its own sweep group, counted in no pool, never cleaned
automatically, yet deleted by ``--clean --remote`` once PROVEN merged.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core.branch_cleanup import clean_sweep
from claude_code_hooks_daemon.core.branch_creation import creation_report
from claude_code_hooks_daemon.core.branch_inventory import (
    BranchState,
    Pool,
    build_inventory,
    pool_of,
)
from claude_code_hooks_daemon.core.branch_records import CREATOR_KEY
from claude_code_hooks_daemon.core.branch_sweep import (
    group_records,
    pool_count,
    render_report,
    report_json,
)

DAY: Final[int] = 86_400
ME: Final[str] = "me@example.com"
THEM: Final[str] = "them@example.com"


def _git(repo: Path, *args: str, author: str = ME, days_ago: float = 1) -> str:
    stamp = f"@{int(time.time() - days_ago * DAY)} +0000"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Author Name",
        "GIT_AUTHOR_EMAIL": author,
        "GIT_COMMITTER_NAME": "c",
        "GIT_COMMITTER_EMAIL": author,
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
    }
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", str(remote), str(root))
    (root / ".git" / "info" / "exclude").write_text("untracked/\n")
    _git(root, "config", "user.email", ME)
    _git(root, "checkout", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root", days_ago=500)
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    return root


def _push_only(repo: Path, name: str, *, author: str, keep_local: bool = False) -> None:
    """A pushed work branch; by default only the remote holds it afterwards."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    (repo / f"{name}.txt").write_text(name)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", name, author=author)
    _git(repo, "push", "-q", "origin", name)
    _git(repo, "checkout", "-q", "main")
    if not keep_local:
        _git(repo, "branch", "-q", "-D", name)
        _git(repo, "fetch", "-q", "origin")


def _config(**extra: object) -> BranchesConfig:
    return BranchesConfig.model_validate(
        {
            "default": "main",
            "wip": {"cap": 1, "mode": "block", "creation_grace": 0},
            "duplicates": {"mode": "off"},
            **extra,
        }
    )


class TestOwnerRule:
    def test_remote_tip_by_another_author_is_foreign(self, repo: Path) -> None:
        _push_only(repo, "theirs", author=THEM)
        record = build_inventory(repo, _config()).records["theirs"]
        assert record.state == BranchState.FOREIGN
        assert record.author_email == THEM
        assert record.author == "Author Name"

    def test_remote_tip_by_my_email_is_mine(self, repo: Path) -> None:
        _push_only(repo, "mine", author=ME)
        assert build_inventory(repo, _config()).records["mine"].state == BranchState.LIVE

    def test_email_match_ignores_case(self, repo: Path) -> None:
        _push_only(repo, "mine", author=ME.upper())
        assert build_inventory(repo, _config()).records["mine"].state == BranchState.LIVE

    def test_local_ref_is_mine_whatever_the_author(self, repo: Path) -> None:
        _push_only(repo, "local", author=THEM, keep_local=True)
        assert build_inventory(repo, _config()).records["local"].state == BranchState.LIVE

    def test_creator_record_is_mine_whatever_the_author(self, repo: Path) -> None:
        _push_only(repo, "recorded", author=THEM)
        _git(repo, "config", f"branch.recorded.{CREATOR_KEY}", "sess:")
        assert build_inventory(repo, _config()).records["recorded"].state == BranchState.LIVE

    def test_no_user_email_makes_an_unrecorded_remote_branch_foreign(self, repo: Path) -> None:
        _push_only(repo, "theirs", author=ME)
        _git(repo, "config", "--unset", "user.email")
        env_free = build_inventory(repo, _config()).records["theirs"]
        # A global identity may exist on the host; only assert when none does.
        has_global = subprocess.run(
            ["git", "config", "user.email"], cwd=repo, capture_output=True, check=False
        ).stdout.strip()
        if not has_global:
            assert env_free.state == BranchState.FOREIGN

    def test_branch_name_with_dots_reads_its_creator(self, repo: Path) -> None:
        _push_only(repo, "rel-1.2.x", author=THEM)
        _git(repo, "config", f"branch.rel-1.2.x.{CREATOR_KEY}", "sess:")
        assert build_inventory(repo, _config()).records["rel-1.2.x"].state == BranchState.LIVE


class TestForeignIsInNoPool:
    def test_pool_of_foreign_is_none(self) -> None:
        assert pool_of(BranchState.FOREIGN) is None

    def test_foreign_branches_do_not_fill_the_open_cap(self, repo: Path) -> None:
        for name in ("a", "b", "c"):
            _push_only(repo, name, author=THEM)
        inventory = build_inventory(repo, _config())
        assert pool_count(inventory, Pool.OPEN) == 0
        report = creation_report(repo, _config(), "new-work")
        assert report.blockers == ()

    def test_foreign_dormant_branch_is_not_dormant(self, repo: Path) -> None:
        _push_only(repo, "old", author=THEM)
        _git(repo, "commit", "-q", "--allow-empty", "-m", "x")  # keep main moving
        record = build_inventory(repo, _config()).records["old"]
        assert record.state == BranchState.FOREIGN
        assert record.dormancy_stage is None

    def test_my_branches_still_count(self, repo: Path) -> None:
        _push_only(repo, "mine", author=ME)
        _push_only(repo, "theirs", author=THEM)
        assert pool_count(build_inventory(repo, _config()), Pool.OPEN) == 1


class TestSweepForeignGroup:
    def test_group_lists_foreign_with_age_and_author(self, repo: Path) -> None:
        _push_only(repo, "theirs", author=THEM)
        inventory = build_inventory(repo, _config())
        groups = group_records(inventory)
        assert [r.name for r in groups.foreign] == ["theirs"]
        text = "\n".join(render_report(inventory, _config(), cap=10))
        assert "Foreign" in text
        assert "theirs" in text
        assert THEM in text

    def test_json_group_is_foreign(self, repo: Path) -> None:
        _push_only(repo, "theirs", author=THEM)
        document = json.loads(json.dumps(report_json(build_inventory(repo, _config()), cap=10)))
        row = next(b for b in document["branches"] if b["name"] == "theirs")
        assert row["group"] == "foreign"
        assert row["pool"] is None
        assert row["author_email"] == THEM


class TestCleaningForeign:
    @staticmethod
    def _merged_foreign(repo: Path) -> None:
        _push_only(repo, "done", author=THEM)
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "origin/done")
        _git(repo, "push", "-q", "origin", "main")

    def test_proven_merged_foreign_is_deleted_by_clean_remote(
        self, repo: Path, tmp_path: Path
    ) -> None:
        self._merged_foreign(repo)
        inventory = build_inventory(repo, _config())
        assert inventory.records["done"].state == BranchState.FOREIGN
        clean_sweep(repo, _config(), dry_run=False, bundle_dir=tmp_path / "b", remote=True)
        listing = _git(repo, "ls-remote", "--heads", "origin", "done")
        assert listing == ""

    def test_unmerged_foreign_is_never_deleted(self, repo: Path, tmp_path: Path) -> None:
        _push_only(repo, "theirs", author=THEM)
        clean_sweep(repo, _config(), dry_run=False, bundle_dir=tmp_path / "b", remote=True)
        assert _git(repo, "ls-remote", "--heads", "origin", "theirs") != ""

    def test_foreign_merged_is_not_in_the_merged_pool(self, repo: Path) -> None:
        self._merged_foreign(repo)
        assert pool_count(build_inventory(repo, _config()), Pool.MERGED) == 0


class TestNoDenyOffersForeignFix:
    def test_report_never_offers_rename_or_foreign_delete(self, repo: Path) -> None:
        for name in ("a", "b"):
            _push_only(repo, name, author=ME)
        _push_only(repo, "theirs", author=THEM)
        report = creation_report(repo, _config(), "new-work")
        fixes = " ".join(fix for blocker in report.blockers for fix in blocker.fixes)
        assert "theirs" not in fixes
        assert "rename" not in fixes.lower()
