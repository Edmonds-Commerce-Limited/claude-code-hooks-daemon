"""Tests for the unrunnable-guidance QA checker (Plan 00192, Plan 00193).

The checker bans every documented way of invoking the daemon that CANNOT work
in a reader's shell:

1. ``$PYTHON`` / ``$VENV_PYTHON`` — never exported to an agent.
2. ``<any python> -m claude_code_hooks_daemon.daemon.cli`` — a bare ``python3``
   cannot import the package (``include-system-site-packages = false``).
3. ``untracked/venv/bin/…`` — the pre-v3.7.0 venv layout. Venvs are
   fingerprint-keyed now, so this directory does not exist in any current
   install.

All three share one root cause and one remedy: the deployed
``bin/hooks-daemon`` wrapper, which resolves the interpreter itself.

The interpreter is taken from ``sys.executable`` — pytest already runs under
the daemon's venv, so there is nothing to hardcode. Spelling out a venv path
here would reproduce the very defect under test.
"""

import json
import subprocess  # nosec B404 - subprocess used for running the QA checker only
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_python_var_guidance.py"
_JSON_OUTPUT = _REPO_ROOT / "untracked" / "qa" / "python_var_guidance.json"


def _run_checker(scan_path: Path) -> dict[str, Any]:
    """Run the checker against ``scan_path`` and return its parsed JSON."""
    subprocess.run(  # nosec B603 - trusted first-party checker script
        [sys.executable, str(_CHECKER), "--json", "--path", str(scan_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert _JSON_OUTPUT.exists(), f"Expected JSON output at {_JSON_OUTPUT}"
    return json.loads(_JSON_OUTPUT.read_text())


def _violated_lines(data: dict[str, Any]) -> list[int]:
    return [violation["line"] for violation in data["violations"]]


class TestUnsetShellVariable:
    """``$PYTHON`` and ``$VENV_PYTHON`` are never set in a reader's shell."""

    def test_flags_python_variable(self, tmp_path: Path) -> None:
        (tmp_path / "guide.md").write_text("Run `$PYTHON -m pytest tests/`\n")
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]
        assert data["summary"]["total_violations"] == 1

    def test_flags_venv_python_variable(self, tmp_path: Path) -> None:
        (tmp_path / "guide.md").write_text("VENV_PYTHON=... then `$VENV_PYTHON x`\n")
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]

    def test_flags_braced_form(self, tmp_path: Path) -> None:
        (tmp_path / "guide.md").write_text("Run ${PYTHON} -c 'print(1)'\n")
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]


class TestBareInterpreterInvokingTheCli:
    """Only ``daemon.cli`` is banned — internal module entry points are not."""

    def test_flags_python3_dash_m_daemon_cli(self, tmp_path: Path) -> None:
        (tmp_path / "guide.md").write_text(
            "python3 -m claude_code_hooks_daemon.daemon.cli status\n"
        )
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]

    def test_allows_internal_module_entry_points(self, tmp_path: Path) -> None:
        """Modules with no wrapper equivalent are invoked BY daemon scripts."""
        (tmp_path / "notes.md").write_text(
            "python -m claude_code_hooks_daemon.core.error_response\n"
        )
        data = _run_checker(tmp_path)
        assert data["summary"]["passed"], data["violations"]


class TestLegacyVenvPath:
    """Regression: the pre-v3.7.0 ``untracked/venv/`` layout no longer exists.

    Venvs have been fingerprint-keyed since v3.7.0
    (``untracked/venv-{slug}-py{MM}-{fingerprint}/``). Any doc still spelling
    out ``untracked/venv/bin/python`` hands the reader a path that is absent on
    every current install — the same unrunnable-guidance defect as ``$PYTHON``,
    in a different spelling that the original pattern did not look for.
    """

    def test_flags_legacy_venv_python(self, tmp_path: Path) -> None:
        (tmp_path / "guide.md").write_text("untracked/venv/bin/python install.py\n")
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]
        assert _violated_lines(data) == [1]

    def test_flags_legacy_venv_pip(self, tmp_path: Path) -> None:
        (tmp_path / "guide.md").write_text("untracked/venv/bin/pip install -e .\n")
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]

    def test_flags_client_mode_legacy_venv(self, tmp_path: Path) -> None:
        (tmp_path / "guide.md").write_text(
            ".claude/hooks-daemon/untracked/venv/bin/python --version\n"
        )
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]

    def test_allows_unrelated_venv_paths(self, tmp_path: Path) -> None:
        """Generic venv advice for installing arbitrary packages is untouched.

        ``pip_break_system`` and ``sudo_pip`` legitimately tell users to build a
        throwaway venv. That is not the daemon's venv and must not be flagged.
        """
        (tmp_path / "guide.md").write_text(
            "python3 -m venv /tmp/venv && /tmp/venv/bin/pip install <package>\n"
        )
        data = _run_checker(tmp_path)
        assert data["summary"]["passed"], data["violations"]

    def test_allows_fingerprint_keyed_venv(self, tmp_path: Path) -> None:
        """The CURRENT layout is describable — only the retired one is banned."""
        (tmp_path / "guide.md").write_text("untracked/venv-{slug}-py{MM}-{fp}/\n")
        data = _run_checker(tmp_path)
        assert data["summary"]["passed"], data["violations"]


