"""The low-noise spellings class 6 found reachable — Plan 00412.

`outcome-reachable-by-an-unenumerated-spelling`: the handler already denies
`git checkout -- <file>`, so discarding the working tree is judged worth
guarding — and `git checkout -f` reached the same outcome untouched. The corpus
at `scripts/qa/dangerous-invocation-corpus.yaml` recorded all of these as
`UNCOVERED-open` against the real chain before this change.

Only the rows the review calls LOW-NOISE are here. `rm -rf`, ref deletion and
the rest ship as separate opt-in handlers, because every new deny is a new
refusal surface in every installing project and a rule that gets switched off
protects nothing.

**Every rule below is paired with a control that a sloppier pattern would
fail.** That is the whole content of these tests: `git gc` is routine and
`git gc --prune=now` is not; `git reflog expire --expire=90.days.ago` is
housekeeping and `--expire=now` is the recovery net being cut. A rule that
cannot tell the pair apart would be denied-by-default noise, which is exactly
the objection that kept these unwritten.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


def _input(command: str) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "test",
    }


def _denied(handler: DestructiveGitHandler, command: str) -> bool:
    hook_input = _input(command)
    if not handler.matches(hook_input):
        return False
    return handler.handle(hook_input).decision is not Decision.ALLOW


def _reason_for(handler: DestructiveGitHandler, command: str) -> str:
    """The block message. The rule id travels IN it — GatingResult has no rule field."""
    return handler.handle(_input(command)).reason or ""


class TestWorkingTreeDestruction:
    @pytest.mark.parametrize(
        "command",
        [
            "git checkout -f",
            "git checkout --force",
            "git checkout -f main",
            "git -C /repo checkout -f",
            "env git checkout --force",
        ],
    )
    def test_forced_checkout_is_denied(self, handler, command: str) -> None:
        assert _denied(handler, command)

    @pytest.mark.parametrize(
        "command",
        [
            "git checkout main",
            "git checkout -b feature-work",
            "git checkout feature-fix",
            "git checkout -t origin/main",
        ],
    )
    def test_ordinary_checkout_is_untouched(self, handler, command: str) -> None:
        """The controls.

        `feature-fix` and `feature-work` both contain an `f`, and `-b`/`-t`
        are ordinary branch operations. A pattern that keyed on the letter
        rather than on a flag token would deny all four, and switching
        branches is the single most routine git operation there is.
        """
        assert not _denied(handler, command)

    @pytest.mark.parametrize(
        "command",
        [
            "git switch -f main",
            "git switch --force",
            "git switch --discard-changes",
            "git -C /repo switch -f main",
        ],
    )
    def test_forced_switch_is_denied(self, handler, command: str) -> None:
        assert _denied(handler, command)

    @pytest.mark.parametrize(
        "command",
        [
            "git switch main",
            "git switch -c feature-work",
            "git switch --create feature-fix",
            "git switch --force-create foo",
        ],
    )
    def test_ordinary_switch_is_untouched(self, handler, command: str) -> None:
        """`--force-create` is the long spelling of `-C`, not of `-f`.

        It resets a branch ref and git itself refuses it when local changes
        would be lost -- it cannot cause the working-tree loss this rule
        exists to catch. The checkout sibling already guards `--force`
        against exactly this shape of over-match (`--force-with-lease` stays
        out via `--force(?!-)`); the switch pattern must hold the same
        property.
        """
        assert not _denied(handler, command)


class TestRecoveryNetDestruction:
    @pytest.mark.parametrize(
        "command",
        [
            "git reflog expire --expire=now --all",
            "git reflog expire --expire-unreachable=now --all",
            "git -C /repo reflog expire --expire=now --all",
        ],
    )
    def test_expiring_the_reflog_now_is_denied(self, handler, command: str) -> None:
        assert _denied(handler, command)

    @pytest.mark.parametrize(
        "command",
        [
            "git reflog",
            "git reflog show HEAD",
            "git reflog expire --expire=90.days.ago --all",
        ],
    )
    def test_reading_or_ordinary_expiry_is_untouched(self, handler, command: str) -> None:
        """The control that makes this rule low-noise rather than a blanket ban.

        Expiring entries older than ninety days is routine housekeeping. Only
        `=now` cuts the net that `destructive_git`'s own acceptance test leans
        on when it justifies a decision with "recoverable via reflog".
        """
        assert not _denied(handler, command)

    @pytest.mark.parametrize(
        "command",
        [
            "git gc --prune=now",
            "git gc --aggressive --prune=now",
            "git -C /repo gc --prune=now",
        ],
    )
    def test_pruning_now_is_denied(self, handler, command: str) -> None:
        assert _denied(handler, command)

    @pytest.mark.parametrize(
        "command",
        [
            "git gc",
            "git gc --auto",
            "git gc --prune=2.weeks.ago",
        ],
    )
    def test_ordinary_gc_is_untouched(self, handler, command: str) -> None:
        assert not _denied(handler, command)


class TestHistoryRewrite:
    @pytest.mark.parametrize(
        "command",
        [
            "git filter-branch --force --tree-filter 'rm -f secrets' HEAD",
            "git filter-repo --path secrets --invert-paths",
            "git -C /repo filter-branch --all",
        ],
    )
    def test_history_filtering_is_denied(self, handler, command: str) -> None:
        assert _denied(handler, command)

    @pytest.mark.parametrize(
        "command",
        [
            "git branch --list",
            "git log --all",
            "git rev-list --all",
        ],
    )
    def test_ordinary_history_reads_are_untouched(self, handler, command: str) -> None:
        assert not _denied(handler, command)


class TestSeparatorSafety:
    """A later, unrelated statement must not be denied by an earlier segment.

    The handler's existing patterns take this seriously enough to carry a
    paragraph of comment each -- `git push origin main; git worktree remove
    <path> --force` was the original defect. A new pattern written with a bare
    `.*` reintroduces it silently, and the failure is a denial of a command the
    rule does not name.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "git status && grep -f patterns.txt notes.txt",
            "git log --oneline; echo '--prune=now'",
            "git gc --auto && git status\ngrep --force notes.txt",
        ],
    )
    def test_an_unrelated_later_statement_is_not_denied(self, handler, command: str) -> None:
        assert not _denied(handler, command)


