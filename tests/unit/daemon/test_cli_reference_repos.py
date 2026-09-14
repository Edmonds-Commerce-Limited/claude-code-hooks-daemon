"""The ``reference-repos`` CLI subcommand (Plan 00401 Task 5.1).

This is the surface the other two POINT AT: the SessionStart sweep and the
PreToolUse gate both print "run `hooks-daemon reference-repos`" as the way out of
a NOT VERIFIED verdict. That makes one behaviour non-negotiable and easy to miss
— ``test_running_it_clears_a_not_verified_verdict``. If the command reported
without writing the cache, following the advice would change nothing, and the
next read would be told again to run the command that just ran.

The exit code is the CI contract: non-zero when any governed repo is stale or
off its default branch, zero when the only findings are repos nobody CAN check.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_reference_repos
from claude_code_hooks_daemon.reference_repos.cache import cached_states
from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState
from claude_code_hooks_daemon.reference_repos.refresh import RefreshOutcome


def _args(
    project_root: Path, *, json_output: bool = False, show_all: bool = False
) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=str(project_root),
        json_output=json_output,
        show_all=show_all,
    )


def _project(tmp_path: Path, *, config: str = "") -> Path:
    root = tmp_path / "repo"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "hooks-daemon.yaml").write_text(
        f"version: '2.0'\n{config}", encoding="utf-8"
    )
    # Self-install marker so the untracked dir resolves under the project.
    (root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    return root


def _repo(root: Path, name: str = "alpha") -> Path:
    path = root / "untracked" / "repos" / name
    (path / ".git").mkdir(parents=True)
    return path


def _state(
    path: Path,
    *,
    behind: int = 0,
    branch: str = "main",
    checkability: Checkability = Checkability.CHECKABLE,
) -> RepoState:
    return RepoState(
        path=path,
        checkability=checkability,
        branch=branch,
        default_branch="main",
        upstream="origin/main",
        behind=behind,
        ahead=0,
        dirty=False,
    )


@pytest.fixture
def stub_refresh(monkeypatch: pytest.MonkeyPatch):
    """Replace the only module that touches the network."""

    def _install(**by_name: RepoState) -> list[bool]:
        seen: list[bool] = []

        def _refresh(path: Path, *, allow_pull: bool = True) -> RefreshOutcome:
            seen.append(allow_pull)
            state = by_name.get(path.name, _state(path))
            return RefreshOutcome(state=state, fetched=True, pulled=False, detail="ok")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.reference_repos.refresh.refresh_repo", _refresh
        )
        return seen

    return _install


class TestExitCodes:
    def test_all_current_exits_zero(
        self, tmp_path: Path, stub_refresh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path)
        _repo(root)
        stub_refresh()

        assert cmd_reference_repos(_args(root)) == 0
        assert "up to date" in capsys.readouterr().out

    def test_a_stale_repo_exits_one(
        self, tmp_path: Path, stub_refresh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path)
        repo = _repo(root)
        stub_refresh(alpha=_state(repo, behind=3))

        assert cmd_reference_repos(_args(root)) == 1
        assert "alpha" in capsys.readouterr().out

    def test_a_repo_off_its_default_branch_exits_one(self, tmp_path: Path, stub_refresh) -> None:
        root = _project(tmp_path)
        repo = _repo(root)
        stub_refresh(alpha=_state(repo, branch="feature"))

        assert cmd_reference_repos(_args(root)) == 1

    def test_an_uncheckable_repo_alone_exits_zero(self, tmp_path: Path, stub_refresh) -> None:
        """The canary must never fail a CI run.

        Its origin is invalid BY DESIGN, so a non-zero exit here would make the
        command permanently red for a state nobody intends to fix.
        """
        root = _project(tmp_path)
        repo = _repo(root, "php-qa-ci")
        stub_refresh(**{"php-qa-ci": _state(repo, checkability=Checkability.NO_REMOTE)})

        assert cmd_reference_repos(_args(root)) == 0

    def test_a_project_governing_nothing_exits_zero(self, tmp_path: Path, stub_refresh) -> None:
        root = _project(tmp_path)
        stub_refresh()

        assert cmd_reference_repos(_args(root)) == 0

    def test_a_missing_project_root_exits_two(self, tmp_path: Path) -> None:
        assert cmd_reference_repos(_args(tmp_path / "nope")) == 2


class TestItIsTheRemedyItAdvertises:
    def test_running_it_clears_a_not_verified_verdict(self, tmp_path: Path, stub_refresh) -> None:
        """Both other surfaces tell the reader to run this command.

        If it reported without writing the cache, following that advice would
        change nothing and the next read would repeat the same instruction.
        """
        root = _project(tmp_path)
        repo = _repo(root)
        stub_refresh()

        assert cached_states(root) is None

        cmd_reference_repos(_args(root))

        cached = cached_states(root)
        assert cached is not None
        assert repo in cached

    def test_the_cached_reading_is_the_state_after_refreshing(
        self, tmp_path: Path, stub_refresh
    ) -> None:
        root = _project(tmp_path)
        repo = _repo(root)
        stub_refresh(alpha=_state(repo, behind=5))

        cmd_reference_repos(_args(root))

        cached = cached_states(root)
        assert cached is not None
        assert cached[repo].behind == 5


class TestReportContent:
    def test_a_stale_repo_gets_a_runnable_fix_command(
        self, tmp_path: Path, stub_refresh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path)
        repo = _repo(root)
        stub_refresh(alpha=_state(repo, behind=2))

        cmd_reference_repos(_args(root))

        assert "pull --ff-only" in capsys.readouterr().out

    def test_uncheckable_repos_are_counted_not_hidden(
        self, tmp_path: Path, stub_refresh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Silence about a repo in a report you ASKED for reads as 'it is fine'.

        The sweep can stay quiet about an un-checkable clone because it speaks
        unprompted; a command answering a direct question cannot.
        """
        root = _project(tmp_path)
        good = _repo(root, "alpha")
        canary = _repo(root, "php-qa-ci")
        stub_refresh(
            alpha=_state(good),
            **{"php-qa-ci": _state(canary, checkability=Checkability.NO_REMOTE)},
        )

        cmd_reference_repos(_args(root))

        assert "not checkable" in capsys.readouterr().out

    def test_show_all_lists_every_governed_repo(
        self, tmp_path: Path, stub_refresh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--all is how you find out WHICH repo the count referred to."""
        root = _project(tmp_path)
        good = _repo(root, "alpha")
        canary = _repo(root, "php-qa-ci")
        stub_refresh(
            alpha=_state(good),
            **{"php-qa-ci": _state(canary, checkability=Checkability.NO_REMOTE)},
        )

        cmd_reference_repos(_args(root, show_all=True))

        out = capsys.readouterr().out
        assert "alpha" in out
        assert "php-qa-ci" in out
        assert "no remote configured" in out

    def test_the_report_is_not_truncated(
        self, tmp_path: Path, stub_refresh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """SessionStart caps the list; a report you asked for shows everything."""
        root = _project(tmp_path)
        states = {}
        for index in range(30):
            repo = _repo(root, f"r{index}")
            states[f"r{index}"] = _state(repo, behind=1)
        stub_refresh(**states)

        cmd_reference_repos(_args(root))

        out = capsys.readouterr().out
        assert "more" not in out
        assert "r29" in out


class TestJsonOutput:
    def test_json_is_machine_readable(
        self, tmp_path: Path, stub_refresh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path)
        repo = _repo(root)
        stub_refresh(alpha=_state(repo, behind=3))

        cmd_reference_repos(_args(root, json_output=True))

        payload = json.loads(capsys.readouterr().out)
        assert payload["needs_attention"] == 1
        assert payload["checked"] == 1
        assert payload["repos"][0]["behind"] == 3

    def test_json_carries_the_remediation_command(
        self, tmp_path: Path, stub_refresh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A consumer should not have to re-derive the remedy from the fields."""
        root = _project(tmp_path)
        repo = _repo(root)
        stub_refresh(alpha=_state(repo, behind=3))

        cmd_reference_repos(_args(root, json_output=True))

        payload = json.loads(capsys.readouterr().out)
        assert "pull --ff-only" in payload["repos"][0]["remediation"]

    def test_json_lists_every_repo_including_uncheckable_ones(
        self, tmp_path: Path, stub_refresh, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Machine output is never the truncated view."""
        root = _project(tmp_path)
        good = _repo(root, "alpha")
        canary = _repo(root, "php-qa-ci")
        stub_refresh(
            alpha=_state(good),
            **{"php-qa-ci": _state(canary, checkability=Checkability.NO_REMOTE)},
        )

        cmd_reference_repos(_args(root, json_output=True))

        payload = json.loads(capsys.readouterr().out)
        assert {entry["path"].split("/")[-1] for entry in payload["repos"]} == {
            "alpha",
            "php-qa-ci",
        }


class TestConfiguration:
    def test_a_disabled_feature_reports_and_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _project(tmp_path, config="reference_repos:\n  enabled: false\n")
        _repo(root)

        assert cmd_reference_repos(_args(root)) == 0
        assert "disabled" in capsys.readouterr().out

    def test_auto_pull_config_reaches_the_refresher(self, tmp_path: Path, stub_refresh) -> None:
        """One config feeds all three surfaces, so the CLI must honour it too."""
        root = _project(tmp_path, config="reference_repos:\n  auto_pull: false\n")
        _repo(root)
        seen = stub_refresh()

        cmd_reference_repos(_args(root))

        assert seen == [False]

    def test_a_custom_root_is_swept(self, tmp_path: Path, stub_refresh) -> None:
        root = _project(tmp_path, config="reference_repos:\n  roots:\n    - vendor\n")
        repo = root / "vendor" / "upstream"
        (repo / ".git").mkdir(parents=True)
        stub_refresh()

        cmd_reference_repos(_args(root))

        cached = cached_states(root)
        assert cached is not None
        assert repo in cached
