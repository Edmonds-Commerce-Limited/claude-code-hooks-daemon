"""Run the registered plan QA checks for one stage.

Deliberately tiny: the registry is declarative data
(:mod:`plan_qa.checks`), the checks are pure functions, and this module is
just the filter-and-accumulate loop between them.
"""

from claude_code_hooks_daemon.plan_qa.checks import all_checks
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Stage


def run_stage(
    stage: Stage,
    context: CheckContext,
    registry: tuple[CheckSpec, ...] | None = None,
) -> list[Finding]:
    """Run every check registered for ``stage`` and accumulate findings.

    Args:
        stage: Which enforcement surface is asking.
        context: The facts the checks may consult.
        registry: Override for tests; defaults to the full catalogue.
    """
    specs = all_checks() if registry is None else registry
    findings: list[Finding] = []
    for spec in specs:
        if spec.stage == stage:
            findings.extend(spec.run(context))
    return findings
