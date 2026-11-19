"""Tests for the automatic-upgrade eligibility pre-check (Plan 00625)."""

import dataclasses
import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.auto_upgrade import (
    ATTEMPT_DIR_NAME,
    UPGRADE_OWNED_PATHS,
    AttemptStatus,
    Eligibility,
    attempt_state_path,
    check_eligibility,
    project_authorises_auto_upgrade,
    read_attempt_record,
)


def _write_attempt(untracked: Path, version: str, text: str) -> Path:
    path = untracked / ATTEMPT_DIR_NAME / f"v{version}.state"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return path


class TestAttemptRecords:
    def test_dir_name_is_the_documented_one(self) -> None:
        assert ATTEMPT_DIR_NAME == "auto-upgrade"

    def test_path_is_under_the_attempt_dir(self, tmp_path: Path) -> None:
        assert attempt_state_path(tmp_path, "3.76.0") == tmp_path / "auto-upgrade" / "v3.76.0.state"

    def test_absent_record_is_none(self, tmp_path: Path) -> None:
        assert read_attempt_record(tmp_path, "3.76.0") is None

    def test_reads_every_field(self, tmp_path: Path) -> None:
        path = _write_attempt(
            tmp_path,
            "3.76.0",
            "status=needs-human\ntarget=3.76.0\nfrom=3.75.0\ndetail=gate escalated\n",
        )
        record = read_attempt_record(tmp_path, "3.76.0")
        assert record is not None
        assert record.status is AttemptStatus.NEEDS_HUMAN
        assert record.target == "3.76.0"
        assert record.from_version == "3.75.0"
        assert record.detail == "gate escalated"
        assert record.state_path == path

    def test_failed_status(self, tmp_path: Path) -> None:
        _write_attempt(tmp_path, "3.76.0", "status=failed\ndetail=rolled back\n")
        record = read_attempt_record(tmp_path, "3.76.0")
        assert record is not None
        assert record.status is AttemptStatus.FAILED

    def test_unknown_status_reads_as_failed_saying_so(self, tmp_path: Path) -> None:
        _write_attempt(tmp_path, "3.76.0", "status=weird\n")
        record = read_attempt_record(tmp_path, "3.76.0")
        assert record is not None
        assert record.status is AttemptStatus.FAILED
        assert "no known status" in record.detail

    def test_unreadable_file_reads_as_failed(self, tmp_path: Path) -> None:
        path = tmp_path / ATTEMPT_DIR_NAME / "v3.76.0.state"
        path.mkdir(parents=True)  # a directory where a file should be
        record = read_attempt_record(tmp_path, "3.76.0")
        assert record is not None
        assert record.status is AttemptStatus.FAILED
        assert "cannot be read" in record.detail


class TestProjectAuthorises:
    def _config(self, tmp_path: Path, text: str) -> Path:
        path = tmp_path / "hooks-daemon.yaml"
        path.write_text(text)
        return path

    def test_no_handler_block_is_authorised(self, tmp_path: Path) -> None:
        assert project_authorises_auto_upgrade(self._config(tmp_path, "version: '1'\n")) is True

    def test_empty_file_is_authorised(self, tmp_path: Path) -> None:
        assert project_authorises_auto_upgrade(self._config(tmp_path, "")) is True

    def test_explicit_opt_out(self, tmp_path: Path) -> None:
        text = (
            "handlers:\n  user_prompt_submit:\n    standing_authorisations:\n"
            "      options:\n        authorisations:\n"
            "          - id: daemon-auto-upgrade\n            enabled: false\n"
        )
        assert project_authorises_auto_upgrade(self._config(tmp_path, text)) is False

    def test_handler_disabled(self, tmp_path: Path) -> None:
        text = (
            "handlers:\n  user_prompt_submit:\n    standing_authorisations:\n"
            "      enabled: false\n"
        )
        assert project_authorises_auto_upgrade(self._config(tmp_path, text)) is False

    def test_other_entries_leave_the_default(self, tmp_path: Path) -> None:
        text = (
            "handlers:\n  user_prompt_submit:\n    standing_authorisations:\n"
            "      options:\n        authorisations:\n"
            "          - id: subagent-delegation\n            enabled: true\n"
        )
        assert project_authorises_auto_upgrade(self._config(tmp_path, text)) is True

    def test_missing_config_is_not_authorised(self, tmp_path: Path) -> None:
        assert project_authorises_auto_upgrade(tmp_path / "absent.yaml") is False

    def test_invalid_yaml_is_not_authorised(self, tmp_path: Path) -> None:
        assert project_authorises_auto_upgrade(self._config(tmp_path, "a: [unclosed\n")) is False

    def test_non_mapping_document_is_not_authorised(self, tmp_path: Path) -> None:
        assert project_authorises_auto_upgrade(self._config(tmp_path, "- a\n- b\n")) is False