class TestExemptions:
    """The escape hatch is same-line and explicit."""

    def test_inline_marker_exempts_its_own_line(self, tmp_path: Path) -> None:
        (tmp_path / "guide.md").write_text(
            "Never use `$PYTHON`. <!-- python-var-guidance-exempt: explains the ban -->\n"
        )
        data = _run_checker(tmp_path)
        assert data["summary"]["passed"], data["violations"]

    def test_marker_does_not_exempt_the_next_line(self, tmp_path: Path) -> None:
        """A preceding marker must NOT silently cover following lines."""
        (tmp_path / "guide.md").write_text(
            "<!-- python-var-guidance-exempt: only covers this line -->\nRun `$PYTHON x`\n"
        )
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]
        assert _violated_lines(data) == [2]


class TestScannedSurface:
    """Only reader-facing suffixes are scanned."""

    def test_scans_markdown_and_python(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text("$PYTHON\n")
        (tmp_path / "b.py").write_text('MSG = "$PYTHON"\n')
        data = _run_checker(tmp_path)
        assert data["summary"]["total_violations"] == 2

    def test_ignores_other_suffixes(self, tmp_path: Path) -> None:
        (tmp_path / "c.txt").write_text("$PYTHON\n")
        (tmp_path / "d.yaml").write_text("$PYTHON\n")
        data = _run_checker(tmp_path)
        assert data["summary"]["passed"], data["violations"]


class TestShellScriptGuidance:
    """Shell scripts PRINT instructions too — that is guidance, and it counts.

    Found by provisioning the client fixture: ``install_version.sh`` closed with
    a "Daemon management:" block echoing variant 2, and ``setup_worktree.sh``
    echoed the literal ``$PYTHON -m …`` variant-1 form as its "Quick start".
    Both reach the user exactly like a doc does, but ``.sh`` was outside the
    scanned suffixes, so neither was ever checked.

    Two conditions must BOTH hold for a `.sh` line to be a defect: it is an
    output statement, AND it shows a command rather than reporting a value.
    Printing an already-resolved interpreter as a value is legitimate — that is
    what the resolver is for.
    """

    def test_flags_escaped_variable_in_echo(self, tmp_path: Path) -> None:
        r"""`echo "\$PYTHON …"` prints a literal, unexpanded `$PYTHON`."""
        (tmp_path / "s.sh").write_text(
            'echo "  \\$PYTHON -m claude_code_hooks_daemon.daemon.cli status"\n'
        )
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]
        assert _violated_lines(data) == [1]

    def test_flags_print_helper_showing_a_command(self, tmp_path: Path) -> None:
        (tmp_path / "s.sh").write_text(
            'print_info "Check: $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status"\n'
        )
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]

    def test_allows_internal_invocation(self, tmp_path: Path) -> None:
        """The script resolved the interpreter itself — this is not guidance."""
        (tmp_path / "s.sh").write_text(
            '"$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli status 2>&1\n'
        )
        data = _run_checker(tmp_path)
        assert data["summary"]["passed"], data["violations"]

    def test_allows_assignment_and_use(self, tmp_path: Path) -> None:
        (tmp_path / "s.sh").write_text(
            'PYTHON="$(resolve_venv_python "$ROOT")"\n"$PYTHON" -m pytest -q\n'
        )
        data = _run_checker(tmp_path)
        assert data["summary"]["passed"], data["violations"]

    def test_skill_wrappers_are_not_blanket_exempt(self, tmp_path: Path) -> None:
        """A script that resolves `PYTHON` may still PRINT bad guidance.

        The skill wrappers (`daemon-cli.sh`, `health-check.sh`,
        `init-handlers.sh`) were blanket path-exempt because they legitimately
        set and use `PYTHON` internally. That exemption also hid five `echo`
        lines telling the operator to run `$PYTHON -m …daemon.cli` instead of
        the wrapper — found in the client fixture (Plan 00193 Phase 4).

        The output-statement rule draws the line precisely enough that the
        blanket exemption is unnecessary, so it was removed: invocations pass,
        printed guidance does not.
        """
        script = tmp_path / "health-check.sh"
        script.write_text(
            'PYTHON="$(resolve_venv_python "$DIR")"\n'
            '"$PYTHON" -m claude_code_hooks_daemon.daemon.cli status\n'
            'echo "  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart"\n'
        )
        data = _run_checker(tmp_path)
        assert not data["summary"]["passed"]
        assert _violated_lines(data) == [3], "only the echoed guidance is a defect"

    def test_allows_diagnostic_reporting_a_resolved_path(self, tmp_path: Path) -> None:
        """Naming the interpreter you just failed to find is not an instruction.

        `print_error "Venv Python not found: $VENV_PYTHON"` expands to the real
        path the script resolved. Flagging it would force scripts to hide the
        very detail that makes the error actionable.
        """
        (tmp_path / "s.sh").write_text(
            'print_error "Venv Python not found: $VENV_PYTHON"\n'
            'echo "Python: $(resolve_existing_venv_python "$ROOT")" >&2\n'
        )
        data = _run_checker(tmp_path)
        assert data["summary"]["passed"], data["violations"]


class TestRepositoryIsClean:
    """The real trees must stay clean — this is the regression lock."""

    def test_default_scan_roots_have_no_violations(self) -> None:
        result = subprocess.run(  # nosec B603 - trusted first-party checker script
            [sys.executable, str(_CHECKER)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout
