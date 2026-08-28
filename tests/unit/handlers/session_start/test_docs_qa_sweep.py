"""Tests for DocsQaSweepHandler (Plan 00284, Task 3.1c).

Whole-corpus docs QA drift report at session start: builds/refreshes the
doc corpus index (the explicit-build half of the cold-index rule), runs
the SWEEP-stage catalogue, and injects ONE compact advisory. Silent when
the corpus is clean; new sessions only.
"""

from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
from claude_code_hooks_daemon.handlers.session_start.docs_qa_sweep import DocsQaSweepHandler


def _handler(policy: DocumentationPolicy | None = None) -> DocsQaSweepHandler:
    handler = DocsQaSweepHandler()
    handler._documentation = policy if policy is not None else DocumentationPolicy(enabled=True)
    return handler


def _patched_context(root: Path, untracked: Path) -> tuple:
    return (
        patch(
            "claude_code_hooks_daemon.handlers.session_start.docs_qa_sweep."
            "ProjectContext.project_root",
            return_value=root,
        ),
        patch(
            "claude_code_hooks_daemon.handlers.session_start.docs_qa_sweep."
            "ProjectContext.daemon_untracked_dir",
            return_value=untracked,
        ),
    )


class TestInit:
    def test_identity(self) -> None:
        handler = DocsQaSweepHandler()
        assert handler.name == "docs-qa-sweep"
        assert handler.terminal is False
        assert "documentation" in handler.tags


class TestMatches:
    def test_matches_new_session_when_enabled(self) -> None:
        assert _handler().matches({"source": "startup"}) is True

    def test_ignores_resumed_session(self, tmp_path: Path) -> None:
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200)
        hook_input = {"source": "resume", "transcript_path": str(transcript)}
        assert _handler().matches(hook_input) is False

    def test_skips_without_policy(self) -> None:
        handler = DocsQaSweepHandler()
        assert handler.matches({"source": "startup"}) is False

    def test_skips_when_documentation_disabled(self) -> None:
        handler = _handler(policy=DocumentationPolicy(enabled=False))
        assert handler.matches({"source": "startup"}) is False

    def test_skips_when_sweep_mode_off(self) -> None:
        policy = DocumentationPolicy(enabled=True, qa=DocumentationQaPolicy(sweep_mode="off"))
        handler = _handler(policy)
        assert handler.matches({"source": "startup"}) is False


class TestHandle:
    def test_clean_corpus_produces_no_context(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "X.md").write_text("# clean\n")
        untracked = tmp_path / "untracked"
        patches = _patched_context(tmp_path, untracked)
        with patches[0], patches[1]:
            result = _handler().handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_drift_produces_advisory_context_with_cli_pointer(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "X.md").write_text("See [missing](Nope.md).\n")
        untracked = tmp_path / "untracked"
        patches = _patched_context(tmp_path, untracked)
        with patches[0], patches[1]:
            result = _handler().handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        assert result.context
        joined = "\n".join(result.context)
        assert "pointer-resolves" in joined
        assert "docs-qa" in joined
        assert "--sweep" in joined

    def test_builds_and_persists_the_corpus_index(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "X.md").write_text("# clean\n")
        untracked = tmp_path / "untracked"
        patches = _patched_context(tmp_path, untracked)
        with patches[0], patches[1]:
            _handler().handle({"source": "startup"})
        assert (untracked / "docs-qa" / "index.json").is_file()


class TestClaudeMdAndAcceptanceTests:
    def test_get_claude_md_returns_content(self) -> None:
        content = DocsQaSweepHandler().get_claude_md()
        assert content is not None
        assert "docs_qa_sweep" in content

    def test_get_acceptance_tests_returns_list(self) -> None:
        tests = DocsQaSweepHandler().get_acceptance_tests()
        assert len(tests) >= 1
