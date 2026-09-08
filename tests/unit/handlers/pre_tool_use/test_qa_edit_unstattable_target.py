"""``plan_qa_edit`` / ``docs_qa_edit``: the sites where no boolean is safe.

Both compute ``exists_before = file_path.is_file()`` and thread it downstream as
``file_exists_before``. That single value is read three different ways::

    archive_immutability.py:30   fires only when `is not True` is False
    task_grammar.py:42           fires only when `is False`
    template_metadata.py:29      fires when `is not False`

So ``False`` disables ``archive_immutability`` and ``True`` disables
``task_grammar``'s new-document scoping. There is no boolean that leaves all
three doing what they were written to do -- which is why ``CheckContext``
already types the field ``bool | None``.

**The answer is ``None``, and the report that classified this site recommended
otherwise.** It argued for biasing to ``True`` so ``archive_immutability`` keeps
firing. Two things say no:

1. ``archive_immutability`` tests ``is not True``, not ``is False``. Its author
   already decided that uncertainty should not raise this advisory. Forcing
   ``True`` from the producer overrides a choice the consumer made deliberately.
2. ``True`` sends execution straight into ``read_text()`` on a path that cannot
   be read, re-raising the same ``PermissionError`` one line later -- so it
   would need a second untruth (content_before ``None`` while claiming the file
   exists) to stay upright. ``None`` is what the daemon actually knows.

The report's mechanism was right and its recommendation was not; the field being
tri-state in the first place is the evidence.

``None`` also changes a branch that was safe while the value was boolean:
``if not exists_before`` is TRUE for ``None``, which would record a plan-number
allocation for a file that may well already exist. Tested below.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import PlanWorkflowQaConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy

_MARKER = "UNREADABLE"
_PLAN_DIR_REL = "CLAUDE/Plan"


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def deny_marked_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """EACCES for marked paths only, so the handlers' own project-root and
    config lookups keep working and the failure is the one under test."""
    original = Path.is_file

    def _maybe_denied(self: Path) -> bool:
        if _MARKER in str(self):
            raise PermissionError(13, "Permission denied", str(self))
        return original(self)

    monkeypatch.setattr(Path, "is_file", _maybe_denied)


def _plan_handler() -> Any:
    """Wired like the existing plan_qa_edit suite: the policy is daemon config,
    not the caller-supplied path this file is about."""
    from claude_code_hooks_daemon.handlers.pre_tool_use.plan_qa_edit import PlanQaEditHandler

    handler = PlanQaEditHandler()
    handler._track_plans_in_project = _PLAN_DIR_REL
    handler._plan_qa = PlanWorkflowQaConfig()
    return handler


def _docs_handler() -> Any:
    from claude_code_hooks_daemon.handlers.pre_tool_use.docs_qa_edit import DocsQaEditHandler

    handler = DocsQaEditHandler()
    handler._documentation = DocumentationPolicy(enabled=True)
    return handler


def _write(file_path: Path, content: str) -> dict[str, Any]:
    return {
        "tool_name": "Write",
        "session_id": "session-eacces",
        "tool_input": {"file_path": str(file_path), "content": content},
    }


def _plan_body() -> str:
    return (
        "# Plan 00999: unreadable\n\n"
        "**Status**: In Progress\n"
        "**Created**: 2026-09-08\n\n"
        "## Overview\n\nBody.\n\n## Tasks\n\n- [ ] ⬜ **Task 1.1**: Do a thing.\n"
    )


class TestTheFixtureIsNotVacuous:
    def test_a_marked_path_really_raises(self, deny_marked_paths: None) -> None:
        with pytest.raises(PermissionError):
            Path(f"/root/{_MARKER}/CLAUDE/Plan/00999-x/PLAN.md").is_file()

    def test_an_unmarked_path_is_untouched(self, tmp_path: Path, deny_marked_paths: None) -> None:
        assert tmp_path.is_file() is False


class TestPlanQaEdit:
    def test_handle_does_not_raise(self, tmp_path: Path, deny_marked_paths: None) -> None:
        target = tmp_path / _MARKER / "CLAUDE" / "Plan" / "00999-x" / "PLAN.md"
        handler = _plan_handler()

        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
        ) as root:
            root.return_value = tmp_path
            result = handler.handle(_write(target, _plan_body()))

        assert result.decision in (Decision.ALLOW, Decision.DENY)

    def test_an_unknown_existence_is_threaded_as_none(
        self, tmp_path: Path, deny_marked_paths: None
    ) -> None:
        """Not ``False``. ``archive_immutability`` tests ``is not True`` and
        ``template_metadata`` tests ``is not False``, so the two disagree about
        what ``False`` means -- only ``None`` says what actually happened."""
        from claude_code_hooks_daemon.plan_qa.context import edit_context

        target = tmp_path / _MARKER / "CLAUDE" / "Plan" / "00999-x" / "PLAN.md"
        handler = _plan_handler()
        seen: list[Any] = []

        def _capture(**kwargs: Any) -> Any:
            seen.append(kwargs.get("file_exists_before"))
            return edit_context(**kwargs)

        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
        ) as root:
            root.return_value = tmp_path
            with patch(
                "claude_code_hooks_daemon.handlers.pre_tool_use.plan_qa_edit.edit_context",
                _capture,
            ):
                handler.handle(_write(target, _plan_body()))

        assert seen == [None], f"expected an explicit 'unknown', got {seen!r}"

    def test_no_plan_number_allocation_is_recorded(
        self, tmp_path: Path, deny_marked_paths: None
    ) -> None:
        """The branch ``None`` newly reaches. ``if not exists_before`` is TRUE
        for ``None``, so a path the daemon merely could not read would be
        recorded as a fresh plan-number allocation."""
        target = tmp_path / _MARKER / "CLAUDE" / "Plan" / "00999-x" / "PLAN.md"
        handler = _plan_handler()

        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
        ) as root:
            root.return_value = tmp_path
            with patch.object(handler, "_record_allocation") as record:
                handler.handle(_write(target, _plan_body()))

        record.assert_not_called()

    def test_a_real_new_file_still_records_an_allocation(self, tmp_path: Path) -> None:
        """Pins the behaviour the ``is False`` narrowing must not break. A file
        that genuinely does not exist is still a creation."""
        target = tmp_path / "CLAUDE" / "Plan" / "00999-x" / "PLAN.md"
        handler = _plan_handler()

        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
        ) as root:
            root.return_value = tmp_path
            with patch.object(handler, "_record_allocation") as record:
                handler.handle(_write(target, _plan_body()))

        record.assert_called_once()


class TestDocsQaEdit:
    def test_handle_does_not_raise(self, tmp_path: Path, deny_marked_paths: None) -> None:
        target = tmp_path / _MARKER / "docs" / "guide.md"
        handler = _docs_handler()

        with patch.multiple(
            "claude_code_hooks_daemon.handlers.pre_tool_use.docs_qa_edit.ProjectContext",
            project_root=staticmethod(lambda: tmp_path),
            daemon_untracked_dir=staticmethod(lambda: tmp_path / "untracked"),
        ):
            result = handler.handle(_write(target, "# Guide\n\nBody.\n"))

        assert result.decision in (Decision.ALLOW, Decision.DENY)


class TestAnEditIsSkippedRatherThanGuessedAt:
    def test_an_edit_to_an_unreadable_plan_is_allowed_unlinted(
        self, tmp_path: Path, deny_marked_paths: None
    ) -> None:
        """``_would_be_content`` needs the file's current text to apply
        ``old_string``. It cannot be read, so there is nothing to lint and the
        only honest answer is to stand aside -- NOT to read it anyway, which is
        what a ``True`` fallback would have made it try."""
        target = tmp_path / _MARKER / "CLAUDE" / "Plan" / "00999-x" / "PLAN.md"
        handler = _plan_handler()
        hook_input: dict[str, Any] = {
            "tool_name": "Edit",
            "session_id": "session-eacces",
            "tool_input": {
                "file_path": str(target),
                "old_string": "Status",
                "new_string": "State",
            },
        }

        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
        ) as root:
            root.return_value = tmp_path
            result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
