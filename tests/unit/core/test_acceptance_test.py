"""Tests for AcceptanceTest dataclass."""

from dataclasses import FrozenInstanceError

import pytest

from claude_code_hooks_daemon.constants import ToolName
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.acceptance_test import (
    AcceptanceTest,
    RecommendedModel,
    TestType,
    ToolPayload,
)


class TestAcceptanceTestDataclass:
    """Test AcceptanceTest dataclass structure and validation."""

    def test_acceptance_test_creation_minimal(self):
        """Test creating AcceptanceTest with minimal required fields."""
        test = AcceptanceTest(
            title="Test git reset --hard",
            command='echo "git reset --hard"',
            description="Blocks destructive git reset",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"destroys.*uncommitted"],
        )

        assert test.title == "Test git reset --hard"
        assert test.command == 'echo "git reset --hard"'
        assert test.description == "Blocks destructive git reset"
        assert test.expected_decision == Decision.DENY
        assert test.expected_message_patterns == [r"destroys.*uncommitted"]
        assert test.safety_notes is None
        assert test.setup_commands is None
        assert test.cleanup_commands is None
        assert test.requires_event is None
        assert test.test_type == TestType.BLOCKING
        assert test.recommended_model is None
        assert test.requires_main_thread is False

    def test_acceptance_test_creation_full(self):
        """Test creating AcceptanceTest with all fields."""
        test = AcceptanceTest(
            title="Test sed -i",
            command='sed -i "s/foo/bar/" /tmp/test.txt',
            description="Blocks destructive sed in-place edit",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"Use Edit tool", r"sed -i"],
            safety_notes="Uses /tmp file - harmless",
            setup_commands=['echo "test" > /tmp/test.txt'],
            cleanup_commands=["rm /tmp/test.txt"],
            requires_event="PreToolUse",
            test_type=TestType.BLOCKING,
        )

        assert test.title == "Test sed -i"
        assert test.safety_notes == "Uses /tmp file - harmless"
        assert test.setup_commands == ['echo "test" > /tmp/test.txt']
        assert test.cleanup_commands == ["rm /tmp/test.txt"]
        assert test.requires_event == "PreToolUse"
        assert test.test_type == TestType.BLOCKING

    def test_acceptance_test_advisory_type(self):
        """Test creating advisory (non-blocking) test."""
        test = AcceptanceTest(
            title="British English suggestion",
            command='echo "color organization"',
            description="Suggests British spellings",
            expected_decision=Decision.ALLOW,
            expected_message_patterns=[r"colour", r"organisation"],
            test_type=TestType.ADVISORY,
        )

        assert test.test_type == TestType.ADVISORY
        assert test.expected_decision == Decision.ALLOW

    def test_acceptance_test_context_type(self):
        """Test creating context injection test."""
        test = AcceptanceTest(
            title="Git context injection",
            command="echo 'test prompt'",
            description="Injects git status",
            expected_decision=Decision.ALLOW,
            expected_message_patterns=[r"git.*status"],
            test_type=TestType.CONTEXT,
        )

        assert test.test_type == TestType.CONTEXT


class TestTestTypeEnum:
    """Test TestType enum."""

    def test_test_type_values(self):
        """Test TestType enum has expected values."""
        assert TestType.BLOCKING == "blocking"
        assert TestType.ADVISORY == "advisory"
        assert TestType.CONTEXT == "context"

    def test_test_type_membership(self):
        """Test TestType enum membership."""
        assert "blocking" in [t.value for t in TestType]
        assert "advisory" in [t.value for t in TestType]
        assert "context" in [t.value for t in TestType]


