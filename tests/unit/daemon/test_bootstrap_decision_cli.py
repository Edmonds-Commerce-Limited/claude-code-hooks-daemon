"""``paths.py bootstrap-decision``: the venv-less gate the hook path asks (Plan 00456).

When the daemon clone is present but no venv resolves for this project path
(GitHub issue #53), ``init.sh`` must decide whether it may build the venv on
its own. It is bash, and the venv it would need to import the package is the
very thing that is missing, so it runs ``paths.py`` BY FILE PATH under a
stdlib ``python3`` (Plan 00431's technique). One spawn has to return
everything the hook needs:

- the five-condition decision from :func:`can_inline_bootstrap`, with one
  remediation line per failed condition (Task 1.3: name each failure with its
  fix, never "install" and never "--force");
- the venv fingerprint the build would produce, so the build's log and
  failed-build marker are keyed exactly like the venv itself;
- an inputs signature, so a failed build is retried only once something it
  depends on has changed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import paths
from claude_code_hooks_daemon.daemon.paths import (
    bootstrap_inputs_signature,
    bootstrap_remediation,
    main,
    python_venv_fingerprint,
)

_PYPROJECT = """\
[project]
name = "fake-daemon"
version = "0.0.0"
requires-python = ">=3.11"
"""

_PATHS_PY = Path(paths.__file__).resolve()
_TIMEOUT_SECONDS = 30

#: The five stable missing-ids :class:`BootstrapDecision` can carry.
_ALL_MISSING_IDS = ("uv", "pyproject.toml", "uv.lock", "compatible-python", "untracked-writable")


@pytest.fixture
def daemon_dir(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT)
    (tmp_path / "uv.lock").write_text("# lock\n")
    (tmp_path / "untracked").mkdir()
    return tmp_path


def _patch_all_good(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "claude_code_hooks_daemon.daemon.paths.shutil.which",
        lambda name: "/opt/uv/bin/uv" if name == "uv" else None,
    )
    monkeypatch.setattr(
        "claude_code_hooks_daemon.daemon.paths.find_latest_python",
        lambda *_args, **_kwargs: Path(sys.executable),
    )


def _parse(stdout: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for line in stdout.splitlines():
        key, sep, value = line.partition("=")
        assert sep == "=", f"every output line must be key=value, got {line!r}"
        parsed.setdefault(key, []).append(value)
    return parsed


def _decide(daemon_dir: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, list[str]]:
    rc = main(["bootstrap-decision", "--daemon-dir", str(daemon_dir)])
    assert rc == 0, "a refused decision is data, not a failure of the command"
    return _parse(capsys.readouterr().out)


class TestTheDecisionItReports:
    def test_all_green_is_allowed_with_no_missing_lines(
        self,
        daemon_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _patch_all_good(monkeypatch)
        out = _decide(daemon_dir, capsys)
        assert out["allowed"] == ["true"]
        assert "missing" not in out
        assert "fix" not in out

    def test_uv_missing_is_refused_and_named_with_its_fix(
        self,
        daemon_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _patch_all_good(monkeypatch)
        monkeypatch.setattr("claude_code_hooks_daemon.daemon.paths.shutil.which", lambda _n: None)
        out = _decide(daemon_dir, capsys)
        assert out["allowed"] == ["false"]
        assert out["missing"] == ["uv"]
        assert len(out["fix"]) == 1
        assert out["fix"][0].startswith("uv: ")

    def test_every_failed_condition_gets_its_own_fix_line(
        self,
        daemon_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("claude_code_hooks_daemon.daemon.paths.shutil.which", lambda _n: None)
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths.find_latest_python",
            lambda *_args, **_kwargs: None,
        )
        (daemon_dir / "pyproject.toml").unlink()
        (daemon_dir / "uv.lock").unlink()
        out = _decide(daemon_dir, capsys)
        assert out["allowed"] == ["false"]
        assert set(out["missing"]) == {"uv", "pyproject.toml", "uv.lock", "compatible-python"}
        assert [line.split(":", 1)[0] for line in out["fix"]] == out["missing"]

    def test_it_reports_the_fingerprint_of_the_interpreter_running_it(
        self,
        daemon_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The build keys its venv on the interpreter that ran this gate, so the
        log and failed marker must be keyed on the same fingerprint."""
        _patch_all_good(monkeypatch)
        out = _decide(daemon_dir, capsys)
        assert out["fingerprint"] == [python_venv_fingerprint(daemon_dir)]
        assert out["python"] == [sys.executable]

    def test_it_reports_the_inputs_signature(
        self,
        daemon_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _patch_all_good(monkeypatch)
        out = _decide(daemon_dir, capsys)
        assert out["inputs"] == [bootstrap_inputs_signature(daemon_dir)]

    def test_a_multi_line_reason_cannot_break_the_line_protocol(
        self,
        daemon_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A TOML parse error message spans lines; the reader is `read -r`."""
        _patch_all_good(monkeypatch)
        (daemon_dir / "pyproject.toml").write_text("[project\nname = not-closed\n")
        out = _decide(daemon_dir, capsys)
        assert out["allowed"] == ["false"]
        assert len(out["reason"]) == 1

    def test_a_missing_daemon_dir_is_a_usage_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["bootstrap-decision", "--daemon-dir", str(tmp_path / "absent")])
        assert rc == 2
        assert "does not exist" in capsys.readouterr().err


class TestRemediation:
    """Task 1.3: each failed condition is named with how to fix it."""

    @pytest.mark.parametrize("missing_id", _ALL_MISSING_IDS)
    def test_every_missing_id_has_a_fix_that_never_says_install_or_force(
        self, missing_id: str, daemon_dir: Path
    ) -> None:
        fix = bootstrap_remediation(missing_id, daemon_dir)
        assert fix
        lowered = fix.lower()
        assert "args=install" not in lowered
        assert "--force" not in lowered
        assert "force=true" not in lowered

    def test_the_python_fix_names_the_projects_own_floor(self, daemon_dir: Path) -> None:
        (daemon_dir / "pyproject.toml").write_text(_PYPROJECT.replace("3.11", "3.13"))
        fix = bootstrap_remediation("compatible-python", daemon_dir)
        assert "3.13" in fix
        assert "HOOKS_DAEMON_PYTHON" in fix

    def test_the_writable_fix_names_the_directory(self, daemon_dir: Path) -> None:
        assert str(daemon_dir / "untracked") in bootstrap_remediation(
            "untracked-writable", daemon_dir
        )

    def test_an_unknown_id_is_a_programming_error(self, daemon_dir: Path) -> None:
        with pytest.raises(ValueError, match="no-such-condition"):
            bootstrap_remediation("no-such-condition", daemon_dir)


class TestInputsSignature:
    """A failed build is retried only when something it depends on changed."""

    def test_stable_across_calls(self, daemon_dir: Path) -> None:
        assert bootstrap_inputs_signature(daemon_dir) == bootstrap_inputs_signature(daemon_dir)

    def test_changes_when_the_lockfile_changes(self, daemon_dir: Path) -> None:
        before = bootstrap_inputs_signature(daemon_dir)
        (daemon_dir / "uv.lock").write_text("# a different lock\n")
        assert bootstrap_inputs_signature(daemon_dir) != before

    def test_changes_when_uv_moves(self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths.shutil.which", lambda _n: "/a/uv"
        )
        before = bootstrap_inputs_signature(daemon_dir)
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths.shutil.which", lambda _n: "/b/uv"
        )
        assert bootstrap_inputs_signature(daemon_dir) != before

    def test_survives_a_missing_pyproject(self, daemon_dir: Path) -> None:
        (daemon_dir / "pyproject.toml").unlink()
        assert bootstrap_inputs_signature(daemon_dir)


class TestItNeedsNoVenv:
    """The whole point: the hook runs this with no venv and no package import."""

    def test_runs_by_file_path_with_no_package_on_the_path(self, daemon_dir: Path) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
        # -S skips site-packages entirely, so the editable install of this
        # package is invisible: only paths.py's own stdlib imports can load.
        result = subprocess.run(  # nosec B603 - fixed argv, no shell
            [sys.executable, "-S", str(_PATHS_PY), "bootstrap-decision", "--daemon-dir", str(daemon_dir)],
            capture_output=True,
            text=True,
            env=env,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        out = _parse(result.stdout)
        assert out["allowed"][0] in ("true", "false")
        assert out["fingerprint"][0].startswith(paths.project_path_slug(daemon_dir))
