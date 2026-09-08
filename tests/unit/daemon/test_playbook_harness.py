"""Planning a playbook block into a dispatchable probe (Plan 00243 Phase 2).

The harness that runs the playbook lives in `tests/acceptance/` and needs a
live daemon, so its logic cannot be unit-tested there. The DECISIONS it makes
can be, and they are the part worth pinning: Task 1.2 measured a checker that
reported 29 failures of which every single one was an artefact of the checker
rather than a defect in what it checked.

Two of those artefacts are now requirements rather than lessons, and both are
asserted here:

1. A payload path is stored UNEXPANDED so the playbook stays portable. A
   harness that dispatches the literal `$CLAUDE_PROJECT_DIR/...` writes to a
   path that cannot exist.
2. A PostToolUse event claims a tool call ALREADY HAPPENED. Dispatching one
   without performing the write first describes a world that does not exist,
   and `lint_on_edit._is_lintable` ends with `Path(file_path).exists()` —
   load-bearing and documented as such — so all ten "invalid code blocked"
   probes silently fail to match.

The third lesson is in `verdict`: a handler that correctly declines to match
an allowed input returns NO decision at all. Reading that absence as a failure
is what produced 18 of the 29.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.daemon.playbook_harness import (
    ExecutableProbe,
    RefusedCommands,
    SkippedProbe,
    build_event,
    daemon_error,
    expand_project_dir,
    plan_probe,
    split_playbook,
    verdict,
    vet_probe_commands,
)

_ROOT = Path("/repo")


def _block(**overrides: object) -> dict:
    """A minimal payload-bearing block, shaped like real generator output."""
    block = {
        "test_number": 22,
        "handler_name": "SedBlockerHandler",
        "title": "Write tool: shell script with sed",
        "event_type": "PreToolUse",
        "expected_decision": "deny",
        "expected_message_patterns": [r"BLOCKED \[R-SED-FILE-MODIFICATION\]"],
        "harness_cannot_produce": None,
        "tools_available": True,
        "tool_payload": {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "$CLAUDE_PROJECT_DIR/untracked/scratch/probe.sh",
                "content": "#!/bin/bash\n",
            },
        },
    }
    block.update(overrides)
    return block


class TestExpandProjectDir:
    """The playbook stores paths unexpanded; the harness must resolve them."""

    def test_bare_variable_is_expanded(self) -> None:
        assert expand_project_dir("$CLAUDE_PROJECT_DIR/a/b.txt", _ROOT) == "/repo/a/b.txt"

    def test_braced_variable_is_expanded(self) -> None:
        assert expand_project_dir("${CLAUDE_PROJECT_DIR}/a/b.txt", _ROOT) == "/repo/a/b.txt"

    def test_a_plain_absolute_path_is_untouched(self) -> None:
        assert expand_project_dir("/tmp/x", _ROOT) == "/tmp/x"

    def test_a_value_with_no_variable_is_returned_unchanged(self) -> None:
        assert expand_project_dir("echo hello", _ROOT) == "echo hello"

    def test_the_variable_is_expanded_wherever_it_sits_not_only_at_the_start(self) -> None:
        """It appears mid-string in Bash payloads, not only as a path prefix."""
        assert expand_project_dir("cd $CLAUDE_PROJECT_DIR && ls", _ROOT) == "cd /repo && ls"


class TestPlanProbeExpandsThePayload:
    def test_the_file_path_reaching_the_probe_is_expanded(self) -> None:
        probe = plan_probe(_block(), _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.tool_input["file_path"] == "/repo/untracked/scratch/probe.sh"

    def test_a_non_string_payload_value_survives_expansion(self) -> None:
        """`AskUserQuestion` carries a list of dicts, not a path."""
        block = _block(
            tool_payload={
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{"question": "Which?"}]},
            }
        )
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.tool_input["questions"] == [{"question": "Which?"}]

    def test_the_declared_tool_and_event_reach_the_probe(self) -> None:
        probe = plan_probe(_block(), _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.tool_name == ToolName.WRITE
        assert probe.event_type == "PreToolUse"


class TestPlanProbeSkipsWhatItCannotRun:
    """A false FAILED is worse than no coverage (Plan 00241 Phase 2)."""

    def test_an_unproducible_input_is_skipped_with_its_own_reason(self) -> None:
        block = _block(
            tool_payload=None,
            harness_cannot_produce="Claude Code rewrites a relative path before the daemon sees it",
        )
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, SkippedProbe)
        assert "rewrites a relative path" in probe.reason

    def test_a_prose_test_is_skipped_rather_than_guessed_at(self) -> None:
        """Regexing the sentence is exactly what this plan removed."""
        probe = plan_probe(_block(tool_payload=None), _ROOT)
        assert isinstance(probe, SkippedProbe)
        assert "no tool payload" in probe.reason.lower()

    def test_a_missing_required_tool_is_skipped(self) -> None:
        block = _block(tools_available=False, required_tools=["rustc"])
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, SkippedProbe)
        assert "rustc" in probe.reason

    def test_an_event_the_harness_cannot_dispatch_is_skipped(self) -> None:
        """SessionStart carries no tool call, so a payload cannot drive it."""
        probe = plan_probe(_block(event_type="SessionStart"), _ROOT)
        assert isinstance(probe, SkippedProbe)
        assert "SessionStart" in probe.reason

    def test_a_skipped_probe_still_identifies_the_test_it_stands_for(self) -> None:
        """A skip nobody can trace back to a handler is not reportable."""
        probe = plan_probe(_block(tool_payload=None), _ROOT)
        assert probe.test_number == 22
        assert probe.handler_name == "SedBlockerHandler"


class TestTheWriteIsPerformedForAPostToolUseProbe:
    """A PostToolUse event claims the tool call ALREADY happened."""

    def test_a_post_tool_use_write_requires_the_file_to_exist_first(self) -> None:
        probe = plan_probe(_block(event_type="PostToolUse"), _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.requires_existing_file is True

    def test_a_pre_tool_use_write_must_not_create_the_file(self) -> None:
        """The whole point is that the write has NOT happened yet."""
        probe = plan_probe(_block(event_type="PreToolUse"), _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.requires_existing_file is False

    def test_a_post_tool_use_probe_with_no_file_path_needs_no_write(self) -> None:
        block = _block(
            event_type="PostToolUse",
            tool_payload={"tool_name": "Bash", "tool_input": {"command": "git status"}},
        )
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.requires_existing_file is False


class TestSplitPlaybook:
    def test_executable_and_skipped_are_partitioned_with_nothing_lost(self) -> None:
        """Every block must land in exactly one bucket (success criterion 2)."""
        blocks = [_block(), _block(test_number=23, tool_payload=None)]
        executable, skipped = split_playbook(blocks, _ROOT)
        assert len(executable) == 1
        assert len(skipped) == 1
        assert len(executable) + len(skipped) == len(blocks)

    def test_a_cli_block_is_skipped_not_dropped(self) -> None:
        """`CliAcceptanceTest` blocks carry no event and no payload."""
        blocks = [{"test_number": 1, "handler_name": "cli", "title": "t", "test_type": "cli"}]
        executable, skipped = split_playbook(blocks, _ROOT)
        assert not executable
        assert len(skipped) == 1


class TestVerdict:
    """The decision AND the reason, because a deny for the wrong reason passes."""

    def _probe(self, **overrides: object) -> ExecutableProbe:
        block = _block(**overrides)
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, ExecutableProbe)
        return probe

    def test_a_matching_deny_with_its_pattern_passes(self) -> None:
        assert verdict(self._probe(), "deny", "BLOCKED [R-SED-FILE-MODIFICATION]: no") is None

    def test_an_allow_where_a_deny_was_expected_fails(self) -> None:
        failure = verdict(self._probe(), "allow", "")
        assert failure is not None
        assert "deny" in failure and "allow" in failure

    def test_a_deny_for_the_wrong_reason_fails(self) -> None:
        """The defect Task 2.3 exists for: today this passes."""
        failure = verdict(self._probe(), "deny", "BLOCKED [R-SOMETHING-ELSE]: no")
        assert failure is not None
        assert "R-SED-FILE-MODIFICATION" in failure

    def test_a_deny_with_no_text_at_all_fails(self) -> None:
        failure = verdict(self._probe(), "deny", "")
        assert failure is not None

    def test_a_missing_deny_reports_what_the_handler_DID_say(self) -> None:
        """The one branch that threw its own diagnostic away (Plan 00250 2.4e).

        `lint_on_edit` fails OPEN in three different ways, and two of them
        ALLOW *with an advisory* naming the cause — a timeout, or a linter that
        could not analyse the file. All three arrive here as an empty decision,
        so the advisory is the only thing that separates them. Reporting the
        decision alone turned a self-diagnosing CI failure into one that needs
        the toolchain installed locally to guess at, which is how probe #144
        stayed unexplained across two runs.

        The mirror-image branch below already quotes the text; this one is the
        asymmetry, not a new convention.
        """
        failure = verdict(self._probe(), "", "⚠️ Swift lint check timed out after 15s")
        assert failure is not None
        assert "timed out after 15s" in failure

    def test_a_missing_deny_with_genuinely_no_text_still_says_so(self) -> None:
        """Silence is itself the diagnostic, and must stay legible as silence."""
        failure = verdict(self._probe(), "", "")
        assert failure is not None
        assert "no decision at all" in failure

    def test_a_post_tool_use_refusal_spells_deny_as_block(self) -> None:
        """One `Decision.DENY`, two wire spellings — see `REFUSAL_CAPABLE_EVENTS`.

        The daemon's own table records it: `PreToolUse # permissionDecision:
        deny` beside `PostToolUse # decision: block`. A harness that knows
        only the first reports every PostToolUse deny probe as a failure,
        which was 7 of this harness's first-run mismatches.
        """
        probe = self._probe(event_type="PostToolUse")
        assert verdict(probe, "block", "BLOCKED [R-SED-FILE-MODIFICATION]: no") is None

    def test_a_block_still_has_to_carry_the_declared_reason(self) -> None:
        probe = self._probe(event_type="PostToolUse")
        assert verdict(probe, "block", "BLOCKED [R-OTHER]: no") is not None

    def test_a_block_where_an_allow_was_expected_fails(self) -> None:
        probe = self._probe(event_type="PostToolUse", expected_decision="allow")
        assert verdict(probe, "block", "BLOCKED: nope") is not None

    def test_an_absent_decision_satisfies_an_allow(self) -> None:
        """A handler correctly declining to match returns NO decision.

        Reading this absence as a failure produced 18 of Task 1.2's 29 false
        failures, and is the single easiest way to make this harness useless.
        """
        probe = self._probe(expected_decision="allow")
        assert verdict(probe, "", "") is None

    def test_a_deny_where_an_allow_was_expected_fails(self) -> None:
        probe = self._probe(expected_decision="allow")
        failure = verdict(probe, "deny", "BLOCKED: nope")
        assert failure is not None

    def test_an_allow_probe_does_not_assert_its_advisory_patterns(self) -> None:
        """Advisory text is session-dependent; asserting it invents failures.

        This repo's handlers carry disclosure ladders — a second fire for the
        same agent is deliberately terser than the first. An advisory whose
        wording legitimately varies cannot be a pass condition without making
        the harness report defects that are not there.
        """
        probe = self._probe(expected_decision="allow")
        assert verdict(probe, "allow", "nothing resembling the declared pattern") is None


class TestTheProbeIsInert:
    """A probe must never be executable as a command."""

    def test_a_bash_payload_stays_data_and_is_never_run(self, tmp_path: Path) -> None:
        """The command string is placed in tool_input, not handed to a shell.

        This is what makes it safe to probe a destructive command at all: the
        harness asks the daemon what it WOULD decide, and no shell ever sees
        the string.
        """
        canary = tmp_path / "canary.txt"
        block = _block(
            tool_payload={
                "tool_name": "Bash",
                "tool_input": {"command": f"touch {canary}"},
            }
        )
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.tool_input["command"] == f"touch {canary}"
        assert not canary.exists()


class TestADaemonErrorIsNotAnAllow:
    """The subtlest way this harness could pass everything for no reason.

    A malformed event is REJECTED by the daemon's input schema before any
    handler runs, and the rejection carries no decision. Read as "no decision
    = allow", every ALLOW probe passes while testing precisely nothing, and
    only the DENY probes complain — which reads like a handful of handler
    bugs rather than the one harness bug it is.

    Measured, not imagined: the first run of this harness sent all 26
    PostToolUse probes without the `tool_response` the schema requires.
    """

    def test_a_validation_failure_is_reported_as_an_error(self) -> None:
        error = daemon_error(
            {
                "error": "input_validation_failed",
                "details": ["root: 'tool_response' is a required property"],
                "event_type": "PostToolUse",
            }
        )
        assert error is not None
        assert "tool_response" in error

    def test_an_ordinary_decision_response_is_not_an_error(self) -> None:
        payload = {"hookSpecificOutput": {"permissionDecision": "deny"}}
        assert daemon_error(payload) is None

    def test_an_empty_response_is_not_an_error(self) -> None:
        """Silence is a handler declining to match, which is an allow."""
        assert daemon_error({}) is None


class TestBuildEvent:
    def _probe(self, **overrides: object) -> ExecutableProbe:
        probe = plan_probe(_block(**overrides), _ROOT)
        assert isinstance(probe, ExecutableProbe)
        return probe

    def test_a_post_tool_use_event_carries_the_required_tool_response(self) -> None:
        """`POST_TOOL_USE_INPUT_SCHEMA` requires it; without it nothing runs."""
        event = build_event(self._probe(event_type="PostToolUse"), run_id="r1")
        assert isinstance(event.get("tool_response"), dict)

    def test_a_pre_tool_use_event_does_not_invent_a_response(self) -> None:
        """The tool has not run yet, so there is nothing to report."""
        event = build_event(self._probe(event_type="PreToolUse"), run_id="r1")
        assert "tool_response" not in event

    def test_the_event_names_its_tool_and_input(self) -> None:
        event = build_event(self._probe(), run_id="r1")
        assert event["tool_name"] == "Write"
        assert event["hook_event_name"] == "PreToolUse"
        assert event["tool_input"]["file_path"] == "/repo/untracked/scratch/probe.sh"

    def test_the_event_is_rooted_at_the_project(self) -> None:
        """`cwd` is part of a Bash probe's INPUT, not incidental framing.

        A command carrying a relative path means nothing without the directory
        it resolves against, and the playbook's commands are written as a human
        runs them: from the repository root. Pointing `cwd` anywhere else
        silently rewrites what every such probe asks, and 14 dispatchable
        handlers read this field.

        Measured, not reasoned: dispatching the 94 shell blocks under an
        isolated temp dir instead put `mkdir -p CLAUDE/Plan/99999-probe`
        outside the repository, so `project_containment` answered before
        `plan_number_helper` ever saw it. The probe still denied — with the
        WRONG handler's reason — and its sibling allow-probe denied outright.

        The root travels ON the probe rather than as a parameter so a caller
        has no cwd knob to get wrong; that is what the temp-dir caller was.
        """
        event = build_event(self._probe(), run_id="r1")
        assert event["cwd"] == str(_ROOT)

    def test_each_probe_gets_its_own_session(self) -> None:
        """A shared session would let one probe's disclosure ladder mute another."""
        first = build_event(self._probe(test_number=1), run_id="r1")
        second = build_event(self._probe(test_number=2), run_id="r1")
        assert first["session_id"] != second["session_id"]

    def test_the_same_probe_gets_a_new_session_on_a_later_run(self) -> None:
        """Otherwise the harness only tells the truth the first time it runs.

        `lsp_enforcement` defaults to `block_once`: the first symbol-lookup
        grep in a session is denied, and later ones are allowed. With a
        session id fixed to the test number, the daemon has already spent that
        session's one block, so run two sees an allow and reports a handler
        that is working perfectly as broken. Measured — this harness passed
        clean, then failed on exactly that probe when re-run.
        """
        first = build_event(self._probe(test_number=1), run_id="r1")
        second = build_event(self._probe(test_number=1), run_id="r2")
        assert first["session_id"] != second["session_id"]


