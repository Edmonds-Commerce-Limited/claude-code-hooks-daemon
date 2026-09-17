"""The worktree socket-path pre-flight must not need a venv to do arithmetic.

`scripts/setup_worktree.sh` refuses to create a worktree whose prospective
daemon socket path would exceed the AF_UNIX cap, because exceeding it is
SILENT: the daemon still starts, relocates its runtime files to `/tmp`, and the
acceptance gates then report "no live socket found under `untracked/`" with a
restart instruction that cannot fix it.

The guard fails OPEN when it cannot measure, which is right — a broken checker
must not block worktree creation. The route into that fallback was not: it
resolved a VENV Python in order to call the daemon's measurement helpers, and a
worktree created from inside another worktree has no venv yet. That is exactly
where paths get long enough to matter, so the guard was inert in the case that
motivated it and healthy everywhere else, reporting `✓ Socket path fits` on
every short path anyone tested it against (Plan 00422 N8, Plan 00431).

`daemon/paths.py` is stdlib-only, so loading that FILE under the system
`python3` runs the real helpers against the real `_UNIX_SOCKET_PATH_LIMIT` with
no venv and no second copy of the limit.

The tests below are one set deliberately: that it REFUSES an over-cap path with
no venv, that it still ACCEPTS a short one there (or a guard that merely always
blocks would pass the first), that the limit it reports is the daemon's own
constant, and that it still fails open when the measurement is genuinely
unavailable.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SETUP_WORKTREE: Final[Path] = _REPO_ROOT / "scripts" / "setup_worktree.sh"

_FUNCTION_OPEN: Final[str] = "preflight_socket_path() {"
_FUNCTION_CLOSE: Final[str] = "}"

#: A stub for the venv resolver that always fails, which is what a fresh
#: worktree's own `untracked/` produces. A fixed pre-flight never calls it —
#: that is the point. It stays because the tests must keep asking the question
#: in the environment that broke, not in one where a venv happens to resolve.
_NO_VENV_STUB: Final[str] = "resolve_venv_python() { return 1; }\n"


def _preflight_function_source() -> str:
    """The `preflight_socket_path` definition, lifted out of the setup script.

    Sourcing the whole script is not an option — it validates arguments and
    creates a worktree at the top level — so the function is sliced out by its
    opening line and the first close brace in column one.
    """
    lines = _SETUP_WORKTREE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(_FUNCTION_OPEN))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == _FUNCTION_CLOSE)
    return "\n".join(lines[start : end + 1]) + "\n"


def _run_preflight(project_root: Path, worktree_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run the pre-flight with no resolvable venv, as a nested worktree has."""
    script = (
        "set -uo pipefail\n"
        "RED=''\nGREEN=''\nYELLOW=''\nNC=''\n"
        f'PROJECT_ROOT="{project_root}"\n'
        f"{_preflight_function_source()}"
        f"{_NO_VENV_STUB}"
        f'preflight_socket_path "{worktree_dir}"\n'
    )
    return subprocess.run(  # nosec B603 B607 - fixed argv, repo-internal script text
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        cwd=_REPO_ROOT,
    )


def _over_cap_worktree_dir() -> Path:
    """A worktree path whose socket path is comfortably past the AF_UNIX cap.

    Built from the real limit rather than a literal, so a platform with a
    different cap still gets an over-cap path rather than a passing test.
    """
    from claude_code_hooks_daemon.daemon.paths import _UNIX_SOCKET_PATH_LIMIT

    return _REPO_ROOT / "untracked" / "worktrees" / ("worktree-" + "x" * _UNIX_SOCKET_PATH_LIMIT)


class TestThePreflightMeasuresWithoutAVenv:
    def test_it_refuses_an_over_cap_path_when_no_venv_resolves(self) -> None:
        """The case the guard exists for, in the environment it is used in."""
        result = _run_preflight(_REPO_ROOT, _over_cap_worktree_dir())

        assert result.returncode == 1, (
            "The pre-flight allowed an over-cap socket path because no venv "
            "resolved. A worktree created from inside another worktree has no "
            "venv, and that is precisely where the path is long enough to "
            "matter, so this is the guard standing down in the only case it "
            "was built for.\n\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "over the limit" in result.stdout, result.stdout

    def test_it_still_accepts_a_short_path_when_no_venv_resolves(self) -> None:
        """Control: a guard that always refused would pass the test above."""
        result = _run_preflight(_REPO_ROOT, _REPO_ROOT / "untracked" / "worktrees" / "worktree-a")

        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "Socket path fits" in result.stdout, result.stdout

    def test_it_reads_the_limit_from_the_daemons_own_constant(self) -> None:
        """The reported limit is the real one, not a number copied into bash."""
        from claude_code_hooks_daemon.daemon.paths import _UNIX_SOCKET_PATH_LIMIT

        result = _run_preflight(_REPO_ROOT, _REPO_ROOT / "untracked" / "worktrees" / "worktree-a")

        assert f"/{_UNIX_SOCKET_PATH_LIMIT} bytes" in result.stdout, result.stdout


class TestThePreflightStillFailsOpenWhenItGenuinelyCannotMeasure:
    def test_a_root_without_paths_py_is_allowed_through(self, tmp_path: Path) -> None:
        """Blocking worktree creation because a checker is broken is worse.

        The fallback is kept deliberately; this plan narrows WHEN it is reached,
        it does not remove it.
        """
        result = _run_preflight(tmp_path, tmp_path / "worktree-a")

        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "could not" in result.stdout.lower(), (
            "Failing open is fine; failing open SILENTLY is how N8 went "
            f"unnoticed for hours.\nstdout:\n{result.stdout}"
        )


_NESTING_FUNCTION_OPEN: Final[str] = "preflight_not_nested() {"


def _nesting_function_source() -> str:
    """The `preflight_not_nested` definition, lifted out the same way."""
    lines = _SETUP_WORKTREE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(_NESTING_FUNCTION_OPEN))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == _FUNCTION_CLOSE)
    return "\n".join(lines[start : end + 1]) + "\n"


