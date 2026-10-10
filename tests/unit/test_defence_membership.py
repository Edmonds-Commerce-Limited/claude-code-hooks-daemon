"""The Defence set is closed, pinned and blocking (Plan 00484 batch 3.1a review S1).

A handler is a Defence exactly when it declares ``defect_class``. Three
properties keep that declaration honest:

* the value is a member of the closed ``DefectClass`` vocabulary, so a typo
  cannot mint a new class;
* the set of library handlers that declare one is pinned here, so growing or
  shrinking the Defence set is a deliberate edit to this test, not a side
  effect of adding a ``defect_class`` line;
* every Defence blocks: it is a PreToolUse handler (the one event whose deny
  the harness enforces), which covers both content gates (Write/Edit) and
  commit gates.

The pinned set is the coordinator's ruling under the DBF definition (content
and commit gates are Defences; post-write linters that only warn, and guards of
an action rather than of content, are not). It is not an owner ruling.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.constants.dbf import DefectClass
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.utils.naming import class_name_to_config_key

_PRE_TOOL_USE_PACKAGE = "claude_code_hooks_daemon.handlers.pre_tool_use"

#: Config keys of the library handlers that are Defences.
PINNED_LIBRARY_DEFENCES: frozenset[str] = frozenset(
    {
        "qa_suppression",
        "error_hiding_blocker",
        "security_antipattern",
        "sensitive_content",
        "comment_changelog",
        "comment_size",
        "staged_lint_gate",
        "validate_instruction_content",
        "plan_time_estimates",
        "plan_qa_edit",
        "plan_qa_commit_gate",
        "docs_qa_edit",
        "docs_qa_commit_gate",
        "remote_docs_provenance",
        "remote_docs_commit_gate",
        "conflict_marker_commit_gate",
        "github_auto_close_keywords",
    }
)

#: Handlers that are deliberately NOT Defences although a reader might expect one.
DELIBERATE_NON_DEFENCES: frozenset[str] = frozenset(
    {"lint_on_edit", "validate_eslint_on_write", "tdd_enforcement"}
)


def _library_handler_classes() -> dict[str, type[Handler]]:
    registry = HandlerRegistry()
    registry.discover("claude_code_hooks_daemon.handlers")
    classes = (registry.get_handler_class(name) for name in registry.list_handlers())
    return {class_name_to_config_key(cls.__name__): cls for cls in classes if cls is not None}


@pytest.fixture(scope="module")
def library_handlers() -> dict[str, type[Handler]]:
    return _library_handler_classes()


class TestDefenceMembership:
    def test_declared_defect_classes_are_members_of_the_closed_vocabulary(
        self, library_handlers: dict[str, type[Handler]]
    ) -> None:
        declared = {
            key: cls.defect_class
            for key, cls in library_handlers.items()
            if cls.defect_class is not None
        }
        assert declared
        for key, defect_class in declared.items():
            assert isinstance(defect_class, DefectClass), key
            assert defect_class in set(DefectClass), key

    def test_the_library_defence_set_is_the_pinned_set(
        self, library_handlers: dict[str, type[Handler]]
    ) -> None:
        declared = {key for key, cls in library_handlers.items() if cls.defect_class is not None}
        assert declared == PINNED_LIBRARY_DEFENCES

    def test_deliberate_non_defences_declare_no_defect_class(
        self, library_handlers: dict[str, type[Handler]]
    ) -> None:
        for key in DELIBERATE_NON_DEFENCES:
            assert library_handlers[key].defect_class is None, key

    def test_every_defence_is_a_blocking_pre_tool_use_handler(
        self, library_handlers: dict[str, type[Handler]]
    ) -> None:
        for key in PINNED_LIBRARY_DEFENCES:
            cls = library_handlers[key]
            assert cls.__module__.startswith(f"{_PRE_TOOL_USE_PACKAGE}."), key
            assert issubclass(cls, PreToolUseHandlerBase), key

    def test_every_vocabulary_member_is_used_by_a_library_defence_or_is_project_only(
        self, library_handlers: dict[str, type[Handler]]
    ) -> None:
        used = {cls.defect_class for cls in library_handlers.values() if cls.defect_class}
        unused = set(DefectClass) - used
        # The only member no library handler declares is the one this project's
        # own plan_done_requires_holding_area project handler declares.
        assert unused == {DefectClass.UNRECORDED_RELEASE_CONSEQUENCE}

    def test_a_free_string_is_not_a_defect_class(self) -> None:
        with pytest.raises(ValueError):
            DefectClass("made-up-class")
