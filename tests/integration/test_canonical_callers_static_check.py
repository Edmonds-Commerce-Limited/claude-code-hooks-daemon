"""Plan 00104 Phase 6 Task 6.1 — canonical-callers static-check tests.

PLAN.md Decision 7 + Success Criteria #4: ``scripts/qa/check_canonical_callers.sh``
is the 11th ``run_all.sh`` gate. It enforces that every venv-resolution
site in the codebase delegates to the canonical library
``scripts/lib/resolve_venv.sh`` (Phase 4), with two opt-out mechanisms:

  * **Positive-include allowlist** (F18): the canonical library file
    itself, plus a small fixed list of self-bootstrap scripts that
    cannot delegate (chicken-and-egg), are exempt by name.
  * **Inline marker comments**: a violation carrying a
    ``# canonical-resolver-exempt: <reason>`` comment is allowed.

The three tests below exercise the contract:

  1. ``test_canonical_library_itself_is_exempt`` — the canonical library
     contains venv-resolution patterns by construction (it IS the
     resolver). The static check must NOT flag it.
  2. ``test_inline_exempt_marker_suppresses_violation`` — a temporary
     fixture script with a violation pattern AND the marker passes.
  3. ``test_legitimate_violation_is_flagged_with_actionable_error`` — a
     temporary fixture with a violation pattern and NO marker fails
     loudly with an actionable directive (R24: "Replace with
     ``source scripts/lib/resolve_venv.sh``" or similar).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER_SCRIPT = REPO_ROOT / "scripts" / "qa" / "check_canonical_callers.sh"

VIOLATION_PATTERN_LINE = 'for candidate in "$ROOT"/untracked/venv-*/bin/python; do'
EXEMPT_MARKER = "# canonical-resolver-exempt: test fixture, intentional violation pattern"


def _run_checker(extra_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the static-check script. ``extra_path`` (if given) is added
    to its scan scope so a tmp-path fixture can be flagged."""
    args = [str(CHECKER_SCRIPT)]
    if extra_path is not None:
        args.append(str(extra_path))
    return subprocess.run(args, capture_output=True, text=True, check=False)


