"""The creation report: one builder for the preflight command and the creation deny (Plan 00594 4.1)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.branch_creation import (
    LABELS_RELATIVE_PATH,
    creation_report,
    creation_verdict,
    read_labels,
    render_creation_report,
    write_labels,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.branch_creation_guard import (
    BranchCreationGuardHandler,
)

NOW: Final[int] = 1_800_000_000
DAY: Final[int] = 86_400


def _git(repo: Path, *args: str, days_ago: float = 0) -> str:
    stamp = f"@{int(NOW - days_ago * DAY)} +0000"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
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
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root", days_ago=40)
    return root


def _open(repo: Path, name: str) -> None:
    """An open work branch: one commit that changes a file."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    (repo / f"{name}.txt").write_text(name)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", name, days_ago=1)
    _git(repo, "checkout", "-q", "main")


def _park(repo: Path, name: str, *, days_ago: float = 1) -> None:
    _git(repo, "checkout", "-q", name)
    _git(
        repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Park branch",
        "-m",
        "Parked-Reason: waiting\nParked-By: t",
        days_ago=days_ago,
    )
    _git(repo, "checkout", "-q", "main")


def _merged(repo: Path, name: str) -> None:
    _git(repo, "branch", name, "main")


def _config(**extra: Any) -> BranchesConfig:
    return BranchesConfig.model_validate(
        {
            "default": "main",
            "wip": {"cap": 50, "mode": "block", "count_remote": True},
            "duplicates": {"mode": "off"},
            **extra,
        }
    )


def _blocked_repo(
    repo: Path, state: str
) -> tuple[BranchesConfig, dict[str, dict[str, str | None]]]:
    """A repository in one blocked state; returns its config and labels snapshot."""
    labels: dict[str, dict[str, str | None]] = {}
    if state == RuleID.BRANCH_WIP_CAP:
        _open(repo, "one")
        _open(repo, "two")
        return (
            _config(wip={"cap": 2, "mode": "block", "count_remote": True, "creation_grace": 0}),
            labels,
        )
    if state == RuleID.BRANCH_DORMANT:
        _open(repo, "stale")
        labels["stale"] = {"group": "dormant", "action": None, "stage": "block"}
        return _config(), labels
    if state == RuleID.BRANCH_PARKED_POOL:
        _open(repo, "held")
        _park(repo, "held")
        return _config(parked={"cap": 1}), labels
    _merged(repo, "done")
    return _config(merged={"cap": 1}), labels


BLOCKED_STATES: Final[list[str]] = [
    RuleID.BRANCH_WIP_CAP,
    RuleID.BRANCH_DORMANT,
    RuleID.BRANCH_PARKED_POOL,
    RuleID.BRANCH_MERGED_POOL,
]


class TestReportAndVerdictAgree:
    @pytest.mark.parametrize("state", BLOCKED_STATES)
    def test_report_blocker_matches_the_verdict(self, repo: Path, state: str) -> None:
        config, labels = _blocked_repo(repo, state)
        report = creation_report(repo, config, "fresh", labels=labels, now=NOW)
        verdict = creation_verdict(repo, config, "fresh", labels=labels, now=NOW)
        assert verdict.decision == "deny"
        assert verdict.rule_id == state
        assert [b.rule_id for b in report.blockers] == [state]
        assert report.blockers[0].refuses is True
        assert verdict.lines == tuple(render_creation_report(report))

    @pytest.mark.parametrize("state", BLOCKED_STATES)
    def test_every_blocker_names_a_fix_command(self, repo: Path, state: str) -> None:
        config, labels = _blocked_repo(repo, state)
        report = creation_report(repo, config, "fresh", labels=labels, now=NOW)
        assert report.blockers[0].fixes, "a blocker without its exact command"
        text = "\n".join(render_creation_report(report))
        for fix in report.blockers[0].fixes:
            assert fix in text

    def test_a_clean_repository_has_no_blockers(self, repo: Path) -> None:
        report = creation_report(repo, _config(), "fresh", now=NOW)
        assert report.blockers == ()
        assert report.may_create is True

    def test_every_pool_is_listed_not_only_the_first_that_trips(self, repo: Path) -> None:
        _open(repo, "one")
        _open(repo, "two")
        _open(repo, "held")
        _park(repo, "held")
        _merged(repo, "done")
        config = _config(
            wip={"cap": 2, "mode": "block", "count_remote": True},
            parked={"cap": 1},
            merged={"cap": 1},
        )
        report = creation_report(repo, config, "fresh", now=NOW)
        assert [b.rule_id for b in report.blockers] == [
            RuleID.BRANCH_WIP_CAP,
            RuleID.BRANCH_PARKED_POOL,
            RuleID.BRANCH_MERGED_POOL,
        ]
        assert report.may_create is False

    def test_a_warn_mode_pool_is_listed_but_does_not_refuse(self, repo: Path) -> None:
        _merged(repo, "done")
        config = _config(merged={"cap": 1, "mode": "warn"})
        report = creation_report(repo, config, "fresh", now=NOW)
        assert [b.rule_id for b in report.blockers] == [RuleID.BRANCH_MERGED_POOL]
        assert report.blockers[0].refuses is False
        assert report.may_create is True

    def test_an_existing_branch_name_is_a_reset_not_a_creation(self, repo: Path) -> None:
        config, labels = _blocked_repo(repo, RuleID.BRANCH_WIP_CAP)
        report = creation_report(repo, config, "one", labels=labels, now=NOW)
        assert report.blockers == ()


class TestGuardDenyRendersTheReport:
    @pytest.mark.parametrize("state", BLOCKED_STATES)
    def test_deny_reason_contains_the_preflight_report(self, repo: Path, state: str) -> None:
        config, labels = _blocked_repo(repo, state)
        write_labels(
            repo / LABELS_RELATIVE_PATH,
            [
                {"name": name, "group": label["group"], "dormancy_stage": label["stage"]}
                for name, label in labels.items()
            ],
        )
        handler = BranchCreationGuardHandler()
        handler._branches = config
        handler._project_root_override = repo
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git switch -c fresh"},
            "cwd": str(repo),
        }
        result = handler.handle(hook_input)
        report = creation_report(
            repo, config, "fresh", labels=read_labels(repo / LABELS_RELATIVE_PATH)
        )
        assert result.decision == "deny"
        assert next(b.rule_id for b in report.blockers if b.refuses) == state
        assert "\n".join(render_creation_report(report)) in result.reason
        assert "branch-preflight" in result.reason
