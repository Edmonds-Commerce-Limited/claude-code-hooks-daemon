"""Tests for ``DocumentationConfig`` (Plan 00284, Task 3.1a)."""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import (
    Config,
    DocumentationConfig,
    DocumentationGeneratedDocEntry,
    DocumentationQaConfig,
    DocumentationTreesConfig,
)


class TestDefaults:
    def test_ships_disabled(self) -> None:
        assert DocumentationConfig().enabled is False

    def test_default_trees(self) -> None:
        trees = DocumentationConfig().trees
        assert trees.agent == "CLAUDE"
        assert trees.human == "docs"

    def test_default_qa_modes(self) -> None:
        qa = DocumentationConfig().qa
        assert qa.edit_mode == "warn"
        assert qa.commit_gate_mode == "warn"
        assert qa.sweep_mode == "advise"
        assert qa.check_modes == {}
        assert qa.grandfather_allowlist == []
        assert qa.registered_module_docs == []
        assert qa.resident_at_imports == ["CLAUDE.md"]
        assert qa.scope_exclude_globs == []

    def test_generated_docs_pre_seeded_with_hooks_daemon_md(self) -> None:
        entries = DocumentationConfig().qa.generated_docs
        assert len(entries) == 1
        assert entries[0].glob == ".claude/HOOKS-DAEMON.md"
        assert entries[0].generator == "bin/hooks-daemon generate-docs"


class TestConfigCarriesADocumentationBlock:
    def test_absent_block_gets_defaults(self) -> None:
        config = Config()
        assert config.documentation.enabled is False
        assert isinstance(config.documentation, DocumentationConfig)

    def test_parses_full_block(self) -> None:
        raw = {
            "documentation": {
                "enabled": True,
                "trees": {"agent": "AgentDocs", "human": "HumanDocs"},
                "qa": {
                    "edit_mode": "block",
                    "commit_gate_mode": "block",
                    "sweep_mode": "off",
                    "check_modes": {"pointer-resolves": "block"},
                    "grandfather_allowlist": ["CLAUDE/Legacy/*.md"],
                    "generated_docs": [{"glob": "docs/GEN.md", "generator": "make docs"}],
                    "registered_module_docs": ["src/foo/CLAUDE.md"],
                    "resident_at_imports": ["CLAUDE.md", "AgentDocs/Extra.md"],
                    "scope_exclude_globs": ["CLAUDE/UPGRADES/v[0-9]*/**"],
                },
            }
        }
        config = Config.model_validate(raw)
        assert config.documentation.enabled is True
        assert config.documentation.trees.agent == "AgentDocs"
        assert config.documentation.trees.human == "HumanDocs"
        assert config.documentation.qa.edit_mode == "block"
        assert config.documentation.qa.check_modes == {"pointer-resolves": "block"}
        assert config.documentation.qa.generated_docs[0].glob == "docs/GEN.md"
        assert config.documentation.qa.registered_module_docs == ["src/foo/CLAUDE.md"]
        assert config.documentation.qa.resident_at_imports == [
            "CLAUDE.md",
            "AgentDocs/Extra.md",
        ]
        assert config.documentation.qa.scope_exclude_globs == ["CLAUDE/UPGRADES/v[0-9]*/**"]


class TestStrictValidation:
    def test_rejects_unknown_top_level_key(self) -> None:
        with pytest.raises(ValidationError):
            DocumentationConfig.model_validate({"bogus": True})

    def test_rejects_unknown_qa_key(self) -> None:
        with pytest.raises(ValidationError):
            DocumentationQaConfig.model_validate({"bogus": True})

    def test_rejects_unknown_trees_key(self) -> None:
        with pytest.raises(ValidationError):
            DocumentationTreesConfig.model_validate({"bogus": True})

    def test_rejects_invalid_edit_mode(self) -> None:
        with pytest.raises(ValidationError):
            DocumentationQaConfig.model_validate({"edit_mode": "bogus"})

    def test_rejects_invalid_sweep_mode(self) -> None:
        with pytest.raises(ValidationError):
            DocumentationQaConfig.model_validate({"sweep_mode": "bogus"})

    def test_generated_doc_entry_requires_both_fields(self) -> None:
        with pytest.raises(ValidationError):
            DocumentationGeneratedDocEntry.model_validate({"glob": "docs/GEN.md"})