def test_canonical_library_itself_is_exempt() -> None:
    """The canonical library file IS the resolver — the static check
    must NOT flag its own venv-resolution patterns.

    Phase 6 Task 6.1: positive-include allowlist names
    ``scripts/lib/resolve_venv.sh`` (and the small set of self-bootstrap
    scripts that cannot delegate) as exempt. When Phase 4 lands the
    library and Phase 6 lands the checker, this assertion is
    straightforward: run the checker against HEAD and observe rc=0.
    """
    result = _run_checker()
    assert result.returncode == 0, (
        "Static check must pass HEAD when only the canonical library "
        "and self-bootstrap scripts contain resolution patterns.\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )


def test_inline_exempt_marker_suppresses_violation(tmp_path: Path) -> None:
    """A violation pattern carrying the exempt marker comment passes."""
    fixture = tmp_path / "vendored_resolver.sh"
    fixture.write_text(
        "#!/bin/bash\n"
        f"{EXEMPT_MARKER}\n"
        f"{VIOLATION_PATTERN_LINE}\n"
        '    echo "$candidate"\n'
        "done\n"
    )
    result = _run_checker(extra_path=fixture)
    assert result.returncode == 0, (
        "Static check must honour the inline canonical-resolver-exempt "
        f"marker.\nfixture={fixture}\nreturncode={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_legitimate_violation_is_flagged_with_actionable_error(tmp_path: Path) -> None:
    """A violation pattern WITHOUT the marker fails with actionable output."""
    fixture = tmp_path / "rogue_resolver.sh"
    fixture.write_text(
        "#!/bin/bash\n" f"{VIOLATION_PATTERN_LINE}\n" '    echo "$candidate"\n' "done\n"
    )
    result = _run_checker(extra_path=fixture)

    assert result.returncode != 0, (
        "Static check must flag a venv-resolution pattern that lacks both "
        "the canonical-library delegation AND the exempt marker.\n"
        f"fixture={fixture}\nreturncode={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "resolve_venv" in combined or "canonical-resolver-exempt" in combined, (
        "Error output must reference either the canonical library "
        "(`source scripts/lib/resolve_venv.sh`) or the exempt marker "
        "(`# canonical-resolver-exempt: <reason>`) so the operator knows "
        "exactly how to fix the violation (R24 actionable error output).\n"
        f"output=\n{combined}"
    )


class TestAGrepFailureIsNotSilentlyReadAsNoMatch:
    """00466 N21: ``grep -q -E ... "$file"`` exits 2 when it cannot open or

    read the file (e.g. unreadable, vanished mid-scan) -- a DIFFERENT outcome
    from exit 1 ("no match"). ``if ! grep -q ...; then return 0; fi`` treated
    both the same, so a file grep could not check was silently reported as
    clean rather than as unchecked.

    A stub ``grep`` on ``PATH`` reproduces exit 2 deterministically: this
    container runs as root, so permission bits alone cannot make a real file
    unreadable here, but the code path under test does not care WHY grep
    failed -- only that it did.
    """

    _MARKER = "GREP_ERROR_MARKER"

    def _stub_grep_bin(self, tmp_path: Path) -> Path:
        real_grep = shutil.which("grep") or "/usr/bin/grep"
        bin_dir = tmp_path / "stub_bin"
        bin_dir.mkdir()
        stub = bin_dir / "grep"
        stub.write_text(
            "#!/bin/bash\n"
            f'for _stub_arg in "$@"; do\n'
            f'    case "$_stub_arg" in\n'
            f"        *{self._MARKER}*) exit 2 ;;\n"
            "    esac\n"
            "done\n"
            f'exec "{real_grep}" "$@"\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return bin_dir

    def test_a_grep_error_fails_the_gate_naming_the_file(self, tmp_path: Path) -> None:
        fixture = tmp_path / f"{self._MARKER}.sh"
        fixture.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
        bin_dir = self._stub_grep_bin(tmp_path)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

        result = subprocess.run(
            [str(CHECKER_SCRIPT), str(fixture)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert result.returncode != 0, (
            f"a file grep could not read must fail the gate, not pass silently.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert (
            str(fixture) in combined or fixture.name in combined
        ), f"the unreadable file must be named in the output.\noutput=\n{combined}"

    def test_a_clean_tree_with_the_stub_grep_still_passes(self, tmp_path: Path) -> None:
        """No false alarm: the stub only errors on the marker path."""
        fixture = tmp_path / "ordinary.sh"
        fixture.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
        bin_dir = self._stub_grep_bin(tmp_path)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

        result = subprocess.run(
            [str(CHECKER_SCRIPT), str(fixture)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr


class TestFindTraversalErrorsAreNotSilenced:
    """00466 N21: ``find ... 2>/dev/null`` discarded find's own stderr, so a

    directory find could not traverse (permission denied, vanished mid-scan)
    produced no record at all -- not in the output, not in the exit code.

    A stub ``find`` on ``PATH`` reproduces a traversal failure
    deterministically for the same reason the grep stub above does: this
    container's root user bypasses the permission bits that would trigger a
    real one.
    """

    _MARKER = "FIND_ERROR_MARKER"

    def _stub_find_bin(self, tmp_path: Path) -> Path:
        real_find = shutil.which("find") or "/usr/bin/find"
        bin_dir = tmp_path / "stub_bin"
        bin_dir.mkdir()
        stub = bin_dir / "find"
        stub.write_text(
            "#!/bin/bash\n"
            f'for _stub_arg in "$@"; do\n'
            f'    case "$_stub_arg" in\n'
            f"        *{self._MARKER}*)\n"
            f'            echo "find: '
            "'"
            "$_stub_arg"
            "'"
            ': Permission denied" >&2\n'
            "            exit 1\n"
            "            ;;\n"
            "    esac\n"
            "done\n"
            f'exec "{real_find}" "$@"\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return bin_dir

    def test_a_traversal_error_fails_the_gate(self, tmp_path: Path) -> None:
        target_dir = tmp_path / f"{self._MARKER}_dir"
        target_dir.mkdir()
        (target_dir / "clean.sh").write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
        bin_dir = self._stub_find_bin(tmp_path)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

        result = subprocess.run(
            [str(CHECKER_SCRIPT), str(target_dir)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert result.returncode != 0, (
            "a directory find could not traverse must fail the gate, not pass silently.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        combined = result.stdout + result.stderr
        assert (
            "Permission denied" in combined
        ), f"find's own error must be surfaced, not swallowed.\noutput=\n{combined}"

    def test_a_clean_tree_with_the_stub_find_still_passes(self, tmp_path: Path) -> None:
        """No false alarm: the stub only errors on the marker directory."""
        target_dir = tmp_path / "ordinary_dir"
        target_dir.mkdir()
        (target_dir / "clean.sh").write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
        bin_dir = self._stub_find_bin(tmp_path)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

        result = subprocess.run(
            [str(CHECKER_SCRIPT), str(target_dir)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr
