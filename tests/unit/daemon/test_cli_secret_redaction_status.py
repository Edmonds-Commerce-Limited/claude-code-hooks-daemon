"""Tests for `_collect_secret_redaction_status_lines` (Plan 00305 Task 1.3).

Surfaces the absolute/home-relative `secret_word_list_path` degrade at
`hooks-daemon check` time -- previously only a `logger.warning` a human was
unlikely to ever read.
"""

from pathlib import Path

from claude_code_hooks_daemon.daemon.cli import _collect_secret_redaction_status_lines


class TestCollectSecretRedactionStatusLines:
    def test_no_config_reports_nothing(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        assert _collect_secret_redaction_status_lines(tmp_path) == []

    def test_unconfigured_secret_word_list_path_reports_nothing(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text("version: '1.0'\n", encoding="utf-8")
        assert _collect_secret_redaction_status_lines(tmp_path) == []

    def test_relative_secret_word_list_path_reports_nothing(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text(
            "version: '1.0'\n"
            "handlers:\n"
            "  pre_tool_use:\n"
            "    sensitive_content:\n"
            "      options:\n"
            "        secret_word_list_path: custom/wordlist\n",
            encoding="utf-8",
        )
        assert _collect_secret_redaction_status_lines(tmp_path) == []

    def test_absolute_secret_word_list_path_is_reported(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text(
            "version: '1.0'\n"
            "handlers:\n"
            "  pre_tool_use:\n"
            "    sensitive_content:\n"
            "      options:\n"
            "        secret_word_list_path: /etc/wordlist\n",
            encoding="utf-8",
        )
        lines = _collect_secret_redaction_status_lines(tmp_path)
        assert len(lines) == 1
        assert "/etc/wordlist" in lines[0]

    def test_declared_subproject_absolute_path_is_reported(self, tmp_path: Path) -> None:
        """Plan 00306 Task 2.1: a `projects:`-declared sub-root's OWN
        `.claude/hooks-daemon.yaml` can configure an absolute
        `secret_word_list_path` that degrades silently -- this must be
        surfaced too, not just the primary root's config (mirrors
        `_collect_enforcement_status_lines`'s registry-wide iteration)."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text(
            "version: '1.0'\nprojects:\n  - name: sub\n    root: sub-app\n",
            encoding="utf-8",
        )
        sub_root = tmp_path / "sub-app"
        sub_claude_dir = sub_root / ".claude"
        sub_claude_dir.mkdir(parents=True)
        (sub_claude_dir / "hooks-daemon.yaml").write_text(
            "version: '1.0'\n"
            "handlers:\n"
            "  pre_tool_use:\n"
            "    sensitive_content:\n"
            "      options:\n"
            "        secret_word_list_path: /etc/sub-wordlist\n",
            encoding="utf-8",
        )
        lines = _collect_secret_redaction_status_lines(tmp_path)
        assert len(lines) == 1
        assert "/etc/sub-wordlist" in lines[0]

    def test_malformed_config_reports_nothing_rather_than_raising(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "hooks-daemon.yaml").write_text("not: [valid, yaml, :", encoding="utf-8")
        # Must not raise.
        assert _collect_secret_redaction_status_lines(tmp_path) == []
