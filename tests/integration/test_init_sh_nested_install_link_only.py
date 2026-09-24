"""`init.sh`'s nested-installation check, robust to a link-only inner dir (Plan 00455).

`init.sh` refuses to run when `.claude/hooks-daemon/.claude/hooks-daemon`
exists, on the theory that it can only mean a daemon once ran with the wrong
project root and wrote runtime artifacts one level too deep. The self-install
daemon now generates a bare `bin/hooks-daemon` symlink under its own
`.claude/hooks-daemon/` (Plan 00455 Task 1.3) -- so a developer running the
self-install daemon directly inside a CLIENT clone's own inner checkout
(`<client>/.claude/hooks-daemon/`, itself a full self-install-capable
checkout) creates exactly that path, as a link-only marker rather than a
genuine nested install.

Unlike the Python equivalent (`daemon/validation.py`'s
`check_for_nested_installation`), this check had NO exemption at all -- it
would refuse every hook event for the CLIENT project. The fix mirrors the
Python side's existing exemption: skip the refusal when the OUTER
`.claude/hooks-daemon/` is itself a real daemon clone (has `pyproject.toml`),
which is also the ordinary case for every ok client install with its own
dogfooded `.claude/` tree.
"""

from __future__ import annotations

import subprocess  # nosec B404 — runs the trusted system `git` and `bash`
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_INIT_SH: Final[Path] = _REPO_ROOT / ".claude" / "init.sh"

#: The error code `init.sh` emits for this specific refusal.
_NESTED_INSTALL_CODE: Final[str] = "nested_installation"

#: A remote that must NOT also trip the (unrelated, later) repo-detection guard,
#: so these tests exercise only the nested-install check.
_UNRELATED_REMOTE: Final[str] = "git@github.com:someone/an-ordinary-project.git"

_SOURCE_TIMEOUT_SECONDS: Final[int] = 30
_GIT_TIMEOUT_SECONDS: Final[int] = 30

_DAEMON_PYPROJECT: Final[str] = (
    '[project]\nname = "claude-code-hooks-daemon"\nversion = "1.0.0"\n'
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=True,
    )


def _throwaway_repo(tmp_path: Path) -> Path:
    """A git repo with an unrelated remote plus a COPY of the real `init.sh`.

    A copy, deliberately: `init.sh` derives `PROJECT_PATH` from `BASH_SOURCE`,
    so sourcing the real file would resolve to the real repository.
    """
    project = tmp_path / "project"
    claude_dir = project / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "init.sh").write_text(_INIT_SH.read_text(encoding="utf-8"), encoding="utf-8")

    _git(project, "init", "-q")
    _git(project, "remote", "add", "origin", _UNRELATED_REMOTE)
    return project


def _source(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["bash", "-c", f'source "{project / ".claude" / "init.sh"}"'],
        capture_output=True,
        text=True,
        timeout=_SOURCE_TIMEOUT_SECONDS,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(project)},
        check=False,
    )


class TestLinkOnlyInnerDirIsExempt:
    """The bug this plan fixes."""

    def test_a_link_only_inner_marker_does_not_refuse(self, tmp_path: Path) -> None:
        project = _throwaway_repo(tmp_path)
        outer = project / ".claude" / "hooks-daemon"
        (outer / "pyproject.toml").parent.mkdir(parents=True)
        (outer / "pyproject.toml").write_text(_DAEMON_PYPROJECT, encoding="utf-8")
        inner_bin = outer / ".claude" / "hooks-daemon" / "bin"
        inner_bin.mkdir(parents=True)
        (inner_bin / "hooks-daemon").symlink_to(outer / "bin" / "hooks-daemon")

        result = _source(project)

        combined = result.stdout + result.stderr
        assert _NESTED_INSTALL_CODE not in combined, (
            "init.sh refused a client project whose inner .claude/hooks-daemon "
            f"is only the self-install daemon's own generated marker: {combined!r}"
        )


class TestGenuineNestedInstallIsStillRefused:
    """Negative direction: a REAL nested install must still be caught."""

    def test_a_real_nested_clone_is_refused(self, tmp_path: Path) -> None:
        project = _throwaway_repo(tmp_path)
        outer = project / ".claude" / "hooks-daemon"
        # Outer has NO pyproject.toml: not a real clone, so the exemption must
        # not apply, and the inner structure is a genuine nested-install
        # artifact.
        inner = outer / ".claude" / "hooks-daemon"
        inner.mkdir(parents=True)

        result = _source(project)

        combined = result.stdout + result.stderr
        assert _NESTED_INSTALL_CODE in combined, (
            f"init.sh let a genuine nested installation through: {combined!r}"
        )

    def test_the_refusal_still_exits_successfully(self, tmp_path: Path) -> None:
        """Failing OPEN is the point: a hook must never block Claude Code."""
        project = _throwaway_repo(tmp_path)
        (project / ".claude" / "hooks-daemon" / ".claude" / "hooks-daemon").mkdir(
            parents=True
        )

        assert _source(project).returncode == 0


class TestNoNestedStructureAtAll:
    """Control: the common case, nothing under .claude/hooks-daemon/ yet."""

    def test_a_fresh_checkout_is_never_refused(self, tmp_path: Path) -> None:
        project = _throwaway_repo(tmp_path)

        result = _source(project)

        combined = result.stdout + result.stderr
        assert _NESTED_INSTALL_CODE not in combined, combined
