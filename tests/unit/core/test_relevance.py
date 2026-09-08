"""Tests for the handler relevance primitive (Plan 00330, Decision 1).

A handler declares WHEN it is relevant to a project rather than whether it
is exempt from the config-optimisation review. ``Relevance`` is the verdict;
``RelevanceContext`` is the cheap, pre-computed view of the project the
verdict is decided against.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.relevance import (
    Relevance,
    RelevanceContext,
    detect_languages,
)


class TestRelevance:
    def test_always_is_applicable_with_a_reason(self) -> None:
        verdict = Relevance.always()
        assert verdict.applicable is True
        assert verdict.reason

    def test_when_true_uses_the_present_reason(self) -> None:
        verdict = Relevance.when(True, present="package.json found", absent="no package.json")
        assert verdict.applicable is True
        assert verdict.reason == "package.json found"

    def test_when_false_uses_the_absent_reason(self) -> None:
        verdict = Relevance.when(False, present="package.json found", absent="no package.json")
        assert verdict.applicable is False
        assert verdict.reason == "no package.json"

    def test_is_frozen(self) -> None:
        verdict = Relevance.always()
        with pytest.raises(dataclasses.FrozenInstanceError):
            dataclasses.replace(verdict).__setattr__("applicable", False)


class TestDetectLanguages:
    def test_empty_directory_detects_nothing(self, tmp_path: Path) -> None:
        assert detect_languages(tmp_path) == frozenset()

    def test_marker_files_map_to_languages(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "package.json").write_text("{}\n")
        (tmp_path / "tsconfig.json").write_text("{}\n")
        (tmp_path / "composer.json").write_text("{}\n")
        (tmp_path / "go.mod").write_text("module x\n")
        (tmp_path / "Cargo.toml").write_text("[package]\n")
        (tmp_path / "pom.xml").write_text("<project/>\n")
        assert detect_languages(tmp_path) == frozenset(
            {"python", "javascript", "typescript", "php", "go", "rust", "java"}
        )

    def test_missing_root_detects_nothing(self, tmp_path: Path) -> None:
        assert detect_languages(tmp_path / "absent") == frozenset()


class TestRelevanceContext:
    def test_probe_reads_the_project(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}\n")
        context = RelevanceContext.probe(tmp_path)
        assert context.project_root == tmp_path
        assert "javascript" in context.languages

    def test_declared_languages_override_detection(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}\n")
        context = RelevanceContext.probe(tmp_path, declared_languages=["PHP"])
        assert context.languages == frozenset({"php"})

    def test_has_file_is_relative_to_root(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "x.md").write_text("x\n")
        context = RelevanceContext.probe(tmp_path)
        assert context.has_file(".claude", "x.md") is True
        assert context.has_file(".claude", "y.md") is False

    def test_uses_any_language(self, tmp_path: Path) -> None:
        context = RelevanceContext(project_root=tmp_path, languages=frozenset({"go"}))
        assert context.uses_any_language("javascript", "go") is True
        assert context.uses_any_language("javascript", "typescript") is False
