"""``bin/hooks-daemon repair`` rebuilds a venv that resolves but cannot import the package.

Plan 00456 made ``repair`` work when NO venv resolves. Plan 00555 made a venv
whose interpreter drifted stop resolving, so that case takes the same path. What
was left is a venv whose ``pyvenv.cfg`` version is right (so it resolves) but
whose site-packages holds no ``claude_code_hooks_daemon`` (an uninstalled dist,
a partial sync, a stale editable ``.pth``). The wrapper then exec'd the Python
CLI, which died with ``ModuleNotFoundError``, and a rebuild would have reused
the venv because its lock hash still matched.

The wrapper therefore probes the import before running ``repair`` and, when it
fails, takes the venv-free path with a forced rebuild.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.venv_bootstrap_sandbox import BASH, Sandbox

_PROBE_TIMEOUT_ENV = "HOOKS_DAEMON_IMPORT_PROBE_TIMEOUT_SECONDS"


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()


def _only_venv(sandbox: Sandbox) -> Path:
    venvs = sorted((sandbox.clone / "untracked").glob("venv-*"))
    assert len(venvs) == 1, venvs
    return venvs[0]


def break_import(venv: Path) -> None:
    """Make ``venv`` resolve (right version, fresh lock hash) yet lack the package.

    Its interpreter becomes a real symlink to the running one, with a
    ``pyvenv.cfg`` that records the right version and no site-packages entry for
    the package, so ``import claude_code_hooks_daemon`` raises ModuleNotFoundError.
    """
    python = venv / "bin" / "python"
    python.unlink()
    python.symlink_to(sys.executable)
    base_home = Path(getattr(sys, "_base_executable", sys.executable)).parent
    (venv / "pyvenv.cfg").write_text(
        f"home = {base_home}\n"
        "include-system-site-packages = false\n"
        f"version_info = {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n"
    )
    (
        venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    ).mkdir(parents=True, exist_ok=True)


def _built_then_broken(sandbox: Sandbox) -> Path:
    sandbox.stub_uv()
    assert sandbox.wrapper("repair").returncode == 0
    venv = _only_venv(sandbox)
    break_import(venv)
    sandbox.uv_log.unlink()
    return venv


class TestFixtureIsTheHole:
    def test_the_broken_venv_resolves_yet_cannot_import(self, sandbox: Sandbox) -> None:
        venv = _built_then_broken(sandbox)

        assert sandbox.resolves(), "precondition: the wrapper's resolver accepts this venv"
        probe = sandbox.run([str(venv / "bin" / "python"), "-c", "import claude_code_hooks_daemon"])
        assert probe.returncode != 0
        assert "ModuleNotFoundError" in probe.stderr


class TestRepairRebuildsAnImportBrokenVenv:
    def test_repair_succeeds_by_rebuilding_not_reusing(self, sandbox: Sandbox) -> None:
        venv = _built_then_broken(sandbox)

        result = sandbox.wrapper("repair")

        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        assert "Venv repaired successfully" in output
        assert not (venv / "bin" / "python").is_symlink(), "the broken interpreter survived"

    def test_the_failure_is_explained_with_the_diagnosis_and_repair_command(
        self, sandbox: Sandbox
    ) -> None:
        _built_then_broken(sandbox)

        result = sandbox.wrapper("repair")
        output = result.stdout + result.stderr

        assert "cannot import claude_code_hooks_daemon" in output
        assert "claude_code_hooks_daemon importable: no" in output

    def test_repair_after_a_global_option_is_probed_too(self, sandbox: Sandbox) -> None:
        venv = _built_then_broken(sandbox)

        result = sandbox.wrapper("--project-root", str(sandbox.project), "repair")

        assert result.returncode == 0, result.stdout + result.stderr
        assert not (venv / "bin" / "python").is_symlink()

    def test_a_hung_probe_is_bounded_and_counts_as_broken(self, sandbox: Sandbox) -> None:
        venv = _built_then_broken(sandbox)
        python = venv / "bin" / "python"
        python.rename(venv / "bin" / "python-real")
        # Answers every call like the real interpreter, except the package import.
        python.write_text(
            "#!/bin/bash\n"
            'case "$*" in *claude_code_hooks_daemon*) sleep 60 ;; esac\n'
            'exec "$(dirname "$0")/python-real" "$@"\n'
        )
        python.chmod(0o755)

        result = sandbox.run(
            [BASH, str(sandbox.clone / "bin" / "hooks-daemon"), "repair"],
            extra_env={_PROBE_TIMEOUT_ENV: "1"},
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Venv repaired successfully" in result.stdout + result.stderr
        assert not (venv / "bin" / "python-real").exists(), "the hung venv was not rebuilt"


class TestBootstrapForcedRebuild:
    def test_plain_repair_reuses_a_lock_fresh_venv(self, sandbox: Sandbox) -> None:
        _built_then_broken(sandbox)
        bootstrap = str(sandbox.clone / "scripts" / "venv_bootstrap.sh")

        result = sandbox.run([BASH, bootstrap, "repair", str(sandbox.clone)])

        assert result.returncode == 0, result.stdout + result.stderr
        assert sandbox.uv_calls() == []

    def test_rebuild_flag_rebuilds_a_lock_fresh_venv(self, sandbox: Sandbox) -> None:
        venv = _built_then_broken(sandbox)
        bootstrap = str(sandbox.clone / "scripts" / "venv_bootstrap.sh")

        result = sandbox.run([BASH, bootstrap, "repair", str(sandbox.clone), "--rebuild"])

        assert result.returncode == 0, result.stdout + result.stderr
        assert sandbox.uv_calls()
        assert not (venv / "bin" / "python").is_symlink()

    def test_unknown_third_argument_is_a_usage_error(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        bootstrap = str(sandbox.clone / "scripts" / "venv_bootstrap.sh")

        result = sandbox.run([BASH, bootstrap, "repair", str(sandbox.clone), "--bogus"])

        assert result.returncode != 0
        assert "usage" in result.stderr
