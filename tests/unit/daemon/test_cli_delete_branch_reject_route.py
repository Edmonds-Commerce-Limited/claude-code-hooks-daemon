"""``delete-branch`` consults the no-value route (Plan 00620, DESIGN.md section 10).

The CLI builds the ``RejectRoute`` from ``branches.reject``: the state store under the
MAIN checkout, the ledger in the checkout the command runs in, and the resolved
default branch as the reference. Building it can fail (a bare repository, or no main
checkout); the command must then refuse an ``unproven`` branch exactly as before and
say why, never crash and never delete.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pytest
from tests.unit.core.test_branch_reject import _git, _issue, _tip, config, repo

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core import branch_reject
from claude_code_hooks_daemon.core.branch_reject import (
    TIER_REJECTED_BUNDLED,
    RejectError,
    RejectStore,
    bundle_path_for,
    read_ledger,
)
from claude_code_hooks_daemon.daemon.cli import cmd_delete_branch

__all__ = ["config", "repo"]


@pytest.fixture
def project(repo: Path) -> Path:
    """The reject-test repository, made a daemon project so the CLI accepts it."""
    (repo / ".claude" / "hooks-daemon").mkdir(parents=True)
    return repo


@pytest.fixture
def store(project: Path, config: BranchRejectConfig) -> RejectStore:
    return RejectStore(project / config.state_dir)


def _args(repo: Path, **overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "project_root": repo,
        "branches": ["feat"],
        "protected_ref": None,
        "dry_run": False,
        "format": "text",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _exists(repo: Path) -> bool:
    return bool(_git(repo, "for-each-ref", "refs/heads/feat").strip())


def _fresh_verdict(repo: Path, store: RejectStore) -> None:
    _issue(repo, store, issued_at=time.time() - 60)


class TestTheRouteThroughTheCli:
    def test_a_valid_verdict_deletes_and_prints_both_restore_lines(
        self,
        project: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        tip = _tip(project)
        _fresh_verdict(project, store)
        assert cmd_delete_branch(_args(project)) == 0
        out = capsys.readouterr().out
        bundle = bundle_path_for(project, config, "feat", tip)
        assert TIER_REJECTED_BUNDLED in out
        assert f"git fetch {bundle}" in out
        assert f"git branch feat {tip}" in out
        assert not _exists(project)
        (line,) = read_ledger(project / config.ledger_path)
        assert line.tip == tip

    def test_the_json_output_names_the_tier_and_the_bundle(
        self,
        project: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        tip = _tip(project)
        _fresh_verdict(project, store)
        assert cmd_delete_branch(_args(project, format="json")) == 0
        payload = json.loads(capsys.readouterr().out)
        (classification,) = payload["classifications"]
        assert classification["tier"] == TIER_REJECTED_BUNDLED
        bundle = str(bundle_path_for(project, config, "feat", tip))
        assert classification["recovery_bundle"] == bundle
        assert any(bundle in command for command in payload["restore"])

    def test_no_verdict_refuses_and_names_the_route(
        self,
        project: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert cmd_delete_branch(_args(project)) == 1
        err = capsys.readouterr().err
        assert "no-value route refused" in err
        assert _exists(project)
        assert read_ledger(project / config.ledger_path) == []

    def test_a_dry_run_validates_and_writes_nothing(
        self,
        project: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        tip = _tip(project)
        _fresh_verdict(project, store)
        assert cmd_delete_branch(_args(project, dry_run=True)) == 0
        assert TIER_REJECTED_BUNDLED in capsys.readouterr().out
        assert _exists(project)
        assert not bundle_path_for(project, config, "feat", tip).exists()
        assert read_ledger(project / config.ledger_path) == []


class TestNoMainCheckout:
    def test_an_unbuildable_route_refuses_unproven_cleanly(
        self,
        project: Path,
        store: RejectStore,
        config: BranchRejectConfig,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fresh_verdict(project, store)

        def no_main(_repo: Path) -> Path:
            raise RejectError("a bare repository; there is no main checkout")

        monkeypatch.setattr(branch_reject, "main_checkout", no_main)
        assert cmd_delete_branch(_args(project)) == 1
        err = capsys.readouterr().err
        assert "no-value route is unavailable" in err
        assert "no main checkout" in err
        assert _exists(project)
        assert read_ledger(project / config.ledger_path) == []

    def test_a_worktree_of_a_bare_repository_has_no_route_and_refuses(
        self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Real git, no monkeypatch: the common dir is not a checkout's ``.git``."""
        bare = tmp_path / "bare.git"
        _git(repo, "clone", "-q", "--bare", str(repo), str(bare))
        # No remote: otherwise the source repository proves feat remote-held.
        _git(bare, "remote", "remove", "origin")
        worktree = tmp_path / "wt"
        _git(bare, "worktree", "add", "-q", str(worktree), "main")
        (worktree / ".claude" / "hooks-daemon").mkdir(parents=True)
        assert cmd_delete_branch(_args(worktree)) == 1
        err = capsys.readouterr().err
        assert "no-value route is unavailable" in err
        assert "Traceback" not in err
        assert _git(bare, "for-each-ref", "refs/heads/feat").strip()

    def test_an_unbuildable_route_leaves_a_proven_delete_alone(
        self,
        project: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _git(project, "merge", "-q", "--no-ff", "-m", "merge feat", "feat")

        def no_main(_repo: Path) -> Path:
            raise RejectError("no main checkout")

        monkeypatch.setattr(branch_reject, "main_checkout", no_main)
        assert cmd_delete_branch(_args(project)) == 0
        assert "unavailable" not in capsys.readouterr().err
        assert not _exists(project)
