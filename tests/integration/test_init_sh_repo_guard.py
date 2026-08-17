"""`init.sh`'s repo-detection guard, pinned in both directions (Plan 00245).

`init.sh` refuses to run inside the hooks-daemon repo unless self-install is
evident. That guard is correct and protects a client install from a
half-configured self-install — but the way it is SATISFIED was never asserted,
and one of the two ways is an untracked file.

The guard accepts either:

1. `HOOKS_DAEMON_ROOT_DIR == PROJECT_PATH`, or
2. the presence of `<PROJECT_PATH>/.claude/hooks-daemon.env`.

Option 2 is GITIGNORED (`.claude/.gitignore`). So every test that sourced the
real `init.sh` cleared the guard by accident on a self-installed developer tree,
and died with `hooks_daemon_repo_detected` on a fresh checkout. GitHub Actions
failed on every push for 25+ consecutive runs, ~63 tests per interpreter, while
the same tests passed locally — and because CI was uniformly red, nothing
distinguished that from the noise.

These tests use a THROWAWAY repo rather than the real one, so they assert the
contract instead of inheriting whichever half of it this working tree happens to
satisfy. A test that can only pass on a self-installed tree is the defect being
guarded against; it must not be the guard.
"""

from __future__ import annotations

import subprocess  # nosec B404 — runs the trusted system `git` and `bash`
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_INIT_SH: Final[Path] = _REPO_ROOT / ".claude" / "init.sh"

#: The error code `init.sh` emits when it decides it is in the hooks-daemon repo
#: without self-install evidence.
_REPO_DETECTED_CODE: Final[str] = "hooks_daemon_repo_detected"

#: A remote URL that trips `is_hooks_daemon_repo`, and one that must not.
_HOOKS_DAEMON_REMOTE: Final[str] = (
    "git@github.com:Edmonds-Commerce-Limited/claude-code-hooks-daemon.git"
)
_UNRELATED_REMOTE: Final[str] = "git@github.com:someone/an-ordinary-project.git"

_SOURCE_TIMEOUT_SECONDS: Final[int] = 30
_GIT_TIMEOUT_SECONDS: Final[int] = 30

#: `init.sh` emits its diagnostic and then exits SUCCESSFULLY, so that a hook
#: failing open never blocks Claude Code. The exit status therefore says nothing
#: about which branch was taken — only the emitted code does.
_FAIL_OPEN_EXIT: Final[int] = 0


def _git(repo: Path, *args: str) -> None:
    """Run a git command in `repo`, failing the test on a non-zero exit."""
    subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=True,
    )


def _throwaway_repo(tmp_path: Path, remote_url: str) -> Path:
    """A git repo carrying `remote_url` plus a COPY of the real `init.sh`.

    A copy, deliberately: `init.sh` derives `PROJECT_PATH` from `BASH_SOURCE`, so
    sourcing the real file would resolve to the real repository and re-introduce
    exactly the ambient dependency these tests exist to remove.
    """
    project = tmp_path / "project"
    claude_dir = project / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "init.sh").write_text(_INIT_SH.read_text(encoding="utf-8"), encoding="utf-8")

    _git(project, "init", "-q")
    _git(project, "remote", "add", "origin", remote_url)
    return project


def _source(project: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Source the project's `init.sh` and report what it emitted."""
    return subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["bash", "-c", f'source "{project / ".claude" / "init.sh"}"'],
        capture_output=True,
        text=True,
        timeout=_SOURCE_TIMEOUT_SECONDS,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(project), **(env or {})},
        check=False,
    )


class TestGuardFiresWithoutSelfInstallEvidence:
    """The protective half of the contract."""

    def test_repo_with_neither_signal_is_refused(self, tmp_path: Path) -> None:
        """No `.env` and no matching root dir: the guard must fire.

        This is precisely the CI condition — a fresh checkout of this repo has
        no `.claude/hooks-daemon.env`, because it is gitignored.
        """
        project = _throwaway_repo(tmp_path, _HOOKS_DAEMON_REMOTE)

        result = _source(project)

        combined = result.stdout + result.stderr
        assert _REPO_DETECTED_CODE in combined, (
            "init.sh did not refuse a hooks-daemon repo lacking self-install "
            f"evidence. Emitted instead: {combined!r}"
        )

    def test_the_refusal_still_exits_successfully(self, tmp_path: Path) -> None:
        """Failing OPEN is the point: a hook must never block Claude Code.

        Pinned separately from the message because the two are independent — a
        change that made the refusal exit non-zero would turn a diagnostic into
        a broken hook, and the message assertion alone would not notice.
        """
        project = _throwaway_repo(tmp_path, _HOOKS_DAEMON_REMOTE)

        assert _source(project).returncode == _FAIL_OPEN_EXIT


class TestEitherSignalSatisfiesTheGuard:
    """The two ways through, asserted independently.

    Both are pinned because the tests that broke in CI relied on the untracked
    one WITHOUT SAYING SO. Naming each separately means a change that removes
    either is a named failure rather than a silent narrowing.
    """

    def test_root_dir_equal_to_project_path_is_enough(self, tmp_path: Path) -> None:
        """The tracked, explicit signal — what the Phase 1 fix relies on."""
        project = _throwaway_repo(tmp_path, _HOOKS_DAEMON_REMOTE)

        result = _source(project, {"HOOKS_DAEMON_ROOT_DIR": str(project)})

        combined = result.stdout + result.stderr
        assert _REPO_DETECTED_CODE not in combined, (
            "HOOKS_DAEMON_ROOT_DIR == PROJECT_PATH no longer satisfies the "
            f"guard, so the Phase 1 fix is inert. Emitted: {combined!r}"
        )

    def test_an_env_file_is_enough(self, tmp_path: Path) -> None:
        """The untracked signal, which a real self-install tree has."""
        project = _throwaway_repo(tmp_path, _HOOKS_DAEMON_REMOTE)
        (project / ".claude" / "hooks-daemon.env").write_text(
            f'export HOOKS_DAEMON_ROOT_DIR="{project}"\n', encoding="utf-8"
        )

        result = _source(project)

        combined = result.stdout + result.stderr
        assert _REPO_DETECTED_CODE not in combined, combined


class TestTheGuardIsScopedToThisRepository:
    """Control: without it, every assertion above could pass vacuously.

    If the guard fired for ANY repository, `test_repo_with_neither_signal_is_refused`
    would pass while the guard was hopelessly broad — and every client install
    would be bricked.
    """

    def test_an_unrelated_remote_is_never_refused(self, tmp_path: Path) -> None:
        project = _throwaway_repo(tmp_path, _UNRELATED_REMOTE)

        result = _source(project)

        combined = result.stdout + result.stderr
        assert _REPO_DETECTED_CODE not in combined, (
            "init.sh refused a project whose remote is not the hooks-daemon "
            f"repo. That would break ordinary client installs. Emitted: {combined!r}"
        )
