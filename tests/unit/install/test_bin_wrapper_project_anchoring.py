"""The wrapper must manage ITS OWN project's daemon, whatever the CWD.

Plan 00194. ``bin/hooks-daemon`` resolves its INTERPRETER from its own location,
but the daemon it then MANAGES (socket/PID/log) was chosen by the CLI from the
CURRENT WORKING DIRECTORY. The two anchors disagreed, so the same wrapper
invoked by absolute path from two directories acted on two different daemons.

Observed twice for real:

- Plan 00193 Phase 4 — running the client fixture's wrapper from ``/workspace``
  restarted the DOGFOOD daemon (PID 1186876 -> 1203331) with no warning.
- Plan 00193 Task 6.7 — an unanchored ``stop`` resolved the wrong project, said
  "Daemon not running", exited 0, and teardown deleted the fixture tree around a
  live daemon while reporting success.

These tests run the real wrapper against a stub interpreter that echoes its
argv, so they assert the ACTUAL command the wrapper builds rather than trusting
a reading of the shell.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.install import bin_wrapper

#: Stub resolver: the wrapper sources this and calls resolve_venv_python.
_RESOLVER_STUB: Final[str] = """#!/bin/bash
resolve_venv_python() {
    printf '%s\\n' "$1/stub-python"
}
"""

#: Stub interpreter: echoes the argv the wrapper exec'd it with.
_PYTHON_STUB: Final[str] = """#!/bin/bash
printf '%s\\n' "$@"
"""

_PROJECT_ROOT_FLAG: Final[str] = "--project-root"

#: Subprocess timeout for a stub that only echoes — generous, but bounded so a
#: hung shell fails the suite instead of stalling it.
_STUB_TIMEOUT_SECONDS: Final[int] = 30


def _build_daemon_tree(daemon_dir: Path) -> Path:
    """Lay out a minimal daemon root the wrapper can run from.

    Returns the deployed wrapper path.
    """
    wrapper = bin_wrapper.deploy_bin_wrapper(daemon_dir)

    lib_dir = daemon_dir / "scripts" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    resolver = lib_dir / "resolve_venv.sh"
    resolver.write_text(_RESOLVER_STUB, encoding="utf-8")
    resolver.chmod(0o755)

    stub_python = daemon_dir / "stub-python"
    stub_python.write_text(_PYTHON_STUB, encoding="utf-8")
    stub_python.chmod(0o755)

    return wrapper


def _client_project(root: Path) -> Path:
    """Create a CLIENT-mode project at ``root``; return its wrapper path."""
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    return _build_daemon_tree(root / ".claude" / "hooks-daemon")


def _self_install_project(root: Path) -> Path:
    """Create a SELF-INSTALL project at ``root``; return its wrapper path."""
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    return _build_daemon_tree(root)


def _run(wrapper: Path, cwd: Path, *args: str) -> list[str]:
    """Invoke the wrapper from ``cwd`` and return the argv it exec'd.

    SECURITY: fixed argv built from test-local tmp_path fixtures; no shell and
    no external input.
    """
    result = subprocess.run(
        [str(wrapper), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_STUB_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, f"wrapper failed: {result.stderr}"
    return result.stdout.splitlines()


def _anchored_root(argv: list[str]) -> str | None:
    """Return the LAST --project-root value in argv, or None.

    Last, not first: argparse takes the final occurrence, so that is the value
    that actually determines the target.
    """
    values = [
        argv[index + 1]
        for index, token in enumerate(argv)
        if token == _PROJECT_ROOT_FLAG and index + 1 < len(argv)
    ]
    return values[-1] if values else None


class TestWrapperAnchorsToItsOwnProject:
    """A wrapper's identity, not the caller's CWD, selects the daemon."""

    def test_client_wrapper_run_from_elsewhere_targets_its_own_project(
        self, tmp_path: Path
    ) -> None:
        """THE regression: fixture wrapper + dogfood CWD restarted the dogfood daemon."""
        mine = tmp_path / "mine"
        other = tmp_path / "other"
        wrapper = _client_project(mine)
        _client_project(other)

        argv = _run(wrapper, other, "status")

        assert _anchored_root(argv) == str(mine.resolve()), (
            f"wrapper at {wrapper} run from {other} did not anchor to its own "
            f"project. argv={argv}"
        )

    def test_self_install_wrapper_run_from_elsewhere_targets_its_own_project(
        self, tmp_path: Path
    ) -> None:
        mine = tmp_path / "selfinstall"
        other = tmp_path / "other"
        wrapper = _self_install_project(mine)
        _client_project(other)

        argv = _run(wrapper, other, "status")

        assert _anchored_root(argv) == str(mine.resolve())

    def test_same_wrapper_targets_the_same_project_from_any_cwd(self, tmp_path: Path) -> None:
        """The core contract, stated directly."""
        mine = tmp_path / "mine"
        other = tmp_path / "other"
        wrapper = _client_project(mine)
        _client_project(other)

        from_own = _anchored_root(_run(wrapper, mine, "status"))
        from_other = _anchored_root(_run(wrapper, other, "status"))

        assert from_own == from_other == str(mine.resolve())

    def test_worktree_wrapper_targets_the_worktree_not_the_main_repo(self, tmp_path: Path) -> None:
        """Task 2.3: a worktree's own wrapper manages the worktree's daemon.

        Plan 00193 wrote "use the worktree's own wrapper" into Worktree.md; that
        guidance only holds if the wrapper's identity determines the target.
        """
        main_repo = tmp_path / "main"
        worktree = tmp_path / "main" / ".claude" / "worktrees" / "feature-abc123"
        main_wrapper = _self_install_project(main_repo)
        worktree_wrapper = _self_install_project(worktree)

        # Each wrapper invoked from the OTHER's directory.
        assert _anchored_root(_run(worktree_wrapper, main_repo, "status")) == str(
            worktree.resolve()
        )
        assert _anchored_root(_run(main_wrapper, worktree, "status")) == str(main_repo.resolve())


class TestExplicitOverrideStillWins:
    """Precedence (Task 1.3): explicit --project-root beats the derived anchor."""

    def test_caller_supplied_project_root_is_last(self, tmp_path: Path) -> None:
        """argparse takes the last occurrence, so the caller's must come after."""
        mine = tmp_path / "mine"
        chosen = tmp_path / "chosen"
        wrapper = _client_project(mine)
        _client_project(chosen)

        argv = _run(wrapper, mine, _PROJECT_ROOT_FLAG, str(chosen), "status")

        assert _anchored_root(argv) == str(
            chosen
        ), f"an explicit --project-root must override the derived anchor. argv={argv}"

    def test_all_user_arguments_are_preserved(self, tmp_path: Path) -> None:
        """Injection must not drop, reorder or mangle the caller's own argv."""
        mine = tmp_path / "mine"
        wrapper = _client_project(mine)

        argv = _run(wrapper, mine, "plan-qa", "--sweep", "--json")

        # The subcommand and its flags survive, in order, at the end.
        assert argv[-3:] == ["plan-qa", "--sweep", "--json"]


