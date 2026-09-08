"""Run the registered plan QA checks for one stage.

Deliberately tiny: the registry is declarative data
(:mod:`plan_qa.checks`), the checks are pure functions, and this module is
just the filter-and-accumulate loop between them -- plus the ONE place the
project-wide ``daemon.exclude_paths`` is applied to findings (Plan 00362
Task 2.9), so no individual check has to know the exclusion exists.
"""

from claude_code_hooks_daemon.plan_qa.checks import all_checks
from claude_code_hooks_daemon.plan_qa.types import CheckContext, CheckSpec, Finding, Stage
from claude_code_hooks_daemon.utils.path_exclusion import is_path_excluded


def _excluded(path: str, context: CheckContext) -> bool:
    """Whether ``path`` -- in any of the forms a finding uses -- is excluded.

    Findings are not uniform about ``path``: document checks carry a
    project-relative path, tree checks carry the bare plan FOLDER name, and
    the EDIT surface holds an absolute path. Each form is tried against the
    project root, and the folder-name form is additionally re-rooted under
    the plan directory so a pattern written as ``CLAUDE/Plan/00042-x/**``
    covers the folder-keyed findings too.
    """
    patterns = context.exclude_paths
    root = context.project_root
    if is_path_excluded(path, patterns, project_root=root):
        return True
    rerooted = f"{context.plan_dir_rel}/{path}".replace("\\", "/")
    return is_path_excluded(rerooted, patterns, project_root="") or is_path_excluded(
        f"{rerooted}/", patterns, project_root=""
    )


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
    if (
        context.exclude_paths
        and context.file_path is not None
        and _excluded(str(context.file_path), context)
    ):
        return []
    specs = all_checks() if registry is None else registry
    findings: list[Finding] = []
    for spec in specs:
        if spec.stage == stage:
            findings.extend(spec.run(context))
    if not context.exclude_paths:
        return findings
    return [
        finding
        for finding in findings
        if finding.path is None or not _excluded(finding.path, context)
    ]
