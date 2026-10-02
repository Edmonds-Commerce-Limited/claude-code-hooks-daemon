"""Tests for the ``secret-meta`` CLI subcommand (Plan 00272 Phase 5)."""

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_secret_meta


def _run(capsys: pytest.CaptureFixture[str], project_root: Path, target: Path) -> dict[str, object]:
    args = argparse.Namespace(project_root=project_root, path=target)
    exit_code = cmd_secret_meta(args)
    assert exit_code == 0
    payload: dict[str, object] = json.loads(capsys.readouterr().out)
    return payload


class TestCmdSecretMeta:
    def test_reports_metadata_without_content(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        secret = tmp_path / "fixture.vault-password"
        secret.write_text("hunter2\n")
        secret.chmod(0o600)
        meta = _run(capsys, tmp_path, secret)
        assert meta["exists"] is True
        assert "size_bucket" in meta
        assert "hunter2" not in json.dumps(meta)

    def test_missing_file_is_a_valid_answer(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        meta = _run(capsys, tmp_path, tmp_path / "absent")
        assert meta["exists"] is False

    def test_plain_hash_requires_config_option(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exact size/sha256 only when the HANDLER config says so — no CLI flag."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text(
            "handlers:\n"
            "  pre_tool_use:\n"
            "    secret_file_guard:\n"
            "      enabled: true\n"
            "      options:\n"
            "        allow_plain_hash: true\n"
        )
        secret = tmp_path / "fixture.vault-password"
        secret.write_text("hunter2\n")
        meta = _run(capsys, tmp_path, secret)
        assert meta["size_bytes"] == 8
        assert "sha256" in meta


def _grant_plain_hash(root: Path) -> None:
    claude_dir = root / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "hooks-daemon.yaml").write_text(
        "handlers:\n"
        "  pre_tool_use:\n"
        "    secret_file_guard:\n"
        "      enabled: true\n"
        "      options:\n"
        "        allow_plain_hash: true\n"
    )


class TestPlainHashIsGrantedOnlyByTheFilesOwnProject:
    """Plan 00483 N230: a config elsewhere is nobody's decision about this file."""

    def test_a_config_outside_the_files_project_never_grants_the_plain_hash(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        grant_root = tmp_path / "scratch"
        _grant_plain_hash(grant_root)
        secret = tmp_path / "fixture.vault-password"
        secret.write_text("hunter2\n")

        meta = _run(capsys, grant_root, secret)

        assert meta["exists"] is True
        assert "size_bucket" in meta
        assert "sha256" not in meta
        assert "size_bytes" not in meta

    def test_a_symlink_under_the_granting_root_is_placed_where_it_points(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        grant_root = tmp_path / "scratch"
        _grant_plain_hash(grant_root)
        secret = tmp_path / "fixture.vault-password"
        secret.write_text("hunter2\n")
        link = grant_root / "link.vault-password"
        link.symlink_to(secret)

        meta = _run(capsys, grant_root, link)

        assert "sha256" not in meta
        assert "size_bytes" not in meta
