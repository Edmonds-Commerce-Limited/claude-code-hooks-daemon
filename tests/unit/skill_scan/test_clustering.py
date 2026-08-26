"""Tests for skill_scan.clustering (Plan 00274).

Heuristic fixed by PLAN.md Decision 4: token-set Jaccard, threshold 0.5.
"""

from __future__ import annotations

from claude_code_hooks_daemon.skill_scan.clustering import cluster_prompts, normalise
from claude_code_hooks_daemon.skill_scan.constants import (
    NUM_PLACEHOLDER,
    PATH_PLACEHOLDER,
    SHA_PLACEHOLDER,
)
from claude_code_hooks_daemon.skill_scan.models import Prompt


class TestNormalise:
    def test_paths_and_numbers_become_placeholders(self) -> None:
        out = normalise("Fix test in /workspace/tests/unit/x.py line 42")
        assert "/workspace" not in out
        assert "42" not in out
        assert PATH_PLACEHOLDER in out
        assert NUM_PLACEHOLDER in out

    def test_shas_become_placeholders(self) -> None:
        out = normalise("cherry-pick abc1234def onto main")
        assert "abc1234def" not in out
        assert SHA_PLACEHOLDER in out

    def test_two_variants_normalise_identically(self) -> None:
        assert normalise("fix the test in tests/unit/a.py") == normalise(
            "Fix the test in tests/unit/b.py"
        )

    def test_whitespace_collapsed(self) -> None:
        assert normalise("a   b\n\nc") == "a b c"


class TestClusterPrompts:
    def test_near_identical_prompts_cluster(self) -> None:
        prompts = [
            Prompt("run qa then restart the daemon and verify", "s1", 1.0),
            Prompt("run qa then restart the daemon and verify it", "s2", 2.0),
            Prompt("write a haiku about penguins", "s3", 3.0),
        ]
        clusters = cluster_prompts(prompts)
        assert sorted(len(c.prompts) for c in clusters) == [1, 2]

    def test_cluster_counts_distinct_sessions(self) -> None:
        prompts = [
            Prompt("same prompt again", "s1", 1.0),
            Prompt("same prompt again", "s1", 2.0),
            Prompt("same prompt again", "s2", 3.0),
        ]
        clusters = cluster_prompts(prompts)
        assert len(clusters) == 1
        assert clusters[0].distinct_sessions == 2
        assert len(clusters[0].prompts) == 3

    def test_clusters_ranked_by_distinct_sessions_then_size(self) -> None:
        prompts = [
            Prompt("alpha beta gamma delta", "s1", 1.0),
            Prompt("alpha beta gamma delta", "s1", 2.0),
            Prompt("one two three four", "s1", 3.0),
            Prompt("one two three four", "s2", 4.0),
        ]
        clusters = cluster_prompts(prompts)
        assert clusters[0].distinct_sessions == 2

    def test_empty_input_yields_no_clusters(self) -> None:
        assert cluster_prompts([]) == []
