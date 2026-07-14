"""Tests for CcySupervisorIntegrityHandler (Plan 00148).

SessionStart advisory handler that warns when the ccy supervisor is ARMED
(``.claude/ccy/ccy.env`` exports a ``CCY_CLAUDE_WRAPPER`` referencing
``claude-supervise.py``) but its files are in a brick-risk state: the script is
missing, not executable, or git-ignored (so teammates never receive it).
"""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import HookResult
from claude_code_hooks_daemon.handlers.session_start.ccy_supervisor_integrity import (
    CcySupervisorIntegrityHandler,
)

_ARMED_ENV = (
    'export CCY_CLAUDE_WRAPPER="${CCY_CLAUDE_WRAPPER:-'
    '$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/claude-supervise.py --arm --}"\n'
)


def _make_ccy(project_root: Path) -> Path:
    ccy = project_root / ".claude" / "ccy"
    ccy.mkdir(parents=True, exist_ok=True)
    return ccy


def _write_script(ccy: Path, *, executable: bool = True) -> Path:
    script = ccy / "claude-supervise.py"
    script.write_text("#!/usr/bin/env python3\nprint('supervise')\n")
    script.chmod(0o755 if executable else 0o644)
    return script


def _run(handler: CcySupervisorIntegrityHandler, project_root: Path | None) -> HookResult:
    with patch.object(handler, "_get_project_root", return_value=project_root):
        return handler.handle({"hook_event_name": "SessionStart"})


class TestInit:
    @pytest.fixture
    def handler(self) -> CcySupervisorIntegrityHandler:
        return CcySupervisorIntegrityHandler()

    def test_name(self, handler: CcySupervisorIntegrityHandler) -> None:
        assert handler.name == "ccy-supervisor-integrity"

    def test_priority(self, handler: CcySupervisorIntegrityHandler) -> None:
        assert handler.priority == 58

    def test_non_terminal(self, handler: CcySupervisorIntegrityHandler) -> None:
        assert handler.terminal is False


