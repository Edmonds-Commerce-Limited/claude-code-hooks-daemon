"""Defence Before Fix (DBF) constants.

The method this project's handlers follow is published at
``DefenceBeforeFix.URL``. The URL and the lines printed by ``explain-rule`` and
``explain-handler`` live here so each appears once.

Which handlers are Defences is the owner's ruling C1 (Plan 00484): the content
gates and commit gates are the Defence set, and the action guards are outside
it. A handler is in the set exactly when it declares a ``defect_class``
(``Handler.defect_class``), using one of the ``DefectClass`` values below.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar


class DefenceBeforeFix:
    """Public home of the Defence Before Fix method and the lines the CLI prints about it."""

    URL: ClassVar[str] = "https://defence-before-fix.github.io"
    #: True of every rule, Defence or guardrail: this daemon follows the method.
    EXPLAIN_LINE: ClassVar[str] = f"Method: Defence Before Fix. {URL}"
    #: Printed for a rule whose handler is an action guard (no defect class).
    GUARDRAIL_LINE: ClassVar[str] = (
        "Guardrail: an action guard, not a Defence in the DBF sense (it stops a careless "
        "action; it does not find a class of defect in content)."
    )

    @staticmethod
    def defence_line(defect_class: DefectClass) -> str:
        """The line printed for a rule whose handler is a Defence.

        Args:
            defect_class: The handler's declared ``DefectClass`` value.

        Returns:
            One line naming the defect class the handler defends.
        """
        return f"Defence for the defect class: {defect_class}"


class DefectClass(StrEnum):
    """The closed vocabulary of defect classes the content and commit gates defend.

    A handler declares one as ``defect_class``; ``hooks-daemon defences --json``
    reports its value as ``defect_class``. The set is closed: a handler (project
    handlers included) declares a member of this enum, never a free string, so a
    typo cannot mint a new class. Renames are a breaking change.
    """

    QA_SUPPRESSION = "qa-suppression"
    ERROR_HIDING = "error-hiding"
    SECURITY_ANTIPATTERN = "security-antipattern"
    SENSITIVE_CONTENT = "sensitive-content"
    CHANGELOG_IN_COMMENT = "changelog-in-comment"
    OVERSIZED_COMMENT = "oversized-comment"
    LINT_FAILURE = "lint-failure"
    INSTRUCTION_FILE_LOG = "instruction-file-log"
    PLAN_TIME_ESTIMATE = "plan-time-estimate"
    PLAN_DRIFT = "plan-drift"
    UNRECORDED_RELEASE_CONSEQUENCE = "unrecorded-release-consequence"
    DOC_DRIFT = "doc-drift"
    UNATTRIBUTED_VENDORED_DOC = "unattributed-vendored-doc"
    CONFLICT_MARKER = "conflict-marker"
    ISSUE_CLOSING_KEYWORD = "issue-closing-keyword"
    #: Declared by no handler: the write-time counterpart is advisory, so only the
    #: blocking batch check (``check_british_english.py``) defends this class.
    AMERICAN_SPELLING = "american-spelling"
