"""Tests for ``docs_qa.policy`` (Plan 00284, Task 3.1a)."""

from dataclasses import FrozenInstanceError, dataclass, field
from typing import Any

import pytest

from claude_code_hooks_daemon.docs_qa.policy import (
    DEFAULT_AGENT_TREE,
    DEFAULT_HUMAN_TREE,
    DEFAULT_RESIDENT_AT_IMPORTS,
    DocumentationPolicy,
    DocumentationQaPolicy,
    DocumentationTreesPolicy,
    policy_from_config,
)


class TestDefaults:
    def test_policy_defaults(self) -> None:
        policy = DocumentationPolicy()
        assert policy.enabled is False
        assert policy.trees.agent == DEFAULT_AGENT_TREE
        assert policy.trees.human == DEFAULT_HUMAN_TREE
        assert policy.qa.edit_mode == "warn"
        assert policy.qa.commit_gate_mode == "warn"
        assert policy.qa.sweep_mode == "advise"
        assert policy.qa.check_modes == {}
        assert policy.qa.grandfather_allowlist == ()
        assert policy.qa.generated_docs == ()
        assert policy.qa.registered_module_docs == ()
        assert policy.qa.resident_at_imports == DEFAULT_RESIDENT_AT_IMPORTS


@dataclass(frozen=True)
class _FakeGeneratedDocEntry:
    glob: str
    generator: str


@dataclass(frozen=True)
class _FakeTreesConfig:
    agent: str = "AgentDocs"
    human: str = "HumanDocs"


@dataclass(frozen=True)
class _FakeQaConfig:
    edit_mode: str = "block"
    commit_gate_mode: str = "block"
    sweep_mode: str = "off"
    check_modes: dict[str, str] = field(default_factory=lambda: {"pointer-resolves": "block"})
    grandfather_allowlist: list[str] = field(default_factory=lambda: ["CLAUDE/Legacy/*.md"])
    generated_docs: list[Any] = field(
        default_factory=lambda: [_FakeGeneratedDocEntry("docs/GEN.md", "make docs")]
    )
    registered_module_docs: list[str] = field(default_factory=lambda: ["src/foo/CLAUDE.md"])
    resident_at_imports: list[str] = field(default_factory=lambda: ["CLAUDE.md", "Extra.md"])


@dataclass(frozen=True)
class _FakeDocumentationConfig:
    enabled: bool = True
    trees: _FakeTreesConfig = field(default_factory=_FakeTreesConfig)
    qa: _FakeQaConfig = field(default_factory=_FakeQaConfig)


class TestPolicyFromConfig:
    def test_copies_every_field(self) -> None:
        policy = policy_from_config(_FakeDocumentationConfig())
        assert isinstance(policy, DocumentationPolicy)
        assert policy.enabled is True
        assert policy.trees == DocumentationTreesPolicy(agent="AgentDocs", human="HumanDocs")
        assert policy.qa.edit_mode == "block"
        assert policy.qa.commit_gate_mode == "block"
        assert policy.qa.sweep_mode == "off"
        assert policy.qa.check_modes == {"pointer-resolves": "block"}
        assert policy.qa.grandfather_allowlist == ("CLAUDE/Legacy/*.md",)
        assert policy.qa.generated_docs[0].glob == "docs/GEN.md"
        assert policy.qa.generated_docs[0].generator == "make docs"
        assert policy.qa.registered_module_docs == ("src/foo/CLAUDE.md",)
        assert policy.qa.resident_at_imports == ("CLAUDE.md", "Extra.md")

    def test_uses_the_real_pydantic_config_shape(self) -> None:
        """The real config model must satisfy the structural Protocol."""
        from claude_code_hooks_daemon.config.models import DocumentationConfig

        policy = policy_from_config(DocumentationConfig())
        assert isinstance(policy, DocumentationPolicy)
        assert policy.qa.generated_docs[0].glob == ".claude/HOOKS-DAEMON.md"


class TestPlainDataclasses:
    def test_qa_policy_is_frozen(self) -> None:
        policy = DocumentationQaPolicy()
        with pytest.raises(FrozenInstanceError):
            policy.edit_mode = "block"
