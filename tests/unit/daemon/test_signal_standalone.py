"""Tests for the venv-free `signal` entry point (Plan 00457, GitHub issue #55).

`bin/hooks-daemon` resolves a venv before it reads the subcommand (Plan
00192), so `signal` was unreachable from a host whose only venv was built
inside a container with a non-matching slug. `daemon/signal_standalone.py`
is a standard-library-only script, run DIRECTLY (never via `-m` or a normal
`import claude_code_hooks_daemon...` statement -- both execute
`claude_code_hooks_daemon/__init__.py`, which imports pydantic) that reuses
`operator_signal.py`'s validation and writer instead of re-implementing them.

These tests exercise three different things:
  - the module loads with NO non-stdlib import, under the real system
    `python3` (not this venv's), confirming the constraint that makes this
    module exist in the first place;
  - its own syntax (and its dependencies') does not exceed the Python
    version it claims to need;
  - it behaves like `cmd_signal` (``daemon/cli.py``) for the same request,
    both end-to-end under system `python3` and via the shared
    `operator_signal.run_signal_cli` the two now both delegate to.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "signal_standalone.py"
_CLI_PY = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "cli.py"
_UTILS_DIR = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "utils"
_SYNTAX_FLOOR = (3, 10)  # see TestSyntaxFloor -- paths.py's bare `X | Y` annotations
_SYSTEM_PYTHON = Path("/usr/bin/python3")

pytestmark = pytest.mark.skipif(
    not _SYSTEM_PYTHON.exists(), reason=f"{_SYSTEM_PYTHON} unavailable in this environment"
)


def _clean_env() -> dict[str, str]:
    """An environment with no venv/PYTHONPATH pollution -- simulates the host."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    return env