class TestRecommendedModelEnum:
    """Test RecommendedModel enum."""

    def test_recommended_model_values(self):
        """Test RecommendedModel enum has expected values."""
        assert RecommendedModel.HAIKU == "haiku"
        assert RecommendedModel.SONNET == "sonnet"
        assert RecommendedModel.OPUS == "opus"

    def test_recommended_model_membership(self):
        """Test RecommendedModel enum membership."""
        assert "haiku" in [m.value for m in RecommendedModel]
        assert "sonnet" in [m.value for m in RecommendedModel]
        assert "opus" in [m.value for m in RecommendedModel]

    def test_recommended_model_is_str_enum(self):
        """Test RecommendedModel values compare equal to strings."""
        assert RecommendedModel.HAIKU == "haiku"
        assert RecommendedModel.SONNET == "sonnet"


class TestAcceptanceTestNewFields:
    """Test new recommended_model and requires_main_thread fields."""

    def test_default_recommended_model_is_none(self):
        """Test recommended_model defaults to None."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
        )
        assert test.recommended_model is None

    def test_default_requires_main_thread_is_false(self):
        """Test requires_main_thread defaults to False."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
        )
        assert test.requires_main_thread is False

    def test_set_recommended_model_haiku(self):
        """Test setting recommended_model to HAIKU."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
            recommended_model=RecommendedModel.HAIKU,
        )
        assert test.recommended_model == RecommendedModel.HAIKU
        assert test.recommended_model == "haiku"

    def test_set_recommended_model_sonnet(self):
        """Test setting recommended_model to SONNET."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
            recommended_model=RecommendedModel.SONNET,
        )
        assert test.recommended_model == RecommendedModel.SONNET

    def test_set_recommended_model_opus(self):
        """Test setting recommended_model to OPUS."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
            recommended_model=RecommendedModel.OPUS,
        )
        assert test.recommended_model == RecommendedModel.OPUS

    def test_set_requires_main_thread_true(self):
        """Test setting requires_main_thread to True."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.ALLOW,
            expected_message_patterns=[],
            requires_main_thread=True,
        )
        assert test.requires_main_thread is True

    def test_both_new_fields_together(self):
        """Test setting both new fields together."""
        test = AcceptanceTest(
            title="Advisory test",
            command='echo "test advisory"',
            description="Advisory test requiring main thread",
            expected_decision=Decision.ALLOW,
            expected_message_patterns=[r"advisory.*context"],
            test_type=TestType.ADVISORY,
            recommended_model=RecommendedModel.SONNET,
            requires_main_thread=True,
        )
        assert test.recommended_model == RecommendedModel.SONNET
        assert test.requires_main_thread is True
        assert test.test_type == TestType.ADVISORY

    def test_blocking_test_typical_config(self):
        """Test typical BLOCKING test config: haiku, not main thread."""
        test = AcceptanceTest(
            title="Block git reset",
            command='echo "git reset --hard"',
            description="Blocks destructive reset",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"destroys"],
            test_type=TestType.BLOCKING,
            recommended_model=RecommendedModel.HAIKU,
            requires_main_thread=False,
        )
        assert test.recommended_model == RecommendedModel.HAIKU
        assert test.requires_main_thread is False


