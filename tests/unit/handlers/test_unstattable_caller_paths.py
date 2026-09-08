"""Handlers must return a decision for a path they cannot stat.

``pathlib`` swallows the stat failures it considers expected -- ENOENT,
ENOTDIR, EBADF, ELOOP -- and answers ``False``. **EACCES is not in that set**,
so ``exists()``, ``is_file()`` and ``is_dir()`` raise ``PermissionError`` when
any ancestor directory lacks ``+x`` for the daemon's user. The paths below all
originate in a user's tool input, so the daemon has no say in whether it can
stat them.

``chain.py`` catching the raise is not a fix. It becomes a silent exemption
under ``strict_mode: false`` (the client default) or a spurious crash-DENY
under ``strict_mode: true`` (this repository) -- two different wrong answers,
neither of them a decision the handler made.

**This file covers the 11 sites where ``False`` is the right answer.** The
other three are elsewhere because they are not this shape:
``write_clobber_guard`` needs ``True`` (``False`` exempts the guard --
``test_write_clobber_guard_unreadable_target.py``), and the ``plan_qa_edit`` /
``docs_qa_edit`` pair feeds a tri-state to consumers that disagree about what
``False`` means.

Every test FORCES the error, and forces it only for paths carrying
``UNREADABLE``. A blanket patch would break config loading and project
resolution, and a permission-based fixture reproduces nothing at all when the
suite runs as root -- which is exactly how the originating instance reached CI
unnoticed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer

_MARKER: Final[str] = "UNREADABLE"
_UNREADABLE_PY: Final[str] = "/root/UNREADABLE/src/module.py"
_UNREADABLE_MD: Final[str] = "/root/UNREADABLE/docs/table.md"
_UNREADABLE_TS: Final[str] = "/root/UNREADABLE/src/component.ts"


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture(autouse=True)
def _stub_project_root() -> Iterator[None]:
    """Several handlers resolve the project root while constructing. That is
    daemon-controlled wiring, not the caller-supplied path under test."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/workspace")
        yield


@pytest.fixture
def deny_marked_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise EACCES for any path containing ``UNREADABLE``, as a real
    untraversable ancestor does -- and leave every other path alone, so the
    daemon's own config and project resolution keep working."""
    originals: dict[str, Callable[[Path], bool]] = {
        name: getattr(Path, name) for name in ("exists", "is_file", "is_dir")
    }

    def _make(name: str) -> Callable[[Path], bool]:
        def _maybe_denied(self: Path) -> bool:
            if _MARKER in str(self):
                raise PermissionError(13, "Permission denied", str(self))
            return originals[name](self)

        return _maybe_denied

    for name in originals:
        monkeypatch.setattr(Path, name, _make(name))


def _write_event(file_path: str, content: str = "x = 1\n") -> dict[str, Any]:
    return {
        "tool_name": "Write",
        "session_id": "session-eacces",
        "tool_input": {"file_path": file_path, "content": content},
    }


class TestTheFixtureIsNotVacuous:
    """The trap this file has to avoid: a narrow patch that silently matches
    nothing still lets every assertion below pass against unfixed code."""

    @pytest.mark.parametrize("attr", ["exists", "is_file", "is_dir"])
    def test_a_marked_path_really_raises(self, attr: str, deny_marked_paths: None) -> None:
        with pytest.raises(PermissionError):
            getattr(Path(_UNREADABLE_PY), attr)()

    @pytest.mark.parametrize("attr", ["exists", "is_file", "is_dir"])
    def test_an_unmarked_path_is_untouched(
        self, attr: str, tmp_path: Path, deny_marked_paths: None
    ) -> None:
        """If the patch were blanket rather than marker-scoped, the handlers
        under test would be failing on their own config lookups instead of on
        the path the test is actually about."""
        assert getattr(tmp_path, attr)() in (True, False)


class TestLintOnEdit:
    def test_an_unstattable_authored_path_is_not_lintable(self, deny_marked_paths: None) -> None:
        """``False`` matches the reasoning already in place: linting a path
        that is not there "would manufacture an error the agent cannot act
        on", and a linter cannot read an unreadable file either."""
        from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler

        assert LintOnEditHandler().matches(_write_event(_UNREADABLE_PY)) is False

    def test_module_root_search_walks_past_what_it_cannot_read(
        self, deny_marked_paths: None
    ) -> None:
        """``_find_module_root`` walks up looking for ``go.mod``/``ansible.cfg``.
        Answering ``True`` for an unreadable ancestor would name it as the
        module root and run the linter from the wrong directory -- "a denial
        the author cannot act on", per the handler's own comment."""
        from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler

        assert LintOnEditHandler._find_module_root(_UNREADABLE_PY, "go.mod") is None


class TestValidateEslintOnWrite:
    def test_an_unstattable_authored_path_is_not_checkable(self, deny_marked_paths: None) -> None:
        from claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write import (
            ValidateEslintOnWriteHandler,
        )

        handler = ValidateEslintOnWriteHandler()

        assert handler.matches(_write_event(_UNREADABLE_TS, "const a = 1;\n")) is False