class TestThePreToolUseTargetMustNotExistYet:
    """The mirror of the PostToolUse rule, and it bit just as hard.

    A PreToolUse event says the write has NOT happened. Dispatched at a path
    that already exists it describes a different operation — a clobber — and
    `write_clobber_guard` correctly denies it, turning three ALLOW probes into
    failures that say nothing about the handler under test. Residue from an
    earlier run is enough to cause it, so the harness has to assert the world
    matches the claim rather than assume it.
    """

    def test_a_pre_tool_use_write_declares_its_target_must_be_absent(self) -> None:
        probe = plan_probe(_block(event_type="PreToolUse"), _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.requires_absent_file is True

    def test_a_post_tool_use_write_does_not(self) -> None:
        probe = plan_probe(_block(event_type="PostToolUse"), _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.requires_absent_file is False

    def test_a_probe_with_no_file_path_declares_neither(self) -> None:
        block = _block(tool_payload={"tool_name": "Bash", "tool_input": {"command": "git status"}})
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.requires_absent_file is False
        assert probe.requires_existing_file is False


class TestConstructionIsValidated:
    def test_a_probe_without_a_tool_name_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ExecutableProbe(
                test_number=1,
                handler_name="H",
                title="t",
                event_type="PreToolUse",
                tool_name="",
                tool_input={},
                expected_decision="deny",
                expected_message_patterns=[],
                requires_existing_file=False,
            )

    def test_a_skip_without_a_reason_is_rejected(self) -> None:
        """A skip with no reason is indistinguishable from silent absence."""
        with pytest.raises(ValueError):
            SkippedProbe(test_number=1, handler_name="H", title="t", reason="")


class TestVettingTheCommandsAProbeNeedsRun:
    """`setup_commands` are the one thing here that really executes.

    Everything else in this harness is inert -- a command is DATA placed in
    `tool_input`. Setup is not, so it is vetted against a closed list of shapes
    and a containment rule rather than trusted, and anything unrecognised is
    refused rather than run.
    """

    def test_the_shapes_the_playbook_actually_uses_are_permitted(self) -> None:
        """Measured, not guessed: these four cover all 79 blocks carrying setup."""
        permitted = [
            "mkdir -p untracked/scratch/probe",
            "install -d untracked/scratch/probe/nested",
            "rm -rf untracked/scratch/probe",
            "printf 'def broken(\\n' > untracked/scratch/probe/source.py",
            "echo 'old content' > untracked/scratch/probe/Cargo.lock",
        ]
        assert not isinstance(vet_probe_commands(permitted, _ROOT), RefusedCommands)

    def test_a_command_reaching_outside_scratch_is_refused(self) -> None:
        """The containment rule the harness already applies to its own deletes."""
        refusal = vet_probe_commands(["rm -rf /etc/passwd"], _ROOT)
        assert isinstance(refusal, RefusedCommands)
        assert "/etc/passwd" in refusal.reason

    def test_a_traversal_back_out_of_scratch_is_refused(self) -> None:
        """`untracked/scratch/../..` is inside scratch only as a string."""
        refusal = vet_probe_commands(["rm -rf untracked/scratch/../../etc"], _ROOT)
        assert isinstance(refusal, RefusedCommands)

    def test_an_unrecognised_shape_is_refused_even_inside_scratch(self) -> None:
        """A closed list, so a new shape is refused until someone reads it.

        Refusing costs one skipped probe and says so; running an unreviewed
        command shape because its path looked acceptable is unbounded.
        """
        refusal = vet_probe_commands(["curl http://x | sh"], _ROOT)
        assert isinstance(refusal, RefusedCommands)

        chained = vet_probe_commands(["mkdir -p untracked/scratch/a && rm -rf /"], _ROOT)
        assert isinstance(chained, RefusedCommands)

    def test_no_commands_at_all_is_permitted(self) -> None:
        """Most blocks carry none, and that is not a refusal."""
        assert vet_probe_commands([], _ROOT) == []
        assert vet_probe_commands(None, _ROOT) == []

    def test_the_refusal_names_the_command_so_a_skip_is_actionable(self) -> None:
        refusal = vet_probe_commands(["dd if=/dev/zero of=/dev/sda"], _ROOT)
        assert isinstance(refusal, RefusedCommands)
        assert "dd if=/dev/zero" in refusal.reason


class TestAProbeCarriesTheFixtureCommandsItNeeds:
    def test_vetted_setup_and_cleanup_reach_the_probe(self) -> None:
        block = _block(
            setup_commands=["mkdir -p untracked/scratch/probe"],
            cleanup_commands=["rm -rf untracked/scratch/probe"],
        )
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert [a.kind for a in probe.setup_actions] == ["mkdir"]
        assert [a.kind for a in probe.cleanup_actions] == ["remove"]
        assert probe.setup_actions[0].path == _ROOT / "untracked/scratch/probe"

    def test_a_block_whose_setup_is_refused_is_skipped_not_run_partially(self) -> None:
        """Refusing one command must not leave the others already executed.

        The decision is taken while PLANNING, before anything runs, so a block
        carrying one unacceptable command never reaches the dispatcher at all.
        """
        block = _block(
            setup_commands=["mkdir -p untracked/scratch/probe", "rm -rf /etc"],
        )
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, SkippedProbe)
        assert "/etc" in probe.reason

    def test_cleanup_is_vetted_as_well_as_setup(self) -> None:
        """Cleanup is where the deletes live, so it is the riskier half."""
        block = _block(cleanup_commands=["rm -rf /"])
        probe = plan_probe(block, _ROOT)
        assert isinstance(probe, SkippedProbe)

    def test_a_block_with_no_fixture_commands_still_dispatches(self) -> None:
        probe = plan_probe(_block(), _ROOT)
        assert isinstance(probe, ExecutableProbe)
        assert probe.setup_actions == []
        assert probe.cleanup_actions == []
