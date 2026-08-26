"""Tests for skill_scan.models (Plan 00274)."""

from __future__ import annotations

from claude_code_hooks_daemon.skill_scan.models import (
    Cluster,
    Prompt,
    ScanStats,
    SkillScanOptions,
)


class TestPrompt:
    def test_prompt_fields(self) -> None:
        prompt = Prompt(text="hello", session_id="s1", mtime=1.0)
        assert prompt.text == "hello"
        assert prompt.session_id == "s1"
        assert prompt.mtime == 1.0


class TestCluster:
    def test_distinct_sessions_counts_unique(self) -> None:
        cluster = Cluster(
            key_tokens=frozenset({"a"}),
            prompts=[
                Prompt("x", "s1", 1.0),
                Prompt("y", "s1", 2.0),
                Prompt("z", "s2", 3.0),
            ],
        )
        assert cluster.distinct_sessions == 2

    def test_representative_is_longest_prompt_truncated(self) -> None:
        long_text = "b" * 500
        cluster = Cluster(
            key_tokens=frozenset({"a"}),
            prompts=[Prompt("short", "s1", 1.0), Prompt(long_text, "s2", 2.0)],
        )
        assert cluster.representative.startswith("b")
        assert len(cluster.representative) <= 200


class TestScanStats:
    def test_defaults_are_zero(self) -> None:
        stats = ScanStats()
        assert stats.files == 0
        assert stats.lines == 0
        assert stats.user_records == 0
        assert stats.unparseable == 0
        assert stats.genuine == 0


class TestSkillScanOptions:
    def test_defaults(self) -> None:
        options = SkillScanOptions.from_dict({})
        assert options.check_interval_days == 7
        assert options.transcript_window_days == 14
        assert options.model == "haiku"
        assert options.max_prompts == 100
        assert options.extra_exclude_patterns == ()
        assert options.transcript_dir is None

    def test_overrides_applied(self) -> None:
        options = SkillScanOptions.from_dict(
            {
                "check_interval_days": 3,
                "transcript_window_days": 30,
                "model": "sonnet",
                "max_prompts": 50,
                "extra_exclude_patterns": ["<custom-marker>"],
                "transcript_dir": "/tmp/x",
            }
        )
        assert options.check_interval_days == 3
        assert options.transcript_window_days == 30
        assert options.model == "sonnet"
        assert options.max_prompts == 50
        assert options.extra_exclude_patterns == ("<custom-marker>",)
        assert options.transcript_dir == "/tmp/x"

    def test_invalid_values_fall_back_to_defaults(self) -> None:
        options = SkillScanOptions.from_dict(
            {
                "check_interval_days": "not-a-number",
                "max_prompts": None,
                "extra_exclude_patterns": "not-a-list",
            }
        )
        assert options.check_interval_days == 7
        assert options.max_prompts == 100
        assert options.extra_exclude_patterns == ()