def _run_nesting_guard(project_root: Path) -> subprocess.CompletedProcess[str]:
    script = (
        "set -uo pipefail\n"
        "RED=''\nGREEN=''\nYELLOW=''\nNC=''\n"
        f'PROJECT_ROOT="{project_root}"\n'
        # Set the way the script itself sets them, well before this runs: the
        # refusal quotes them back as the command to run in the outer checkout.
        'BRANCH_NAME="worktree-probe"\n'
        'BASE_BRANCH=""\n'
        f"{_nesting_function_source()}"
        "preflight_not_nested\n"
    )
    return subprocess.run(  # nosec B603 B607 - fixed argv, repo-internal script text
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        cwd=_REPO_ROOT,
    )


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["git", *args], cwd=cwd, check=True, capture_output=True
    )


def _repo_with_a_linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A throwaway repository and a worktree linked to it."""
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "--quiet", ".", cwd=main)
    _git("config", "user.email", "test@example.com", cwd=main)
    _git("config", "user.name", "test", cwd=main)
    (main / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git("add", "seed.txt", cwd=main)
    _git("commit", "--quiet", "-m", "seed", cwd=main)

    linked = tmp_path / "linked"
    _git("worktree", "add", "--detach", "--quiet", str(linked), "HEAD", cwd=main)
    return main, linked


class TestTheSetupScriptRefusesToNestAWorktreeInsideAWorktree:
    """A worktree carries the whole tree, `scripts/` included.

    So running the copy that is right there is the natural thing to do — and
    `PROJECT_ROOT` comes from the script's own location, so the new worktree
    lands under the INNER checkout. The path length is the visible half, and the
    socket pre-flight above now catches that; the expensive half is work landing
    on a branch inside a tree the coordinator later reaps (Plan 00422 N9).
    """

    def test_it_refuses_when_run_from_inside_a_linked_worktree(self, tmp_path: Path) -> None:
        _main, linked = _repo_with_a_linked_worktree(tmp_path)

        result = _run_nesting_guard(linked)

        assert result.returncode == 1, (
            "The setup script allowed itself to run from inside a linked "
            "worktree, which nests the new one under the inner checkout.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_the_refusal_names_the_enclosing_checkout(self, tmp_path: Path) -> None:
        """'You are nested' is not actionable; the outer path is."""
        main, linked = _repo_with_a_linked_worktree(tmp_path)

        result = _run_nesting_guard(linked)

        assert str(main.resolve()) in result.stdout, (
            f"the refusal did not name {main}, so the reader still has to work "
            f"out where to run it instead.\nstdout:\n{result.stdout}"
        )

    def test_a_normal_checkout_is_allowed_through(self, tmp_path: Path) -> None:
        """Control: a guard that refused everywhere would pass the tests above.

        This is also the documented child-worktree workflow's path — a child is
        created from the MAIN checkout with a parent base branch.
        """
        main, _linked = _repo_with_a_linked_worktree(tmp_path)

        result = _run_nesting_guard(main)

        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    def test_a_directory_that_is_not_a_repository_fails_open(self, tmp_path: Path) -> None:
        """A checker that cannot reach a verdict must not block creation.

        The same judgement the socket pre-flight makes, for the same reason —
        and it says so rather than passing silently.
        """
        result = _run_nesting_guard(tmp_path)

        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "could not" in result.stdout.lower(), result.stdout


class TestTheExtractionItself:
    def test_the_function_is_still_in_the_script(self) -> None:
        """Control: a rename must fail loudly, not quietly check nothing."""
        assert _FUNCTION_OPEN in _SETUP_WORKTREE.read_text(encoding="utf-8"), (
            f"{_SETUP_WORKTREE} no longer defines {_FUNCTION_OPEN!r}, which is "
            f"how every test above finds the code it exercises."
        )

    def test_the_extracted_source_is_a_complete_function(self) -> None:
        """A slice that stopped at the wrong brace would not even parse."""
        source = _preflight_function_source()
        parsed = subprocess.run(  # nosec B603 B607 - fixed argv, repo-internal script text
            ["bash", "-n", "-c", source],
            capture_output=True,
            text=True,
            check=False,
        )
        assert parsed.returncode == 0, f"{source}\n{parsed.stderr}"