class TestMatches:
    @pytest.fixture
    def handler(self) -> CcySupervisorIntegrityHandler:
        return CcySupervisorIntegrityHandler()

    def test_new_session_matches(self, handler: CcySupervisorIntegrityHandler) -> None:
        assert handler.matches({"hook_event_name": "SessionStart"}) is True

    def test_resume_session_does_not_match(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.json"
        transcript.write_text("x" * 200)
        assert (
            handler.matches({"hook_event_name": "SessionStart", "transcript_path": str(transcript)})
            is False
        )


class TestArmedDetection:
    @pytest.fixture
    def handler(self) -> CcySupervisorIntegrityHandler:
        return CcySupervisorIntegrityHandler()

    def test_real_export_line_is_armed(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        env = tmp_path / "ccy.env"
        env.write_text(f"# comment\n{_ARMED_ENV}")
        assert handler._is_armed(env) is True

    def test_commented_out_export_is_not_armed(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        env = tmp_path / "ccy.env"
        env.write_text('# export CCY_CLAUDE_WRAPPER="/x/claude-supervise.py --arm --"\n')
        assert handler._is_armed(env) is False

    def test_missing_env_is_not_armed(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        assert handler._is_armed(tmp_path / "nope.env") is False

    def test_wrapper_without_supervisor_reference_is_not_armed(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        env = tmp_path / "ccy.env"
        env.write_text('export CCY_CLAUDE_WRAPPER=""\n')  # disabled to empty
        assert handler._is_armed(env) is False


class TestHandle:
    @pytest.fixture
    def handler(self) -> CcySupervisorIntegrityHandler:
        return CcySupervisorIntegrityHandler()

    def test_not_a_ccy_project_is_silent(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        assert _run(handler, tmp_path).context == []

    def test_ccy_project_but_not_armed_is_silent(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        _make_ccy(tmp_path)  # no ccy.env → not armed
        assert _run(handler, tmp_path).context == []

    def test_armed_and_healthy_is_silent(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        ccy = _make_ccy(tmp_path)
        (ccy / "ccy.env").write_text(_ARMED_ENV)
        _write_script(ccy, executable=True)
        # No .git → git-ignore check is skipped; script present + executable.
        assert _run(handler, tmp_path).context == []

    def test_armed_but_script_missing_warns(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        ccy = _make_ccy(tmp_path)
        (ccy / "ccy.env").write_text(_ARMED_ENV)
        result = _run(handler, tmp_path)
        text = "\n".join(result.context)
        assert result.context != []
        assert "missing" in text.lower()
        assert "claude-supervise.py" in text

    def test_armed_but_not_executable_warns(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        ccy = _make_ccy(tmp_path)
        (ccy / "ccy.env").write_text(_ARMED_ENV)
        _write_script(ccy, executable=False)
        result = _run(handler, tmp_path)
        assert result.context != []
        assert "executable" in "\n".join(result.context).lower()

    def test_armed_but_git_ignored_warns(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        ccy = _make_ccy(tmp_path)
        (ccy / "ccy.env").write_text(_ARMED_ENV)
        _write_script(ccy, executable=True)
        (ccy / ".gitignore").write_text("*\n")  # blanket ignore, the broken setup
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

        result = _run(handler, tmp_path)
        text = "\n".join(result.context).lower()
        assert result.context != []
        assert "ignore" in text or "track" in text

    def test_armed_and_whitelisted_in_git_is_silent(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        ccy = _make_ccy(tmp_path)
        (ccy / "ccy.env").write_text(_ARMED_ENV)
        _write_script(ccy, executable=True)
        (ccy / ".gitignore").write_text("*\n!.gitignore\n!ccy.env\n!claude-supervise.py\n")
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

        assert _run(handler, tmp_path).context == []

    def test_project_root_none_is_silent(self, handler: CcySupervisorIntegrityHandler) -> None:
        assert _run(handler, None).context == []


class TestDeployConsistency:
    """Armed+present but ccy.deploy_supervisor=false ⇒ upgrades won't refresh it."""

    @pytest.fixture
    def handler(self) -> CcySupervisorIntegrityHandler:
        return CcySupervisorIntegrityHandler()

    def _write_config(self, project_root: Path, value: str) -> None:
        cfg = project_root / ".claude" / "hooks-daemon.yaml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(f"ccy:\n  deploy_supervisor: {value}\n", encoding="utf-8")

    def _arm_and_deploy(self, tmp_path: Path) -> None:
        ccy = _make_ccy(tmp_path)
        (ccy / "ccy.env").write_text(_ARMED_ENV)
        _write_script(ccy, executable=True)

    def test_deploy_false_while_armed_warns(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        self._arm_and_deploy(tmp_path)
        self._write_config(tmp_path, "false")
        result = _run(handler, tmp_path)
        text = "\n".join(result.context)
        assert result.context != []
        assert "deploy_supervisor" in text

    def test_deploy_true_while_armed_is_silent(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        self._arm_and_deploy(tmp_path)
        self._write_config(tmp_path, "true")
        assert _run(handler, tmp_path).context == []

    def test_deploy_absent_while_armed_is_silent(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        # No config key set → None deploys+recommends, not an inconsistency.
        self._arm_and_deploy(tmp_path)
        assert _run(handler, tmp_path).context == []

    def test_deploy_check_helper_true_for_false(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        self._write_config(tmp_path, "false")
        assert handler._deploy_explicitly_disabled(tmp_path) is True

    def test_deploy_check_helper_false_when_no_config(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        assert handler._deploy_explicitly_disabled(tmp_path) is False


class TestGitIgnoredHelper:
    @pytest.fixture
    def handler(self) -> CcySupervisorIntegrityHandler:
        return CcySupervisorIntegrityHandler()

    def test_no_git_repo_returns_false(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        assert handler._git_ignored(tmp_path, ".claude/ccy/claude-supervise.py") is False

    def test_git_error_returns_false(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        (tmp_path / ".git").mkdir()
        with patch(
            "claude_code_hooks_daemon.handlers.session_start."
            "ccy_supervisor_integrity.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            assert handler._git_ignored(tmp_path, "x") is False


class TestFallbacks:
    @pytest.fixture
    def handler(self) -> CcySupervisorIntegrityHandler:
        return CcySupervisorIntegrityHandler()

    def test_get_project_root_falls_back_to_cwd_on_runtime_error(
        self, handler: CcySupervisorIntegrityHandler
    ) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.session_start."
            "ccy_supervisor_integrity.ProjectContext.project_root",
            side_effect=RuntimeError("not initialised"),
        ):
            assert handler._get_project_root() == Path.cwd()

    def test_resume_detection_swallows_stat_error(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        transcript = tmp_path / "t.json"
        transcript.write_text("x" * 200)
        with patch.object(Path, "stat", side_effect=OSError("stat failed")):
            assert (
                handler.matches(
                    {"hook_event_name": "SessionStart", "transcript_path": str(transcript)}
                )
                is True
            )

    def test_is_armed_swallows_read_error(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        env = tmp_path / "ccy.env"
        env.write_text(_ARMED_ENV)
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            assert handler._is_armed(env) is False


class TestMetadata:
    @pytest.fixture
    def handler(self) -> CcySupervisorIntegrityHandler:
        return CcySupervisorIntegrityHandler()

    def test_get_claude_md_is_present(self, handler: CcySupervisorIntegrityHandler) -> None:
        md = handler.get_claude_md()
        assert md is not None
        assert "ccy" in md.lower()

    def test_get_acceptance_tests_returns_list(
        self, handler: CcySupervisorIntegrityHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) >= 1


# ── Stale running-supervisor detection (Plan 00164 Phase 3) ──────────────────


_VERSIONED_SCRIPT = '#!/usr/bin/env python3\n__version__ = "{version}"\nprint("supervise")\n'


def _write_versioned_script(ccy: Path, *, version: str, body: str = "") -> Path:
    script = ccy / "claude-supervise.py"
    script.write_text(_VERSIONED_SCRIPT.format(version=version) + body)
    script.chmod(0o755)
    return script


def _untracked_supervise_dir(project_root: Path) -> Path:
    # Mirrors the handler's install-mode-aware resolution for a non-self-install
    # fixture project (no src/ tree at the root).
    return project_root / ".claude" / "hooks-daemon" / "untracked" / "supervise"


def _write_status(project_root: Path, *, version: str, source_hash: str, pid: int) -> Path:
    d = _untracked_supervise_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    status = d / "supervisor-status.json"
    status.write_text(
        json.dumps({"version": version, "source_hash": source_hash, "pid": pid, "started_at": 0.0})
    )
    return status


class TestStaleness:
    @pytest.fixture
    def handler(self) -> CcySupervisorIntegrityHandler:
        return CcySupervisorIntegrityHandler()

    def _arm(self, tmp_path: Path, *, version: str = "3.40.0") -> Path:
        ccy = _make_ccy(tmp_path)
        (ccy / "ccy.env").write_text(_ARMED_ENV)
        _write_versioned_script(ccy, version=version)
        return ccy

    def test_no_status_file_is_silent(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        """Armed + healthy but no supervisor advertised → no staleness noise."""
        self._arm(tmp_path)
        assert _run(handler, tmp_path).context == []

    def test_matching_hash_is_silent(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        ccy = self._arm(tmp_path, version="3.40.0")
        script = ccy / "claude-supervise.py"
        _write_status(
            tmp_path,
            version="3.40.0",
            source_hash=handler._hash_supervisor_source(script),
            pid=os.getpid(),
        )
        assert _run(handler, tmp_path).context == []

    def test_stale_running_supervisor_warns_restart_ccy(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        """On-disk supervisor differs from the running one (alive) → advise restart."""
        self._arm(tmp_path, version="3.41.0")  # on disk = newer
        _write_status(
            tmp_path,
            version="3.40.0",  # running = older
            source_hash="deadbeefcafe",  # different from on-disk
            pid=os.getpid(),  # alive
        )
        text = "\n".join(_run(handler, tmp_path).context).lower()
        assert text != ""
        assert "restart" in text and "ccy" in text
        assert "3.40.0" in text  # running version
        assert "3.41.0" in text  # on-disk version

    def test_dead_pid_is_silent(
        self, handler: CcySupervisorIntegrityHandler, tmp_path: Path
    ) -> None:
        """A stale status file for a supervisor that is no longer running must
        not raise a false alarm."""
        self._arm(tmp_path, version="3.41.0")
        _write_status(tmp_path, version="3.40.0", source_hash="deadbeefcafe", pid=os.getpid())
        with patch.object(handler, "_pid_alive", return_value=False):
            assert _run(handler, tmp_path).context == []