class TestEligibility:
    def _check(
        self,
        tmp_path: Path,
        *,
        installed: str = "3.75.0",
        latest: str = "3.76.0",
        authorised: bool = True,
        self_install: bool = False,
    ) -> Eligibility:
        return check_eligibility(
            installed=installed,
            latest=latest,
            authorised=authorised,
            self_install=self_install,
            project_root=tmp_path / "project",
            untracked_dir=tmp_path / "untracked",
        )

    def test_clean_minor_bump_is_eligible(self, tmp_path: Path) -> None:
        result = self._check(tmp_path)
        assert result.eligible is True
        assert result.reasons == []

    def test_patch_bump_is_eligible(self, tmp_path: Path) -> None:
        assert self._check(tmp_path, latest="3.75.1").eligible is True

    def test_not_authorised(self, tmp_path: Path) -> None:
        result = self._check(tmp_path, authorised=False)
        assert result.eligible is False
        assert any("not authorised" in r for r in result.reasons)

    def test_self_install(self, tmp_path: Path) -> None:
        result = self._check(tmp_path, self_install=True)
        assert result.eligible is False
        assert any("daemon's own repository" in r for r in result.reasons)

    def test_release_in_progress(self, tmp_path: Path) -> None:
        state = tmp_path / "project" / "untracked" / "release-state.json"
        state.parent.mkdir(parents=True)
        state.write_text("{}")
        result = self._check(tmp_path)
        assert result.eligible is False
        assert any("release is in progress" in r for r in result.reasons)

    @pytest.mark.parametrize("latest", ["3.75.0", "3.74.9", "2.99.0"])
    def test_latest_not_newer(self, tmp_path: Path, latest: str) -> None:
        result = self._check(tmp_path, latest=latest)
        assert result.eligible is False
        assert any("not newer" in r for r in result.reasons)

    def test_major_bump(self, tmp_path: Path) -> None:
        result = self._check(tmp_path, latest="4.0.0")
        assert result.eligible is False
        assert any("MAJOR" in r for r in result.reasons)

    def test_unparsable_version_is_refused(self, tmp_path: Path) -> None:
        result = self._check(tmp_path, latest="banana")
        assert result.eligible is False
        assert any("cannot be compared" in r for r in result.reasons)

    def test_attempt_record_refuses_that_version(self, tmp_path: Path) -> None:
        _write_attempt(tmp_path / "untracked", "3.76.0", "status=failed\ndetail=x\n")
        result = self._check(tmp_path)
        assert result.eligible is False
        assert any("already attempted" in r and "failed" in r for r in result.reasons)

    def test_attempt_for_older_version_does_not_block_newer(self, tmp_path: Path) -> None:
        _write_attempt(tmp_path / "untracked", "3.76.0", "status=failed\n")
        assert self._check(tmp_path, latest="3.77.0").eligible is True

    def test_reasons_accumulate(self, tmp_path: Path) -> None:
        result = self._check(tmp_path, authorised=False, self_install=True, latest="4.0.0")
        assert len(result.reasons) == 3

    def test_result_is_frozen(self, tmp_path: Path) -> None:
        result = self._check(tmp_path)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.__setattr__("eligible", False)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@x.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull},
    )


class TestUncommittedWork:
    """Ruling item 5: only the paths the upgrade rewrites, and the clone itself."""

    def _project(self, tmp_path: Path) -> tuple[Path, Path]:
        project = tmp_path / "project"
        project.mkdir()
        _git(project, "init", "-q", "-b", "main")
        (project / ".gitignore").write_text(".claude/hooks-daemon/\n")
        _git(project, "add", ".gitignore")
        _git(project, "commit", "-q", "-m", "p")
        daemon = project / ".claude" / "hooks-daemon"
        daemon.mkdir(parents=True)
        _git(daemon, "init", "-q", "-b", "main")
        (daemon / "f").write_text("x")
        _git(daemon, "add", "f")
        _git(daemon, "commit", "-q", "-m", "d")
        return project, daemon

    def _check(self, project: Path, daemon: Path) -> Eligibility:
        return check_eligibility(
            installed="3.75.0",
            latest="3.76.0",
            authorised=True,
            self_install=False,
            project_root=project,
            untracked_dir=daemon / "untracked",
            daemon_dir=daemon,
        )

    def test_owned_paths_match_the_skill_commit_step(self) -> None:
        assert UPGRADE_OWNED_PATHS == (
            ".claude/hooks-daemon/",
            ".claude/hooks-daemon.yaml",
            ".claude/skills/hooks-daemon/",
            ".claude/hooks/",
            ".claude/settings.json",
        )

    def test_unrelated_uncommitted_work_is_eligible(self, tmp_path: Path) -> None:
        project, daemon = self._project(tmp_path)
        (project / "notes.txt").write_text("x")
        assert self._check(project, daemon).eligible is True

    @pytest.mark.parametrize(
        "path", [".claude/settings.json", ".claude/hooks/h.sh", ".claude/skills/hooks-daemon/S.md"]
    )
    def test_uncommitted_work_in_an_owned_path_refuses(self, tmp_path: Path, path: str) -> None:
        project, daemon = self._project(tmp_path)
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_text("x")
        result = self._check(project, daemon)
        assert result.eligible is False
        assert any(path in r for r in result.reasons)

    def test_uncommitted_work_in_the_clone_refuses(self, tmp_path: Path) -> None:
        project, daemon = self._project(tmp_path)
        (daemon / "f").write_text("changed")
        result = self._check(project, daemon)
        assert result.eligible is False
        assert any("daemon clone" in r for r in result.reasons)
