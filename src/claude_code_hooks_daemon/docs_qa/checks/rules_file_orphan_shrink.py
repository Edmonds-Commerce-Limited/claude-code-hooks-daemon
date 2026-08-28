"""Check ``rules-file-orphan-shrink`` (STAGED only, never blocks; R7a, RULESET section 3).

The transition rule for a pointers-only rules file (R7a #4): "a rules file
may not be thinned by deleting its content -- promote the content to (or
verify it already exists in) the canonical home FIRST, then thin". This
check is the mechanical (weak) approximation of that rule: a staged
``.claude/rules/*.md`` file that SHRANK, with no staged file in the
canonical agent tree that GREW in the same commit, is flagged advisory --
the shrink might be a genuine promotion this check simply cannot see (the
canonical growth could be unstaged, in a prior commit, or the content
could have been genuinely obsolete), so this never blocks and is a
prompt to check, not a verdict.

STAGED only: there is no EDIT-time equivalent — "did anything else grow in
THIS COMMIT" is a cross-file, whole-staged-tree question by definition, the
same reason ``plan_shrink_without_journal`` (its plan_qa precedent) is
commit-gate-only.
"""

from typing import Final

from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)

CHECK_ID: Final[str] = "rules-file-orphan-shrink"

_RULES_DIR_PARTS: Final[tuple[str, str]] = (".claude", "rules")


def _is_rules_file(rel_path: str) -> bool:
    parts = tuple(rel_path.split("/"))
    return len(parts) == 3 and parts[:2] == _RULES_DIR_PARTS


def _finding(rel_path: str) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.ADVISE,
        message=(
            f"`{rel_path}` shrank in this commit, with no staged growth of a "
            "canonical agent-tree document -- this may be an unpromoted thin."
        ),
        remediation=(
            "Per R7a's transition rule: promote the removed content to (or "
            "verify it already exists in) a canonical doc in the agent tree "
            "FIRST, then thin the rules file. If the content was genuinely "
            "obsolete, or was already promoted in an earlier commit, this "
            "advisory is a false positive -- git keeps the history either way."
        ),
        path=rel_path,
    )


def _run_staged(context: CheckContext) -> list[Finding]:
    if context.staged_documents is None or context.gitfacts is None:
        return []

    shrunk_rules_files: list[str] = []
    for rel_path, content in context.staged_documents.items():
        if not _is_rules_file(rel_path):
            continue
        head_content = context.gitfacts.head_file_text(rel_path)
        if head_content is None:
            continue  # a brand-new file was never "shrunk"
        if len(content) < len(head_content):
            shrunk_rules_files.append(rel_path)

    if not shrunk_rules_files:
        return []

    agent_tree_prefix = context.policy.trees.agent.rstrip("/") + "/"
    grew_elsewhere = False
    for rel_path, content in context.staged_documents.items():
        if not rel_path.startswith(agent_tree_prefix) or _is_rules_file(rel_path):
            continue
        head_content = context.gitfacts.head_file_text(rel_path)
        old_length = len(head_content) if head_content is not None else 0
        if len(content) > old_length:
            grew_elsewhere = True
            break

    if grew_elsewhere:
        return []
    return [_finding(rel_path) for rel_path in sorted(shrunk_rules_files)]


CHECKS: Final[tuple[CheckSpec, ...]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.STAGED, run=_run_staged),
)