def _make_self_install_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    (project_root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    return project_root


class TestModuleLoadsWithoutThirdPartyImports:
    """The whole point: no venv, no third-party package, only src/ on disk."""

    def test_no_non_stdlib_module_is_loaded_by_import_alone(self) -> None:
        code = (
            "import runpy, sys\n"
            "before = set(sys.modules)\n"
            f"runpy.run_path({str(SCRIPT_PATH)!r}, run_name='not_main')\n"
            "after = set(sys.modules)\n"
            "stdlib = set(sys.stdlib_module_names)\n"
            "offenders = sorted(\n"
            "    m for m in (after - before)\n"
            "    if m.split('.')[0] not in stdlib\n"
            "    and not m.startswith('claude_code_hooks_daemon')\n"
            ")\n"
            "print('OFFENDERS=' + ','.join(offenders))\n"
        )
        result = subprocess.run(
            [str(_SYSTEM_PYTHON), "-I", "-c", code],
            capture_output=True,
            text=True,
            env=_clean_env(),
            check=False,
        )

        assert result.returncode == 0, (
            f"loading signal_standalone.py must not raise. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        offenders_line = next(
            (line for line in result.stdout.splitlines() if line.startswith("OFFENDERS=")), None
        )
        assert offenders_line is not None, f"marker line missing. stdout={result.stdout!r}"
        offenders = offenders_line.removeprefix("OFFENDERS=")
        assert offenders == "", f"no third-party module may load, got: {offenders}"

    def test_has_no_import_statement_naming_a_forbidden_module(self) -> None:
        """Structural backstop: no `import`/`from` statement in the file's
        actual code (prose in the docstring doesn't count) names cli.py,
        ProjectContext, pydantic or yaml.
        """
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        forbidden = {"pydantic", "yaml", "claude_code_hooks_daemon.daemon.cli"}
        assert not (imported & forbidden), imported & forbidden
        assert not any(m.endswith("project_context") for m in imported)


class TestSyntaxFloor:
    """The script and everything it loads must parse at its declared floor.

    ``daemon/paths.py`` uses bare ``X | Y`` annotations with no
    ``from __future__ import annotations``, which need Python 3.10 to even
    evaluate at function-definition time -- that, not anything in this
    module's own code, is the real floor. This test pins it so a future
    change to any of the four files cannot silently raise it without
    notice.
    """

    @pytest.mark.parametrize(
        "relative_path",
        [
            "daemon/signal_standalone.py",
            "daemon/paths.py",
            "utils/operator_signal.py",
            "utils/temp_names.py",
        ],
    )
    def test_parses_at_the_declared_floor(self, relative_path: str) -> None:
        path = REPO_ROOT / "src" / "claude_code_hooks_daemon" / relative_path
        source = path.read_text(encoding="utf-8")

        ast.parse(source, filename=str(path), feature_version=_SYNTAX_FLOOR)


class TestEndToEndWithoutVenv:
    """Runs the real script with the real system `python3` -- no PYTHONPATH,
    no venv, no sys.path setup: it locates its siblings via `__file__`.
    """

    def _run(
        self, tmp_path: Path, *args: str, session_id: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = _clean_env()
        if session_id is not None:
            env["CLAUDE_CODE_SESSION_ID"] = session_id
        else:
            env.pop("CLAUDE_CODE_SESSION_ID", None)
        return subprocess.run(
            [str(_SYSTEM_PYTHON), str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_writes_a_signal_for_the_current_session(self, tmp_path: Path) -> None:
        project_root = _make_self_install_project(tmp_path)

        result = self._run(
            tmp_path,
            "reboot-warning",
            "--minutes",
            "5",
            "--project-root",
            str(project_root),
            session_id="standalone-session",
        )

        assert result.returncode == 0, result.stderr
        signal_file = (
            project_root / "untracked" / "context-sidecar" / "standalone-session.operator-signal"
        )
        payload = json.loads(signal_file.read_text(encoding="utf-8"))
        assert payload["kind"] == "reboot-warning"
        assert payload["minutes"] == 5

    def test_all_sessions_reaches_every_live_sidecar_in_a_container_slugged_layout(
        self, tmp_path: Path
    ) -> None:
        """The scenario #55 is about: a self-install project whose only venv
        (irrelevant here -- this script never touches one) was built with a
        container-specific slug that cannot run on the host.
        """
        project_root = _make_self_install_project(tmp_path)
        sidecar_dir = project_root / "untracked" / "context-sidecar"
        sidecar_dir.mkdir(parents=True)
        (sidecar_dir / "sess-a.json").write_text("{}", encoding="utf-8")
        (sidecar_dir / "sess-b.json").write_text("{}", encoding="utf-8")

        result = self._run(
            tmp_path,
            "reboot-cancelled",
            "--all-sessions",
            "--project-root",
            str(project_root),
        )

        assert result.returncode == 0, result.stderr
        assert (sidecar_dir / "sess-a.operator-signal").exists()
        assert (sidecar_dir / "sess-b.operator-signal").exists()

    def test_refuses_a_warning_kind_without_minutes(self, tmp_path: Path) -> None:
        project_root = _make_self_install_project(tmp_path)

        result = self._run(
            tmp_path,
            "reboot-warning",
            "--project-root",
            str(project_root),
            session_id="s",
        )

        assert result.returncode == 1
        assert "--minutes" in result.stderr

    def test_refuses_a_nonexistent_project_root(self, tmp_path: Path) -> None:
        result = self._run(
            tmp_path,
            "reboot-cancelled",
            "--project-root",
            str(tmp_path / "does-not-exist"),
            session_id="s",
        )

        assert result.returncode == 1
        assert "does not exist" in result.stderr

    def test_missing_project_root_is_an_argparse_error(self, tmp_path: Path) -> None:
        """Unlike `cmd_signal`'s optional flag with a CWD walk-up, this entry
        point REQUIRES ``--project-root`` -- the walk-up needs the full
        package. See the module docstring.
        """
        result = self._run(tmp_path, "reboot-cancelled", session_id="s")

        assert result.returncode == 2
        assert "--project-root" in result.stderr

    def test_rejects_an_unknown_kind_like_cmd_signal_does(self, tmp_path: Path) -> None:
        project_root = _make_self_install_project(tmp_path)

        result = self._run(
            tmp_path,
            "not-a-kind",
            "--project-root",
            str(project_root),
            session_id="s",
        )

        assert result.returncode == 2


class TestKindChoicesMatchCliPy:
    """`cmd_signal`'s subparser (`daemon/cli.py`) hardcodes the closed kind
    set as a literal tuple; this module derives it from
    `operator_signal.KINDS`. Both must name the same three kinds.
    """

    def test_cli_py_choices_literal_matches_operator_signal_kinds(self) -> None:
        from claude_code_hooks_daemon.utils.operator_signal import KINDS

        tree = ast.parse(_CLI_PY.read_text(encoding="utf-8"), filename=str(_CLI_PY))
        choices: set[str] | None = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
                continue
            if not any(isinstance(a, ast.Constant) and a.value == "kind" for a in node.args):
                continue
            for kw in node.keywords:
                if kw.arg == "choices" and isinstance(kw.value, ast.Tuple):
                    choices = {
                        elt.value
                        for elt in kw.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    }
        assert choices is not None, "could not find the signal subparser's `kind` choices in cli.py"
        assert choices == set(KINDS)


class TestRunSignalCliIsTheSharedCore:
    """Structural guard: both entry points must delegate to the SAME
    function rather than each carrying their own copy of the targeting/
    writing logic.
    """

    def test_signal_standalone_calls_run_signal_cli(self) -> None:
        text = SCRIPT_PATH.read_text(encoding="utf-8")
        assert "run_signal_cli" in text

    def test_cmd_signal_calls_run_signal_cli(self) -> None:
        text = _CLI_PY.read_text(encoding="utf-8")
        assert "run_signal_cli" in text
