"""Runtime guidance names the daemon wrapper for the install mode in use (issue #147, part 2).

A client install keeps the wrapper at ``.claude/hooks-daemon/bin/hooks-daemon`` and has
no root ``bin/``; each renderer below must not emit the bare self-install spelling.
"""

import re
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import project_context as pc
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.core.session_mode_registry import goal_loop_self_clear_instruction
from claude_code_hooks_daemon.core.worktree_seed import SEED_MODE_COPY, SeedEntry
from claude_code_hooks_daemon.daemon.issue_validity_cli import _claim_command
from claude_code_hooks_daemon.daemon.source_fingerprint import _restart_advice
from claude_code_hooks_daemon.docs_qa.checks.unlisted_fake_value import _remedy_vendored
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import GoalInjectionHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.daemon_location_guard import (
    DaemonLocationGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.github_issue_assignment_guard import (
    GithubIssueAssignmentGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_commit_gate import (
    _rule_staged_provenance,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_provenance import (
    _rule_remote_docs_provenance,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.remote_docs_routing import (
    _rule_vendored_copy,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.usage_pause_tool_gate import (
    _rule as _usage_pause_tool_rule,
)
from claude_code_hooks_daemon.handlers.status_line.daemon_stats import DaemonStatsHandler
from claude_code_hooks_daemon.handlers.stop.idle_workable_issue_stop_gate import (
    IdleWorkableIssueStopGateHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.idle_housekeeping_advisor import (
    IdleHousekeepingAdvisoryHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.limit_rebrief import _rebrief
from claude_code_hooks_daemon.handlers.user_prompt_submit.usage_pause_gate import (
    UsagePauseGateHandler,
)
from claude_code_hooks_daemon.handlers.worktree_create.worktree_create_handler import (
    WorktreeCreateHandler,
)
from claude_code_hooks_daemon.remote_docs.index import render_index
from claude_code_hooks_daemon.utils.github_issue_validity import (
    CheckResult,
    CheckStatus,
    ValidityReport,
)
from claude_code_hooks_daemon.utils.usage_pause_gate import render_lift_not_recorded_note
from claude_code_hooks_daemon.utils.work_queue import WorkRecord, render_rebrief


def _guard_denial() -> str:
    """The unassigned-issue denial text, with its claim command."""
    report = ValidityReport(
        number=7,
        results=(CheckResult(check="assignee", status=CheckStatus.FIXABLE, message="nobody"),),
    )
    rule, detail = GithubIssueAssignmentGuardHandler._denial(report)
    return f"{rule.fix}\n{rule.verbose}\n{detail}"


def _rebrief_text() -> str:
    """The limit re-brief with an empty body, so every place is named."""
    return _rebrief([], [], None, [])


def _seeding_text() -> str:
    """The worktree seeding guidance, with one configured seed entry."""
    entries = [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)]
    with patch.object(WorktreeCreateHandler, "_seed_entries", return_value=entries):
        return WorktreeCreateHandler().get_claude_md() or ""


def _work_queue_text() -> str:
    """The work-queue re-brief advisory for one running record."""
    record = WorkRecord(
        name="a",
        worktree="w",
        branch="b",
        brief="x",
        brief_file=None,
        last_sha="abc",
        status="running",
        created_at=0.0,
        updated_at=0.0,
    )
    return "\n".join(render_rebrief([record], now=1.0, project_root=Path("/proj")))


def _rules_text(rules: list[Rule]) -> str:
    """Every rendered field of every rule."""
    return "\n".join(f"{r.fix}\n{r.verbose or ''}" for r in rules)


_CLIENT_WRAPPER = ".claude/hooks-daemon/bin/hooks-daemon"
_BARE = re.compile(r"(?<!\.claude/hooks-daemon/)bin/hooks-daemon")


def _set_mode(monkeypatch: pytest.MonkeyPatch, *, self_install: bool) -> None:
    """Pin ProjectContext to a known root and install mode."""
    monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
    monkeypatch.setattr(
        pc.ProjectContext, "project_root", classmethod(lambda cls: Path("/proj")), raising=False
    )
    monkeypatch.setattr(
        pc.ProjectContext,
        "self_install_mode",
        classmethod(lambda cls: self_install),
        raising=False,
    )


_RENDERERS: list[Callable[[], str]] = [
    lambda: _claim_command(7),
    goal_loop_self_clear_instruction,
    _restart_advice,
    _remedy_vendored,
    lambda: _rule_vendored_copy().verbose or "",
    lambda: _rule_remote_docs_provenance().verbose or "",
    lambda: _rule_staged_provenance().verbose or "",
    lambda: _usage_pause_tool_rule().verbose or "",
    _guard_denial,
    lambda: GithubIssueAssignmentGuardHandler().get_claude_md() or "",
    lambda: _rules_text(DaemonLocationGuardHandler().get_rules()),
    lambda: _rules_text(UsagePauseGateHandler().get_rules()),
    lambda: UsagePauseGateHandler().get_claude_md() or "",
    lambda: IdleHousekeepingAdvisoryHandler()._default_guidance(),
    lambda: IdleHousekeepingAdvisoryHandler().get_claude_md() or "",
    _rebrief_text,
    lambda: IdleWorkableIssueStopGateHandler()._render((7,)),
    lambda: DaemonStatsHandler().explain_segment().current_value,
    lambda: GoalInjectionHandler().get_claude_md() or "",
    _seeding_text,
    lambda: render_lift_not_recorded_note(expires_at=1.0),
    _work_queue_text,
    lambda: render_index(Path("/nonexistent-corpus")),
]


@pytest.mark.parametrize("render", _RENDERERS)
def test_client_install_names_client_wrapper(
    monkeypatch: pytest.MonkeyPatch, render: Callable[[], str]
) -> None:
    """A client install never sees the bare self-install wrapper path."""
    _set_mode(monkeypatch, self_install=False)
    text = render()
    assert _CLIENT_WRAPPER in text
    assert _BARE.search(text) is None


@pytest.mark.parametrize("render", _RENDERERS)
def test_self_install_names_root_wrapper(
    monkeypatch: pytest.MonkeyPatch, render: Callable[[], str]
) -> None:
    """A self-install keeps the root ``bin/hooks-daemon`` spelling."""
    _set_mode(monkeypatch, self_install=True)
    text = render()
    assert "bin/hooks-daemon" in text
    assert _CLIENT_WRAPPER not in text