class TestHarnessCannotProduceField:
    """Test the harness_cannot_produce field (Plan 00196).

    Marks a test whose triggering input the Claude Code harness rewrites
    before the daemon ever sees it, so the playbook must render it as SKIP
    rather than asking a tester to run something that cannot happen.
    """

    def test_defaults_to_none(self):
        """A test is executable unless explicitly marked otherwise."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
        )
        assert test.harness_cannot_produce is None

    def test_carries_the_reason_verbatim(self):
        """The reason is the payload — it is what the tester ends up reading."""
        reason = "Claude Code normalises file_path to absolute before dispatch."
        test = AcceptanceTest(
            title="Read with relative path",
            command="Use the Read tool with a relative file_path",
            description="Blocks relative paths",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"requires absolute path"],
            harness_cannot_produce=reason,
        )
        assert test.harness_cannot_produce == reason

    def test_coexists_with_blocking_type(self):
        """The test keeps its real type — it is unreachable, not reclassified.

        The handler genuinely blocks; only the route to triggering it is gone.
        Downgrading test_type would misdescribe the handler.
        """
        test = AcceptanceTest(
            title="Write with relative path",
            command="Use the Write tool with a relative file_path",
            description="Blocks relative paths",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"absolute path"],
            test_type=TestType.BLOCKING,
            harness_cannot_produce="harness rewrites the input",
        )
        assert test.test_type == TestType.BLOCKING
        assert test.expected_decision == Decision.DENY


class TestToolPayloadField:
    """Test the structured `tool_payload` field (Plan 00243 Task 1.3).

    `command` is overloaded: sometimes a literal shell command, sometimes an
    English sentence describing a tool call ("Use the Write tool to create
    file X with content Y"). Nothing marked which, so the prototype harness
    guessed with regexes and produced 49 false failures — five grammars for
    one payload.

    A shell string is the WRONG target for those tests. A Write-tool guard is
    not reachable from bash at all: this project's own rules record that a
    file written through Bash bypasses the content guards that run before a
    `Write`. Rewriting such a test as `echo … > f` would assert the opposite
    of what it means to assert. So the payload is declared, not parsed.
    """

    def test_defaults_to_none(self):
        """A test carries no payload unless it needs one."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
        )
        assert test.tool_payload is None

    def test_carries_the_tool_name_and_input(self):
        payload = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={"file_path": "/repo/x.py", "content": "def f():\n    pass\n"},
        )
        test = AcceptanceTest(
            title="A guarded write is blocked",
            command="Use the Write tool to create /repo/x.py",
            description="Blocks the guarded content",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"blocked"],
            tool_payload=payload,
        )
        assert test.tool_payload is not None
        assert test.tool_payload.tool_name == ToolName.WRITE
        assert test.tool_payload.tool_input["file_path"] == "/repo/x.py"

    def test_payload_is_frozen(self):
        """A shared default must not be mutable by one consumer.

        Handlers build these at import time and the generator hands the same
        object to every renderer; a mutable payload would let one of them
        edit what the next reads.
        """
        payload = ToolPayload(tool_name=ToolName.WRITE, tool_input={"file_path": "/a"})
        with pytest.raises(FrozenInstanceError):
            payload.tool_name = ToolName.EDIT

    def test_empty_tool_name_rejected(self):
        """An unnamed tool cannot be dispatched, so it must not construct."""
        with pytest.raises(ValueError):
            ToolPayload(tool_name="", tool_input={"file_path": "/a"})

    def test_blank_tool_name_rejected(self):
        with pytest.raises(ValueError):
            ToolPayload(tool_name="   ", tool_input={"file_path": "/a"})

    def test_a_payload_and_a_skip_reason_are_mutually_exclusive(self):
        """A test the harness cannot produce has no payload to produce.

        Declaring both says the test is simultaneously unreachable and
        directly dispatchable. Whichever is true, the other is a lie the
        harness would act on.
        """
        with pytest.raises(ValueError):
            AcceptanceTest(
                title="Contradiction",
                command="Use the Write tool",
                description="Cannot be both",
                expected_decision=Decision.DENY,
                expected_message_patterns=[],
                harness_cannot_produce="Claude Code rewrites the path",
                tool_payload=ToolPayload(tool_name=ToolName.WRITE, tool_input={"file_path": "/a"}),
            )

    def test_dispatch_as_bash_derives_the_payload_from_the_command(self):
        """A shell test states its command ONCE (Plan 00345 Task 3.1).

        For a prose test the sentence is derived from the payload. A shell
        test needs the opposite direction: the bare command is already the
        best thing a human can be handed, so `as_instruction()` would only
        make it harder to paste. Deriving the payload FROM the command keeps
        one copy, which is what stops the two disagreeing.
        """
        command = 'echo "git reset --hard SAFE_TEST"'
        test = AcceptanceTest(
            title="git reset --hard",
            command=command,
            description="Blocks it",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"destroys"],
            dispatch_as_bash=True,
        )
        assert test.tool_payload is not None
        assert test.tool_payload.tool_name == ToolName.BASH
        assert test.tool_payload.tool_input == {"command": command}

    def test_the_command_a_human_is_shown_is_left_byte_identical(self):
        """The human route must not get worse in exchange for the machine one."""
        command = "grep -r 'x' /"
        test = AcceptanceTest(
            title="probe",
            command=command,
            description="Blocks it",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"x"],
            dispatch_as_bash=True,
        )
        assert test.command == command

    def test_dispatch_as_bash_and_an_explicit_payload_are_mutually_exclusive(self):
        """Two payloads for one probe, and nothing says which the harness runs.

        The five blocks that carry a shell-shaped command but match a DIFFERENT
        tool are exactly why this must raise rather than pick a winner.
        """
        with pytest.raises(ValueError):
            AcceptanceTest(
                title="Contradiction",
                command="npx eslint .",
                description="Cannot be both",
                expected_decision=Decision.DENY,
                expected_message_patterns=[],
                dispatch_as_bash=True,
                tool_payload=ToolPayload(tool_name=ToolName.WRITE, tool_input={"file_path": "/a"}),
            )

    def test_dispatch_as_bash_and_a_skip_reason_are_mutually_exclusive(self):
        """Same contradiction as the explicit-payload case, one step removed."""
        with pytest.raises(ValueError):
            AcceptanceTest(
                title="Contradiction",
                command='echo "x"',
                description="Cannot be both",
                expected_decision=Decision.DENY,
                expected_message_patterns=[],
                dispatch_as_bash=True,
                harness_cannot_produce="Claude Code rewrites the path",
            )

    def test_prose_command_is_kept_alongside_the_payload(self):
        """The playbook is still read by a human (Task 1.4).

        The payload is for the harness; the sentence is what a tester follows.
        Replacing one with the other would fix a machine and break a person.
        """
        prose = "Use the Write tool to create /repo/x.py with content 'x = 1'"
        test = AcceptanceTest(
            title="Write probe",
            command=prose,
            description="Blocks something",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"x"],
            tool_payload=ToolPayload(
                tool_name=ToolName.WRITE, tool_input={"file_path": "/repo/x.py", "content": "x = 1"}
            ),
        )
        assert test.command == prose