class TestDoesNotBreakUnanchorableLayouts:
    """Fail-safe: never inject an anchor that would break a working caller."""

    def test_no_anchor_injected_when_derived_root_is_not_a_project(self, tmp_path: Path) -> None:
        """A daemon tree with no .claude at its derived root keeps CWD behaviour.

        Injecting a --project-root that fails validation would turn a working
        invocation into a hard error. Absent a usable anchor, defer to the CLI's
        existing CWD walk-up and its existing diagnostics.
        """
        stray = tmp_path / "stray"
        wrapper = _build_daemon_tree(stray)  # no .claude anywhere
        caller = tmp_path / "caller"
        _client_project(caller)

        argv = _run(wrapper, caller, "status")

        assert (
            _anchored_root(argv) is None
        ), f"wrapper injected an unusable anchor instead of deferring. argv={argv}"


class TestBothCopiesStayIdentical:
    """The template and the deployed self-install copy must not drift."""

    def test_repo_wrapper_matches_template(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        deployed = repo_root / "bin" / "hooks-daemon"
        if not deployed.is_file():
            return
        template = bin_wrapper.wrapper_template_path().read_text(encoding="utf-8")
        assert deployed.read_text(encoding="utf-8") == template

    def test_bash_is_available_for_these_tests(self) -> None:
        """Guard: these tests are meaningless without a shell to run."""
        assert shutil.which("bash") is not None
