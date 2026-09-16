"""The guard-config commit gate (Plan 00412 class 2(a)).

Class 2, `guard-self-disablement-unwatched`, is defined as an action that
changes what a future session's guards will do, where no gate judges the action
and no record is made that it happened. 2(b) built the session-start drift
report; this is the other half, at the moment the weakening enters history.

**Why it REPORTS rather than denies, which is a measured decision and not a
preference.** Two gate designs were tested against this repository's own
history, and both failed the same way:

* requiring a literal `RULE CHANGE:` marker -- 7 of 20 weakening commits carry
  one, so 13 commits that were already explaining themselves would be blocked;
* requiring the message to NAME the handler it weakens -- 1 of 5. One of the
  four it would block spends a paragraph on precisely that config decision and
  fails only because it writes "sensitive-content guard" rather than the
  underscore config key; the other three are bulk restructures, two of which
  made the config STRICTER overall.

Both test the SPELLING of the commit message, not whether anyone reasoned. A
gate with an 80% historical false-alarm rate is one that gets switched off,
which is the finding eating itself. The RECORD is what class 2 asks for, and a
warn-mode report is the whole deliverable -- the same warn-first rollout
`staged_lint_gate`, `verification_result_gate` and `plan_qa_commit_gate` ship.

**Why `-a` handling is load-bearing rather than polish.** `git commit -a`
records the WORKING TREE, so a gate reading only the index sees nothing when
the config is edited and committed with `-a` -- which is exactly the route the
class is about.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.guard_config_commit_gate import (
    CONFIG_RELATIVE_PATH,
    GuardConfigCommitGateHandler,
    RecordedSource,
    recorded_config_source,
)

_COMMITTED = """
handlers:
  pre_tool_use:
    sed_blocker:
      enabled: true
    sensitive_content:
      enabled: true
