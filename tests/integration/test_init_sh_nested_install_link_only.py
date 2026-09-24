"""`init.sh`'s nested-installation check still fires with the generated link (Plan 00455).

`init.sh` refuses to run when `.claude/hooks-daemon/.claude/hooks-daemon`
exists. A CLIENT's clone never contains that path from cloning alone:
`.claude/hooks-daemon/` is gitignored by this repository's own
`.claude/.gitignore`, including inside the clone's own tracked `.claude/`
tree, so the clone carries no nested `hooks-daemon` directory at all. The
path can therefore only come into being at RUNTIME -- historically, a
daemon that started with the wrong project root and wrote runtime artifacts
one level too deep; now also a self-install daemon whose project root was
set to the CLIENT clone's own inner checkout
(`<client>/.claude/hooks-daemon/`), which is the identical wrong-root
pathology this check exists to flag. The self-install daemon's generated
`bin/hooks-daemon` symlink (Plan 00455 Task 1.3) makes that pathology
produce a link-only marker rather than daemon runtime files, but it is
still the SAME symptom of the SAME bug, and must still be reported.

An earlier revision of this plan added an exemption here (skip the refusal
when the outer `.claude/hooks-daemon/` has `pyproject.toml`, mirroring
`daemon/validation.py`'s `check_for_nested_installation`). That was wrong:
every REAL client clone has `pyproject.toml` at that path, so the exemption
would have silenced the check for every client, always -- it could never
fire again for a genuine nested installation either. Reverted; these tests
pin the check firing in exactly that "real clone, nested path present"
shape instead.
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

_DAEMON_PYPROJECT: Final[str] = '[project]\nname = "claude-code-hooks-daemon"\nversion = "1.0.0"\n'


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


class TestTheCheckStillFiresWithARealOuterClone:
    """The case an earlier revision of this plan wrongly exempted."""

    def test_a_link_only_inner_marker_under_a_real_clone_is_still_refused(
        self, tmp_path: Path
    ) -> None:
        """The self-install-in-the-wrong-place symptom must still be reported.

        Outer has `pyproject.toml` (a genuine client clone) AND the inner
        `.claude/hooks-daemon/` exists (here, a link-only marker -- what the
        self-install daemon now generates when run with its project root set
        to this exact wrong place). This is the wrong-root pathology the
        check exists to catch, so it must still refuse.
        """
        project = _throwaway_repo(tmp_path)
        outer = project / ".claude" / "hooks-daemon"
        (outer / "pyproject.toml").parent.mkdir(parents=True)
        (outer / "pyproject.toml").write_text(_DAEMON_PYPROJECT, encoding="utf-8")
        inner_bin = outer / ".claude" / "hooks-daemon" / "bin"
        inner_bin.mkdir(parents=True)
        (inner_bin / "hooks-daemon").symlink_to(outer / "bin" / "hooks-daemon")

        result = _source(project)

        combined = result.stdout + result.stderr
        assert _NESTED_INSTALL_CODE in combined, (
            "init.sh let the wrong-root pathology through: a real clone with a "
            f"link-only marker one level too deep should still be refused: {combined!r}"
        )


class TestGenuineNestedInstallIsStillRefused:
    """The check's original coverage: a REAL nested install must still be caught."""

    def test_a_real_nested_clone_is_refused(self, tmp_path: Path) -> None:
        project = _throwaway_repo(tmp_path)
        outer = project / ".claude" / "hooks-daemon"
        inner = outer / ".claude" / "hooks-daemon"
        inner.mkdir(parents=True)

        result = _source(project)

        combined = result.stdout + result.stderr
        assert (
            _NESTED_INSTALL_CODE in combined
        ), f"init.sh let a genuine nested installation through: {combined!r}"

    def test_the_refusal_still_exits_successfully(self, tmp_path: Path) -> None:
        """Failing OPEN is the point: a hook must never block Claude Code."""
        project = _throwaway_repo(tmp_path)
        (project / ".claude" / "hooks-daemon" / ".claude" / "hooks-daemon").mkdir(parents=True)

        assert _source(project).returncode == 0


class TestNoNestedStructureAtAll:
    """Control: the common case, nothing under .claude/hooks-daemon/ yet."""

    def test_a_fresh_checkout_is_never_refused(self, tmp_path: Path) -> None:
        project = _throwaway_repo(tmp_path)

        result = _source(project)

        combined = result.stdout + result.stderr
        assert _NESTED_INSTALL_CODE not in combined, combined
