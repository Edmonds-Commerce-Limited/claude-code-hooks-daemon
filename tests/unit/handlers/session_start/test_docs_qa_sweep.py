"""Tests for DocsQaSweepHandler (Plan 00284, Task 3.1c).

Whole-corpus docs QA drift report at session start: builds/refreshes the
doc corpus index (the explicit-build half of the cold-index rule), runs
the SWEEP-stage catalogue, and injects ONE compact advisory. Silent when
the corpus is clean; new sessions only.
"""

import threading
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.docs_qa.runner import run_stage
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
from claude_code_hooks_daemon.handlers.session_start.docs_qa_sweep import DocsQaSweepHandler


def _handler(policy: DocumentationPolicy | None = None) -> DocsQaSweepHandler:
    handler = DocsQaSweepHandler()
    handler._documentation = policy if policy is not None else DocumentationPolicy(enabled=True)
    # A cold sweep is awaited in full so these tests are not timing-dependent;
    # TestSweepCache sets it to zero where the pending path is the point.
    handler._sweep_wait_seconds = 60.0
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

    def test_get_claude_md_source_tree_markdown_text_matches_check_semantics(self) -> None:
        """Task 2.1 (Plan 00295): the injected guidance previously claimed
        source-tree-markdown 'stays silent when no `layout:` source/test
        dirs are declared', but `test_dirs` always has a built-in
        cross-language fallback (`ProjectLayout`'s `_BUILTIN_TEST_DIRS`), so
        TEST-dir findings can fire in zero-config -- only SOURCE-dir
        findings stay dormant undeclared. The injected text must match the
        check module's own (accurate) docstring, not contradict it.
        """
        content = DocsQaSweepHandler().get_claude_md()
        assert content is not None
        assert "stays silent when no `layout:` source/test dirs are declared" not in content
        assert "SOURCE-dir findings stay" in content
        assert "TEST-dir\nfindings can fire" in content

    def test_get_acceptance_tests_returns_list(self) -> None:
        tests = DocsQaSweepHandler().get_acceptance_tests()
        assert len(tests) >= 1


class TestProjectExcludePaths:
    """Plan 00362 Task 2.9: drift inside ``daemon.exclude_paths`` is not swept."""

    def test_drift_in_an_excluded_file_is_silent(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE" / "fixtures").mkdir(parents=True)
        (tmp_path / "CLAUDE" / "fixtures" / "X.md").write_text("See [missing](Nope.md).\n")
        untracked = tmp_path / "untracked"
        policy = DocumentationPolicy(enabled=True, exclude_paths=("CLAUDE/fixtures/**",))
        patches = _patched_context(tmp_path, untracked)
        with patches[0], patches[1]:
            result = _handler(policy).handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_get_claude_md_names_the_exclusion(self) -> None:
        content = DocsQaSweepHandler().get_claude_md()
        assert content is not None
        assert "daemon.exclude_paths" in content


_RUN_STAGE = "claude_code_hooks_daemon.handlers.session_start.docs_qa_sweep.run_stage"


class TestSweepCache:
    """Plan 00495 Task 2.6: the sweep is cached by input fingerprint, off the chain."""

    def _handle(self, handler: DocsQaSweepHandler, root: Path) -> list[str]:
        patches = _patched_context(root, root / "untracked")
        with patches[0], patches[1]:
            return handler.handle({"source": "startup"}).context

    def test_unchanged_inputs_reuse_the_cached_report(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "X.md").write_text("See [missing](Nope.md).\n")
        handler = _handler()
        with patch(_RUN_STAGE, wraps=run_stage) as sweep:
            first = self._handle(handler, tmp_path)
            second = self._handle(handler, tmp_path)
        assert first
        assert second == first
        assert sweep.call_count == 1

    def test_editing_a_scanned_file_invalidates_the_cache(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        doc = tmp_path / "CLAUDE" / "X.md"
        doc.write_text("# clean\n")
        handler = _handler()
        assert self._handle(handler, tmp_path) == []

        doc.write_text("See [missing](Nope.md).\n")

        assert "pointer-resolves" in "\n".join(self._handle(handler, tmp_path))

    def test_fixing_drift_clears_the_cached_report(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        doc = tmp_path / "CLAUDE" / "X.md"
        doc.write_text("See [missing](Nope.md).\n")
        handler = _handler()
        assert self._handle(handler, tmp_path)

        doc.write_text("# clean\n")

        assert self._handle(handler, tmp_path) == []

    def test_removing_a_linked_non_markdown_file_surfaces_the_dead_link(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "X.md").write_text("See [tool](../tool.py).\n")
        target = tmp_path / "tool.py"
        target.write_text("x = 1\n")
        handler = _handler()
        assert self._handle(handler, tmp_path) == []

        target.unlink()

        assert "pointer-resolves" in "\n".join(self._handle(handler, tmp_path))

    def test_policy_change_invalidates_the_cache(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE" / "fixtures").mkdir(parents=True)
        (tmp_path / "CLAUDE" / "fixtures" / "X.md").write_text("See [missing](Nope.md).\n")
        excluded = DocumentationPolicy(enabled=True, exclude_paths=("CLAUDE/fixtures/**",))
        assert self._handle(_handler(excluded), tmp_path) == []

        assert self._handle(_handler(), tmp_path)

    def test_slow_sweep_is_reported_pending_without_blocking_the_chain(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "X.md").write_text("# clean\n")
        handler = _handler()
        handler._sweep_wait_seconds = 0.0
        release = threading.Event()

        def slow(*args: object, **kwargs: object) -> list[object]:
            release.wait(60.0)
            return []

        with patch(_RUN_STAGE, side_effect=slow):
            context = self._handle(handler, tmp_path)
            release.set()

        text = "\n".join(context)
        assert "background" in text
        assert "docs-qa" in text
        assert "--sweep" in text