class TestPayloadRendersItsOwnInstruction:
    """`as_instruction()` renders the human sentence FROM the payload.

    The audit counted FIVE grammars expressing one Write payload —
    "create file X with content Y", "write file_path='X' with content 'Y'",
    "Write file_path=\"X\" content=\"Y\"", and two more. They exist because
    each site hand-wrote its own sentence next to its own values, so the two
    could disagree and nothing would notice.

    Rendering the sentence from the payload removes the second copy. A site
    states the payload once; the prose is derived, so a harness and a human
    tester are reading the same fact by construction rather than by review.
    """

    def test_write_payload_names_the_tool_and_both_arguments(self):
        payload = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={"file_path": "/repo/x.py", "content": "x = 1"},
        )
        instruction = payload.as_instruction()

        assert "Write" in instruction
        assert "/repo/x.py" in instruction
        assert "x = 1" in instruction

    def test_instruction_is_stable_regardless_of_key_order(self):
        """Two sites stating the same payload must read identically.

        Dict order follows insertion, so without this the same probe written
        by two authors renders as two grammars again — the exact defect.
        """
        a = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={"file_path": "/repo/x.py", "content": "x = 1"},
        )
        b = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={"content": "x = 1", "file_path": "/repo/x.py"},
        )
        assert a.as_instruction() == b.as_instruction()

    def test_works_for_a_tool_that_is_not_write(self):
        """The grammar is generic — nothing about it is Write-specific."""
        payload = ToolPayload(
            tool_name=ToolName.EDIT,
            tool_input={"file_path": "/repo/x.py", "old_string": "a", "new_string": "b"},
        )
        instruction = payload.as_instruction()

        assert "Edit" in instruction
        assert "old_string" in instruction
        assert "new_string" in instruction

    def test_a_tool_with_no_arguments_still_reads_as_a_sentence(self):
        payload = ToolPayload(tool_name="AskUserQuestion")
        assert "AskUserQuestion" in payload.as_instruction()

    def test_multiline_content_is_rendered_readably(self):
        """A newline inside a sentence would break the playbook's layout.

        The playbook renders this inline in a `**Command**` block, so a raw
        newline would split one instruction across two lines and read as two.
        """
        payload = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={"file_path": "/a.py", "content": "line one\nline two"},
        )
        assert "\n" not in payload.as_instruction()