class TestMarkdownTableFormatter:
    def test_matches_declines_a_path_it_cannot_stat(self, deny_marked_paths: None) -> None:
        from claude_code_hooks_daemon.handlers.post_tool_use.markdown_table_formatter import (
            MarkdownTableFormatterHandler,
        )

        handler = MarkdownTableFormatterHandler()

        assert handler.matches(_write_event(_UNREADABLE_MD, "| a |\n")) is False

    def test_handle_declines_independently_of_matches(self, deny_marked_paths: None) -> None:
        """The second, independent ``exists()`` in ``handle()``. Fixing only
        the ``matches()`` one leaves this raising whenever ``handle()`` is
        reached without ``matches()`` having run first."""
        from claude_code_hooks_daemon.handlers.post_tool_use.markdown_table_formatter import (
            MarkdownTableFormatterHandler,
        )

        handler = MarkdownTableFormatterHandler()

        assert handler.handle(_write_event(_UNREADABLE_MD, "| a |\n")).decision == Decision.ALLOW


class TestStagedLintGate:
    def test_a_staged_file_it_cannot_stat_is_skipped(
        self, tmp_path: Path, deny_marked_paths: None
    ) -> None:
        """Linting a file the daemon cannot read would report a syntax error
        against content it never saw."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import (
            StagedLintGateHandler,
        )

        handler = StagedLintGateHandler()

        assert handler._lintable_files(tmp_path, "UNREADABLE/src/module.py\n") == []


class TestTddEnforcement:
    def test_a_test_path_it_cannot_stat_does_not_satisfy_the_gate(
        self, deny_marked_paths: None
    ) -> None:
        """``False`` keeps the gate live. ``True`` would accept an unstattable
        candidate as a test that exists, turning an unreadable ``tests/``
        directory into a blanket TDD exemption -- silent, where the denial is
        loud and lists every location it searched."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.tdd_enforcement import (
            TddEnforcementHandler,
        )

        handler = TddEnforcementHandler()

        assert handler.handle(_write_event(_UNREADABLE_PY)).decision == Decision.DENY


class TestGithubAutoCloseKeywords:
    def test_a_message_file_it_cannot_stat_is_skipped(self, deny_marked_paths: None) -> None:
        """Both fallbacks converge here, because ``os.access`` (which never
        raises) answers ``False`` for the same path. ``False`` is still the
        honest value: it says what happened rather than relying on the next
        check to correct a guess."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.github_auto_close_keywords import (
            GithubAutoCloseKeywordsHandler,
        )

        handler = GithubAutoCloseKeywordsHandler()
        segment = f"git commit -F {_UNREADABLE_MD}"

        assert handler._message_file_texts(segment, {"cwd": "/workspace"}) == []


class TestPlanNumberHelper:
    def test_a_plan_folder_it_cannot_stat_is_not_treated_as_existing(
        self, tmp_path: Path, deny_marked_paths: None
    ) -> None:
        """``is_dir()`` True means "already there, a ``-p`` re-create is fine"
        and returns None, which stands the guard down. ``False`` keeps the
        redirect to ``mkplan.bash`` alive for a folder the daemon cannot see.

        The workspace root is a REAL readable directory and only the plan
        folder itself carries the marker. Denying the whole tree would make the
        deployed-scaffolder check on the next line raise as well, and the
        method would return None for a second reason -- so the test would pass
        without the fix, proving nothing.
        """
        from claude_code_hooks_daemon.handlers.pre_tool_use.plan_number_helper import (
            PlanNumberHelperHandler,
        )

        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)
        (plan_dir / "mkplan.bash").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

        handler = PlanNumberHelperHandler()
        handler._workspace_root = tmp_path
        handler._track_plans_in_project = "CLAUDE/Plan"

        folder = "CLAUDE/Plan/00999-UNREADABLE-thing"

        assert handler._new_plan_folder_in_mkdir(f"mkdir {folder}") == folder


class TestWorktreeRemove:
    def test_an_unstattable_worktree_is_pruned_not_force_removed(
        self, deny_marked_paths: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This handler never denies, so the only question is which git command
        runs. ``False`` skips the optional ``worktree remove --force`` and lets
        the unconditional ``worktree prune`` do the cleanup."""
        from claude_code_hooks_daemon.handlers.worktree_remove import worktree_remove_handler

        calls: list[tuple[str, ...]] = []
        monkeypatch.setattr(
            worktree_remove_handler.WorktreeRemoveHandler,
            "_run_git",
            staticmethod(lambda cwd, *args: calls.append(args)),
        )
        handler = worktree_remove_handler.WorktreeRemoveHandler()

        handler.handle({"cwd": "/workspace", "worktree_path": "/root/UNREADABLE/wt"})

        assert calls == [("worktree", "prune")]


class TestCommentSize:
    def test_unreadable_prior_content_counts_as_growth(self, deny_marked_paths: None) -> None:
        """The one place ``False`` is right for a reason other than caution.
        ``_region_before`` returning None makes ``grows`` True downstream,
        which is the branch that can DENY -- so the naive fallback biases
        TOWARD the block here, the opposite risk profile from
        ``write_clobber_guard`` despite both being ``is_file()`` on a
        ``PreToolUse`` DENY handler."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.comment_size import CommentSizeHandler

        handler = CommentSizeHandler()

        assert handler._region_before(_write_event(_UNREADABLE_PY), _UNREADABLE_PY) is None
