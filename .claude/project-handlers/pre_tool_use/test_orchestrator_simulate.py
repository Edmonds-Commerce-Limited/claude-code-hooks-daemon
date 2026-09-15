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

from orchestrator_simulate import OrchestratorSimulateHandler

from claude_code_hooks_daemon.core.hook_result import Decision


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

    def test_handle_never_returns_deny_attribute_anywhere(self) -> None:
        """Static property check: DENY is not reachable from this handler's code.

        `handle()` is hand-read as having a single `return` statement — this
        test pins the behavioural half of that claim so a future edit that
        adds a second path is caught even if it forgets to re-read the source.
        """
        import inspect

        source = inspect.getsource(self.handler.handle)
        assert "Decision.DENY" not in source
        assert "GatingResult.deny" not in source
        assert ".deny(" not in source

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
        """No acceptance test may expect DENY — this handler cannot produce one."""
        tests = self.handler.get_acceptance_tests()
        assert all(t.expected_decision == Decision.ALLOW for t in tests)