class TestHookInputField:
    """Test the structured `hook_input` field (Plan 00319 Task 4.6).

    `tool_payload` carries only `tool_name`/`tool_input` — the shape of a
    TOOL CALL — so it cannot represent an event with no tool call at all
    (SubagentStop's `last_assistant_message`, SessionStart's empty input,
    etc.). `hook_input` is the general escape hatch: the RAW dict a CI-time
    contract test hands straight to `handler.handle()`, for exactly the
    tests a `ToolPayload` cannot describe.
    """

    def test_defaults_to_none(self):
        """A test carries no raw hook_input unless it needs one."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
        )
        assert test.hook_input is None

    def test_carries_the_dict_verbatim(self):
        raw = {"last_assistant_message": "x" * 5000, "stop_hook_active": False}
        test = AcceptanceTest(
            title="Oversized subagent report",
            command="Dispatch a subagent that returns an oversized final message",
            description="Blocks the stop",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"REPORT TOO LARGE"],
            hook_input=raw,
        )
        assert test.hook_input == raw

    def test_a_hook_input_and_a_skip_reason_are_mutually_exclusive(self):
        """A test the harness cannot produce has no input to drive it with."""
        with pytest.raises(ValueError):
            AcceptanceTest(
                title="Contradiction",
                command="Dispatch a subagent",
                description="Cannot be both",
                expected_decision=Decision.DENY,
                expected_message_patterns=[],
                harness_cannot_produce="Claude Code rewrites the input",
                hook_input={"last_assistant_message": "x"},
            )

    def test_a_hook_input_and_a_tool_payload_are_mutually_exclusive(self):
        """Two declared inputs for one probe, and nothing says which wins."""
        with pytest.raises(ValueError):
            AcceptanceTest(
                title="Contradiction",
                command="Dispatch a subagent",
                description="Cannot be both",
                expected_decision=Decision.DENY,
                expected_message_patterns=[],
                hook_input={"last_assistant_message": "x"},
                tool_payload=ToolPayload(tool_name=ToolName.WRITE, tool_input={"file_path": "/a"}),
            )

    def test_a_hook_input_and_dispatch_as_bash_are_mutually_exclusive(self):
        with pytest.raises(ValueError):
            AcceptanceTest(
                title="Contradiction",
                command='echo "x"',
                description="Cannot be both",
                expected_decision=Decision.DENY,
                expected_message_patterns=[],
                hook_input={"last_assistant_message": "x"},
                dispatch_as_bash=True,
            )


class TestAcceptanceTestValidation:
    """Test validation of AcceptanceTest fields."""

    def test_empty_title_rejected(self):
        """Test that empty title is rejected."""
        with pytest.raises((ValueError, TypeError)):
            AcceptanceTest(
                title="",
                command='echo "test"',
                description="Test",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
            )

    def test_empty_command_rejected(self):
        """Test that empty command is rejected."""
        with pytest.raises((ValueError, TypeError)):
            AcceptanceTest(
                title="Test",
                command="",
                description="Test",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
            )

    def test_empty_description_rejected(self):
        """Test that empty description is rejected."""
        with pytest.raises((ValueError, TypeError)):
            AcceptanceTest(
                title="Test",
                command='echo "test"',
                description="",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
            )