"""

_WEAKENED = _COMMITTED.replace(
    "    sed_blocker:\n      enabled: true",
    "    sed_blocker:\n      enabled: false",
)


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestWhichVersionTheCommitRecords:
    """A pure decision, because getting it wrong makes the gate look clean."""

    def test_a_bare_commit_records_the_index(self) -> None:
        assert recorded_config_source("git commit -m msg", CONFIG_RELATIVE_PATH) is (
            RecordedSource.INDEX
        )

    def test_commit_all_records_the_working_tree(self) -> None:
        assert recorded_config_source("git commit -am msg", CONFIG_RELATIVE_PATH) is (
            RecordedSource.WORKING_TREE
        )

    def test_a_pathspec_naming_the_config_records_the_working_tree(self) -> None:
        """`git commit <path>` commits that path's WORKING TREE content.

        It bypasses the index for those paths entirely, so reading the staged
        blob would examine something the commit does not contain.
        """
        command = f"git commit -m msg {CONFIG_RELATIVE_PATH}"

        assert recorded_config_source(command, CONFIG_RELATIVE_PATH) is (
            RecordedSource.WORKING_TREE
        )

    def test_a_pathspec_not_naming_the_config_records_no_config_at_all(self) -> None:
        """The commit cannot carry a config change, so there is nothing to say."""
        assert recorded_config_source("git commit -m msg docs/a.md", CONFIG_RELATIVE_PATH) is None

    def test_a_directory_pathspec_containing_the_config_counts(self) -> None:
        assert recorded_config_source("git commit -m msg .claude", CONFIG_RELATIVE_PATH) is (
            RecordedSource.WORKING_TREE
        )

    def test_a_dot_pathspec_records_the_whole_working_tree(self) -> None:
        """`git commit .` commits everything below cwd, config included.

        `_pathspec_covers` did a literal prefix comparison with no
        normalisation, so `.` never equalled and never prefixed the config
        path -- the gate read this as naming nothing and stayed silent about
        a commit that in fact carries the config.
        """
        assert recorded_config_source("git commit . -m x", CONFIG_RELATIVE_PATH) is (
            RecordedSource.WORKING_TREE
        )

    def test_a_slash_dot_pathspec_records_the_whole_working_tree(self) -> None:
        assert recorded_config_source("git commit -m x ./", CONFIG_RELATIVE_PATH) is (
            RecordedSource.WORKING_TREE
        )

    def test_a_dot_slash_prefixed_config_path_still_counts(self) -> None:
        command = f"git commit -m x ./{CONFIG_RELATIVE_PATH}"

        assert recorded_config_source(command, CONFIG_RELATIVE_PATH) is (
            RecordedSource.WORKING_TREE
        )

    def test_a_non_commit_command_is_not_judged(self) -> None:
        assert recorded_config_source("git status", CONFIG_RELATIVE_PATH) is None

    def test_a_respelled_git_invocation_is_still_judged(self) -> None:
        """`git -C <path> commit` must not walk past this gate.

        Assuming a handler "is not a command handler" is what let `git -C`
        bypass four handlers unnoticed, so the subcommand is located with the
        evasion-hardened locator rather than by reading token 1. The gate never
        denies, so there is no block to evade -- but a respelling that made it
        SILENT would hide the weakening just as effectively.
        """
        command = "git -C /srv/project commit -am msg"

        assert recorded_config_source(command, CONFIG_RELATIVE_PATH) is (
            RecordedSource.WORKING_TREE
        )

    def test_a_no_pager_respelling_is_still_judged(self) -> None:
        assert recorded_config_source("git --no-pager commit -m msg", CONFIG_RELATIVE_PATH) is (
            RecordedSource.INDEX
        )

    def test_an_absolute_git_path_is_still_judged(self) -> None:
        assert recorded_config_source("/usr/bin/git commit -m msg", CONFIG_RELATIVE_PATH) is (
            RecordedSource.INDEX
        )

    def test_the_a_in_a_quoted_message_does_not_select_the_working_tree(self) -> None:
        command = "git commit -m 'fix the -a flag handling'"

        assert recorded_config_source(command, CONFIG_RELATIVE_PATH) is RecordedSource.INDEX


class TestTheGateReportsAWeakening:
    def _handler(self, head: str | None, recorded: str | None) -> GuardConfigCommitGateHandler:
        handler = GuardConfigCommitGateHandler()
        handler.head_reader = lambda: head
        handler.recorded_reader = lambda _source: recorded
        return handler

    def test_a_disabled_guard_is_named(self) -> None:
        handler = self._handler(_COMMITTED, _WEAKENED)

        result = handler.handle(_bash("git commit -m msg"))

        assert result.decision == Decision.ALLOW, "warn mode never denies"
        assert any("sed_blocker" in line for line in result.context)

    def test_an_unchanged_config_says_nothing(self) -> None:
        handler = self._handler(_COMMITTED, _COMMITTED)

        assert handler.handle(_bash("git commit -m msg")).context == []

    def test_a_strengthened_config_is_not_reported(self) -> None:
        """Turning a guard back ON is drift in the safe direction.

        The session-start report counts it, because there the question is
        "does the working tree differ from what was reviewed". Here the diff is
        right in front of the reviewer, so only WEAKENINGS are worth a line.
        """
        handler = self._handler(_WEAKENED, _COMMITTED)

        assert handler.handle(_bash("git commit -m msg")).context == []

    def test_a_commit_that_cannot_carry_the_config_is_silent(self) -> None:
        handler = self._handler(_COMMITTED, _WEAKENED)

        assert handler.handle(_bash("git commit -m msg docs/a.md")).context == []

    def test_no_committed_baseline_is_not_a_finding(self) -> None:
        handler = self._handler(None, _WEAKENED)

        assert handler.handle(_bash("git commit -m msg")).context == []

    def test_an_unreadable_recorded_config_is_not_a_finding(self) -> None:
        handler = self._handler(_COMMITTED, None)

        assert handler.handle(_bash("git commit -m msg")).context == []

    def test_the_report_does_not_demand_a_marker_or_a_name(self) -> None:
        """The measurement's conclusion, asserted so it cannot quietly regress.

        Both refuted designs would have to reappear as text telling the author
        to add a token or a handler name, so the absence of that instruction is
        the thing to hold.
        """
        handler = self._handler(_COMMITTED, _WEAKENED)

        rendered = " ".join(handler.handle(_bash("git commit -am msg")).context).lower()

        assert "rule change:" not in rendered
        assert "must name" not in rendered


class TestMatching:
    def test_matches_a_git_commit(self) -> None:
        assert GuardConfigCommitGateHandler().matches(_bash("git commit -m msg")) is True

    def test_does_not_match_an_unrelated_command(self) -> None:
        assert GuardConfigCommitGateHandler().matches(_bash("git status")) is False

    def test_does_not_match_a_non_bash_tool(self) -> None:
        handler = GuardConfigCommitGateHandler()

        assert handler.matches({"tool_name": "Write", "tool_input": {}}) is False
