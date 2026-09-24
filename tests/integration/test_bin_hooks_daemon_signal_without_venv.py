"""``bin/hooks-daemon signal`` works when there is no venv to run it with (Plan 00457, #55).

The wrapper resolves the venv before it looks at a single argument, so every
verb exits 5 when no venv resolves for this path (Plan 00456, #53, fixed this
for ``repair`` first -- see ``test_bin_hooks_daemon_repair_without_venv.py``).
``signal`` -- the operator-signal channel's host-reachable caller (Plan
00417) -- is the second verb this applies to, and for a different reason: its
caller need not be inside any Claude Code session at all, so for a project
whose only venv was built inside a container (wrong slug, wrong interpreter),
this host-side tool was refused on the exact deployment it exists for.

Unlike ``repair``, ``signal`` never builds a venv. Its arm execs
``daemon/signal_standalone.py`` -- standard-library-only, loaded by file path
rather than package import (see that module's own docstring) -- directly
under a system ``python3``, gated on Python >= 3.8 first so an old
interpreter gets a clear message instead of an ``ImportError`` from inside
``operator_signal.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.venv_bootstrap_sandbox import Sandbox

#: bin/hooks-daemon's "no venv resolves" exit status.
_NO_VENV_EXIT = 5


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()


def _sidecar_dir(sandbox: Sandbox) -> Path:
    sidecar_dir = sandbox.clone / "untracked" / "context-sidecar"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    return sidecar_dir


class TestSignalWithNoVenv:
    def test_writes_a_signal_and_builds_no_venv(self, sandbox: Sandbox) -> None:
        sidecar_dir = _sidecar_dir(sandbox)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")

        result = sandbox.wrapper(
            "signal", "reboot-cancelled", "--all-sessions", "--project-root", str(sandbox.project)
        )

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert (sidecar_dir / "sess-a.operator-signal").exists()
        assert sandbox.uv_calls() == [], "signal must never build a venv"
        assert not sandbox.resolves(), "signal leaves this clone with no venv, exactly as before"

    def test_a_warning_kind_without_minutes_is_still_refused(self, sandbox: Sandbox) -> None:
        """Validation is unchanged: reused from operator_signal.py, not
        re-implemented for the venv-free path."""
        result = sandbox.wrapper(
            "signal", "reboot-warning", "--all-sessions", "--project-root", str(sandbox.project)
        )

        assert result.returncode == 1, result.stdout + result.stderr
        assert "--minutes" in result.stderr

    def test_help_needs_no_venv(self, sandbox: Sandbox) -> None:
        result = sandbox.wrapper("signal", "--help")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "signal" in result.stdout.lower()
        assert sandbox.uv_calls() == []

    def test_a_missing_entry_point_is_named(self, sandbox: Sandbox) -> None:
        entry_point = (
            sandbox.clone / "src" / "claude_code_hooks_daemon" / "daemon" / "signal_standalone.py"
        )
        entry_point.unlink()

        result = sandbox.wrapper(
            "signal", "reboot-cancelled", "--all-sessions", "--project-root", str(sandbox.project)
        )

        assert result.returncode == _NO_VENV_EXIT
        assert "signal_standalone.py" in result.stderr
        assert sandbox.uv_calls() == []

    def test_refuses_a_python3_older_than_the_floor(self, sandbox: Sandbox) -> None:
        """The wrapper's own gate, ahead of ever invoking the entry point --
        distinct from (and a backstop alongside) signal_standalone.py's own
        internal `_check_python_version`."""
        old_python3 = sandbox.root / "tools" / "python3"
        old_python3.unlink()
        old_python3.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
        old_python3.chmod(0o755)

        result = sandbox.wrapper(
            "signal", "reboot-cancelled", "--all-sessions", "--project-root", str(sandbox.project)
        )

        assert result.returncode == _NO_VENV_EXIT
        assert "3.8" in result.stderr
        assert sandbox.uv_calls() == []

    def test_a_broken_python3s_own_stderr_is_not_swallowed(self, sandbox: Sandbox) -> None:
        """Review fix 1: the version probe used to redirect the broken
        interpreter's own stderr to /dev/null, so a python3 that crashes for
        a reason OTHER than "too old" (a corrupt install, a bad shebang) was
        reported identically to a clean old-version refusal -- the real
        reason was thrown away. The probe's stderr must reach ours."""
        broken_python3 = sandbox.root / "tools" / "python3"
        broken_python3.unlink()
        broken_python3.write_text(
            "#!/bin/bash\necho 'PYTHON3-IS-CORRUPT-MARKER' >&2\nexit 1\n", encoding="utf-8"
        )
        broken_python3.chmod(0o755)

        result = sandbox.wrapper(
            "signal", "reboot-cancelled", "--all-sessions", "--project-root", str(sandbox.project)
        )

        assert result.returncode == _NO_VENV_EXIT
        assert "PYTHON3-IS-CORRUPT-MARKER" in result.stderr

    def test_no_system_python3_on_path_is_named_clearly(self, sandbox: Sandbox) -> None:
        """Review fix 1: `command -v python3 || true` is the banned
        error-hiding shape (a bare `|| true` on a command whose failure is
        meaningful) -- assert on the behaviour it must still produce once
        rewritten as an explicit `if ! system_python=$(command -v python3);
        then ...`: python3 missing entirely is still refused at exit 5 with
        a clear message, not a raw `set -e` failure."""
        (sandbox.root / "tools" / "python3").unlink()

        result = sandbox.wrapper(
            "signal", "reboot-cancelled", "--all-sessions", "--project-root", str(sandbox.project)
        )

        assert result.returncode == _NO_VENV_EXIT
        assert "no system python3" in result.stderr.lower()


class TestMissingValueForAGlobalOption:
    """Review fix 2: the reconstruction loop that strips the "signal" verb
    replicates ``_subcommand_of``'s value-taking-option recognition
    (--project-root/--pid-file/--socket), but originally did an unconditional
    ``shift 2`` -- which fails under this script's own ``set -e`` when the
    option is the LAST argument, so the script died with no explanation
    at all. The fix passes the bare flag through so signal_standalone.py's
    own argparse reports the missing value clearly.
    """

    def test_project_root_as_the_last_argument_is_not_a_silent_crash(
        self, sandbox: Sandbox
    ) -> None:
        result = sandbox.wrapper("signal", "reboot-cancelled", "--all-sessions", "--project-root")

        output = result.stdout + result.stderr
        assert result.returncode != 0
        assert output.strip(), "must not die with empty stdout and stderr"
        assert "shift" not in output.lower(), "a raw bash builtin error leaked through"
        assert "project-root" in output.lower()


class TestTheVerbIsFoundPastGlobalOptions:
    """Mirrors ``TestTheVerbIsFoundPastGlobalOptions`` in the repair test file
    (Review S3): the intercept looks for the subcommand, not just ``$1``.
    """

    def test_signal_after_a_global_option_still_dispatches(self, sandbox: Sandbox) -> None:
        sidecar_dir = _sidecar_dir(sandbox)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")

        result = sandbox.wrapper(
            "--project-root",
            str(sandbox.project),
            "signal",
            "reboot-cancelled",
            "--all-sessions",
            "--project-root",
            str(sandbox.project),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert (sidecar_dir / "sess-a.operator-signal").exists()
