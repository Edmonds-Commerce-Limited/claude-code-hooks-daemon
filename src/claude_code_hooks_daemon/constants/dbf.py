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
    def defence_line(defect_class: str) -> str:
        """The line printed for a rule whose handler is a Defence.

        Args:
            defect_class: The handler's declared ``DefectClass`` value.

        Returns:
            One line naming the defect class the handler defends.
        """
        return f"Defence for the defect class: {defect_class}"


class DefectClass:
    """The defect classes the content and commit gates defend (public contract, like ``RuleID``).

    A handler declares one as ``defect_class``; ``hooks-daemon defences --json``
    reports it as ``defect_class``. Renames are a breaking change.
    """

    QA_SUPPRESSION: ClassVar[str] = "qa-suppression"
    ERROR_HIDING: ClassVar[str] = "error-hiding"
    SECURITY_ANTIPATTERN: ClassVar[str] = "security-antipattern"
    SENSITIVE_CONTENT: ClassVar[str] = "sensitive-content"
    CHANGELOG_IN_COMMENT: ClassVar[str] = "changelog-in-comment"
    OVERSIZED_COMMENT: ClassVar[str] = "oversized-comment"
    SOURCE_WITHOUT_TEST: ClassVar[str] = "source-without-test"
    LINT_FAILURE: ClassVar[str] = "lint-failure"
    INSTRUCTION_FILE_LOG: ClassVar[str] = "instruction-file-log"
    PLAN_TIME_ESTIMATE: ClassVar[str] = "plan-time-estimate"
    PLAN_DRIFT: ClassVar[str] = "plan-drift"
    DOC_DRIFT: ClassVar[str] = "doc-drift"
    UNATTRIBUTED_VENDORED_DOC: ClassVar[str] = "unattributed-vendored-doc"
    CONFLICT_MARKER: ClassVar[str] = "conflict-marker"
