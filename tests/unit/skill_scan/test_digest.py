"""Tests for skill_scan.digest (Plan 00274).

The digest is the privacy bulwark: everything the model ever sees passes
through here — redacted, truncated and capped.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.skill_scan.constants import MAX_PAYLOAD_CHARS
from claude_code_hooks_daemon.skill_scan.digest import (
    build_digest,
    build_model_prompt,
    existing_skill_names,
)
from claude_code_hooks_daemon.skill_scan.models import Cluster, Prompt


def _cluster(text: str, sessions: int = 1) -> Cluster:
    prompts = [Prompt(text, f"s{i}", float(i)) for i in range(sessions)]
    return Cluster(key_tokens=frozenset(text.split()), prompts=prompts)


class TestBuildDigest:
    def test_lines_carry_counts_and_normalised_representative(self) -> None:
        digest = build_digest([_cluster("Deploy The Thing", sessions=3)], terms=())
        assert "count=3" in digest
        assert "sessions=3" in digest
        # The representative is NORMALISED before it can reach the model:
        # lowercased, with paths/shas/numbers collapsed to placeholders.
        assert "deploy the thing" in digest
        assert "Deploy The Thing" not in digest

    def test_paths_in_prompts_never_reach_digest(self) -> None:
        digest = build_digest(
            [_cluster("fix the test in /workspace/tests/unit/secret_area/x.py now")],
            terms=(),
        )
        assert "/workspace" not in digest
        assert "secret_area" not in digest
        from claude_code_hooks_daemon.skill_scan.constants import PATH_PLACEHOLDER

        assert PATH_PLACEHOLDER in digest

    def test_secret_terms_are_redacted(self) -> None:
        digest = build_digest([_cluster("please rotate hunter2 now")], terms=("hunter2",))
        assert "hunter2" not in digest
        assert "[REDACTED]" in digest

    def test_cluster_cap_applied(self) -> None:
        clusters = [_cluster(f"unique prompt number {i} xyz") for i in range(200)]
        digest = build_digest(clusters, terms=(), max_clusters=5)
        assert digest.count("\n") <= 5

    def test_payload_char_cap_applied(self) -> None:
        clusters = [_cluster("word " * 60 + str(i)) for i in range(2000)]
        digest = build_digest(clusters, terms=(), max_clusters=2000)
        assert len(digest) <= MAX_PAYLOAD_CHARS

    def test_newlines_in_representative_flattened(self) -> None:
        digest = build_digest([_cluster("line one\nline two")], terms=())
        assert "line one line two" in digest


class TestExistingSkillNames:
    def test_lists_skill_and_command_dirs(self, tmp_path: Path) -> None:
        (tmp_path / ".claude" / "skills" / "release").mkdir(parents=True)
        (tmp_path / ".claude" / "commands" / "deploy").mkdir(parents=True)
        names = existing_skill_names(tmp_path)
        assert "release" in names
        assert "deploy" in names

    def test_markdown_command_files_listed_without_extension(self, tmp_path: Path) -> None:
        commands = tmp_path / ".claude" / "commands"
        commands.mkdir(parents=True)
        (commands / "ship.md").write_text("do the ship")
        assert "ship" in existing_skill_names(tmp_path)

    def test_missing_dirs_yield_empty(self, tmp_path: Path) -> None:
        assert existing_skill_names(tmp_path) == []


class TestBuildModelPrompt:
    def test_prompt_carries_digest_inventory_and_rubric(self) -> None:
        prompt = build_model_prompt("[1] count=2 rep='x'", ["release", "configure"])
        assert "[1] count=2" in prompt
        assert "release, configure" in prompt
        assert "JSON" in prompt
        assert "workloads" in prompt
        assert "corrections" in prompt

    def test_empty_inventory_rendered(self) -> None:
        prompt = build_model_prompt("digest", [])
        assert "(none)" in prompt