class TestRuleIdentity:
    """Each new spelling reports its OWN rule id.

    Per-rule granularity is this handler's existing contract (Plan 00116,
    Decision B). Folding a new spelling into a neighbouring rule id would make
    the block message name a command the agent did not run.
    """

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("git checkout -f", RuleID.GIT_CHECKOUT_FORCE),
            ("git switch --discard-changes", RuleID.GIT_SWITCH_FORCE),
            ("git reflog expire --expire=now --all", RuleID.GIT_REFLOG_EXPIRE),
            ("git gc --prune=now", RuleID.GIT_GC_PRUNE_NOW),
            ("git filter-repo --path x --invert-paths", RuleID.GIT_FILTER_HISTORY),
        ],
    )
    def test_the_reported_rule_id_names_the_command_run(
        self, handler, command: str, expected: str
    ) -> None:
        assert expected in _reason_for(handler, command)

    def test_every_new_rule_id_has_a_rule_definition(self, handler) -> None:
        """A rule id with no Rule renders as a bare identifier with no guidance."""
        defined = {rule.rule_id for rule in handler.get_rules()}

        for rule_id in (
            RuleID.GIT_CHECKOUT_FORCE,
            RuleID.GIT_SWITCH_FORCE,
            RuleID.GIT_REFLOG_EXPIRE,
            RuleID.GIT_GC_PRUNE_NOW,
            RuleID.GIT_FILTER_HISTORY,
        ):
            assert rule_id in defined
