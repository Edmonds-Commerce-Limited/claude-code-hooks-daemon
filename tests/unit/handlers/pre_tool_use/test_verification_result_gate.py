"""The verifier→mutator gate (Plan 00268 Phase 2).

The motivating incident is `TestTheMotivatingIncident` and it is the reason the
separator handling matters: the lint ran on line 1 and the `git commit` on
line 3 of ONE multi-line Bash command. A handler that scans for `;` between
commands inspects line 1, finds its internal `;`s, and never connects them —
so the obvious implementation misses the very bug that prompted it.

`TestDoesNotCryWolf` is the other half, and the more important one for whether
this handler survives contact with real usage. Every shape in it comes from
ANALYSIS-command-chaining.md §3, where blanket `&&` enforcement was rejected
precisely because it fires on all of them.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.verification_result_gate import (
    VerificationResultGateHandler,
)

_MUTATOR_ONLY = "git commit -m 'x'"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """get_data_layer() is a process-wide singleton (Plan 00116, Decision G).

    Without this, one test's ``mark_disclosed`` for a rule_id + transcript_path
    leaks into a later test that reuses the same pair, turning a genuine
    "first fire" into a stale "already disclosed".
    """
    reset_data_layer()
    yield
    reset_data_layer()


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _fires(handler: VerificationResultGateHandler, command: str) -> bool:
    """Whether the handler produces a finding for this command."""
    hook_input = _bash(command)
    if not handler.matches(hook_input):
        return False
    result = handler.handle(hook_input)
    return bool(result.context) or result.decision == Decision.DENY


@pytest.fixture()
def handler() -> VerificationResultGateHandler:
    return VerificationResultGateHandler()


class TestInitialisation:
    def test_identity_and_priority(self, handler: VerificationResultGateHandler) -> None:
        assert handler.handler_id == HandlerID.VERIFICATION_RESULT_GATE
        assert handler.priority == Priority.VERIFICATION_RESULT_GATE

    def test_is_not_terminal(self, handler: VerificationResultGateHandler) -> None:
        """Advisory: it must never stop other handlers judging the command."""
        assert handler.terminal is False


class TestMatches:
    def test_ignores_non_bash_tools(self, handler: VerificationResultGateHandler) -> None:
        assert handler.matches({"tool_name": "Write", "tool_input": {"file_path": "/x"}}) is False

    def test_ignores_a_command_with_no_mutator_at_all(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """The cheap pre-filter: most Bash calls cannot possibly be findings."""
        assert handler.matches(_bash("ansible-lint site.yml")) is False

    def test_considers_a_command_containing_a_mutator(
        self, handler: VerificationResultGateHandler
    ) -> None:
        assert handler.matches(_bash("ansible-lint site.yml; git commit -m x")) is True


class TestTheMotivatingIncident:
    def test_newline_separated_lint_then_commit_fires(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """THE regression. Nothing here is separated by `;` at the top level —
        the lint's own `;`s are internal to line 1, and the `git add` is a
        NEWLINE away. In shell a newline terminates a command exactly as `;`
        does."""
        command = (
            "ansible-lint site.yml > /tmp/lint.txt 2>&1; "
            'echo "lint exit=$?"; cat /tmp/lint.txt\n'
            "git add site.yml\n"
            "git commit -q -m 'fix'\n"
            "git push"
        )

        assert _fires(handler, command)

    def test_the_finding_names_both_halves_of_the_pair(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """A message that names the pair is actionable; one that says 'use &&'
        is a style opinion, and this handler cannot afford to read as one."""
        result = handler.handle(_bash("ansible-lint site.yml\ngit commit -m x"))
        rendered = " ".join(result.context or []) + (result.guidance or "")

        assert "ansible-lint" in rendered
        assert "git commit" in rendered

    def test_a_printed_exit_code_is_not_a_gate(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """`echo "lint exit=$?"` is exactly what the incident did. It PRINTED
        the result; it consumed nothing. Treating a `$?` mention as a gate
        would exempt the motivating case."""
        assert _fires(handler, 'ansible-lint x; echo "exit=$?"; git commit -m y')


class TestSeparatorParity:
    @pytest.mark.parametrize("separator", [";", "\n", " ; ", "\n\n"])
    def test_semicolon_and_newline_are_equivalent(
        self, handler: VerificationResultGateHandler, separator: str
    ) -> None:
        assert _fires(handler, f"ansible-lint site.yml{separator}git commit -m x")

    def test_a_separator_inside_quotes_is_data(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """One command, not two — so there is no ungated hand-off."""
        assert not _fires(handler, "git commit -m 'ran ansible-lint; then committed'")


class TestConsumedResults:
    def test_direct_and_chaining(self, handler: VerificationResultGateHandler) -> None:
        assert not _fires(handler, "ansible-lint site.yml && git commit -m x")

    def test_explicit_failure_branch(self, handler: VerificationResultGateHandler) -> None:
        assert not _fires(handler, 'ansible-lint x || { echo "failed"; exit 1; }; git commit -m y')

    def test_captured_exit_code_with_a_conditional(
        self, handler: VerificationResultGateHandler
    ) -> None:
        command = (
            "ansible-lint x; rc=$?\n" 'if [ "$rc" -ne 0 ]; then exit 1; fi\n' "git commit -m y"
        )

        assert not _fires(handler, command)

    def test_a_case_statement_also_consumes(self, handler: VerificationResultGateHandler) -> None:
        command = "ansible-lint x; rc=$?\ncase $rc in 0) : ;; *) exit 1 ;; esac\ngit commit -m y"

        assert not _fires(handler, command)

    @pytest.mark.parametrize(
        "set_line", ["set -e", "set -euo pipefail", "set -o errexit", "set -eu"]
    )
    def test_set_e_gates_the_whole_invocation(
        self, handler: VerificationResultGateHandler, set_line: str
    ) -> None:
        assert not _fires(handler, f"{set_line}\nansible-lint x\ngit commit -m y")

    def test_a_mutator_inside_a_quoted_heredoc_body_is_not_executed(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """A quoted delimiter disables every expansion, so the body is text."""
        command = "ansible-lint x\ncat > notes.md <<'EOF'\ngit commit -m 'not run'\nEOF"

        assert not _fires(handler, command)


class TestDoesNotCryWolf:
    """ANALYSIS-command-chaining.md §3, verbatim. Each of these is legitimate
    shell that blanket `&&` enforcement would have broken."""

    @pytest.mark.parametrize(
        "command",
        [
            "grep -q pattern file; echo done",
            'echo "=== A ==="; cmd_a; echo "=== B ==="; cmd_b',
            "ls -1t dir_a; ls -1t dir_b",
            'cmd > file 2>&1; echo "exit=$?"',
            "diff a b; echo '---'",
        ],
    )
    def test_legitimate_diagnostic_shell_is_allowed(
        self, handler: VerificationResultGateHandler, command: str
    ) -> None:
        assert not _fires(handler, command)

    def test_a_mutator_with_no_verifier_is_allowed(
        self, handler: VerificationResultGateHandler
    ) -> None:
        assert not _fires(handler, f"echo starting; {_MUTATOR_ONLY}")

    def test_a_verifier_AFTER_the_mutator_is_allowed(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """Order is the whole point — a lint run after a commit cannot have
        gated it, but it is also not the shape this handler is about."""
        assert not _fires(handler, "git commit -m x; ansible-lint site.yml")

    def test_the_command_name_as_an_argument_is_not_an_invocation(
        self, handler: VerificationResultGateHandler
    ) -> None:
        assert not _fires(handler, "grep ansible-lint notes.md; git commit -m x")


class TestTaxonomy:
    @pytest.mark.parametrize(
        "verifier",
        [
            "ansible-lint site.yml",
            "shellcheck script.sh",
            "bash -n script.sh",
            "pytest tests/",
            "ruff check src/",
            "mypy src/",
            "golangci-lint run",
            "go vet ./...",
            "php -l file.php",
            "npm test",
            "yamllint config.yml",
            "ansible-playbook site.yml --syntax-check",
        ],
    )
    def test_each_verifier_is_recognised(
        self, handler: VerificationResultGateHandler, verifier: str
    ) -> None:
        assert _fires(handler, f"{verifier}\ngit commit -m x")

    @pytest.mark.parametrize(
        "mutator",
        [
            "git add .",
            "git commit -m x",
            "git push",
            "git tag v1.0.0",
            "gh pr create --fill",
            "gh issue create --title x",
            "gh pr merge 1 --merge",
            "ansible-playbook site.yml",
        ],
    )
    def test_each_mutator_is_recognised(
        self, handler: VerificationResultGateHandler, mutator: str
    ) -> None:
        assert _fires(handler, f"ansible-lint site.yml\n{mutator}")

    def test_git_global_options_do_not_hide_the_subcommand(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """`git -C /path commit` read "/path" as the subcommand and walked past
        an earlier guard in this codebase. GIT_INVOCATION exists for it."""
        assert _fires(handler, "ansible-lint site.yml\ngit -C /repo commit -m x")

    def test_a_path_qualified_verifier_is_recognised(
        self, handler: VerificationResultGateHandler
    ) -> None:
        assert _fires(handler, "/usr/bin/ansible-lint site.yml\ngit commit -m x")

    def test_ansible_playbook_is_a_verifier_or_a_mutator_by_its_flags(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """The same binary on both tables, separated only by a flag. The
        verifier table is consulted first, so a dry run is never reported as
        the mutator half of a pair."""
        assert not _fires(handler, "ansible-lint x\nansible-playbook site.yml --check")
        assert not _fires(handler, "ansible-lint x\nansible-playbook site.yml --syntax-check")
        assert _fires(handler, "ansible-lint x\nansible-playbook site.yml")
        assert _fires(handler, "ansible-playbook site.yml --syntax-check\ngit commit -m x")


class TestModes:
    def test_warn_mode_allows_with_context(self, handler: VerificationResultGateHandler) -> None:
        result = handler.handle(_bash("ansible-lint x\ngit commit -m y"))

        assert result.decision == Decision.ALLOW
        assert result.context

    def test_block_mode_denies(self, handler: VerificationResultGateHandler) -> None:
        handler._mode = "block"

        result = handler.handle(_bash("ansible-lint x\ngit commit -m y"))

        assert result.decision == Decision.DENY
        assert result.reason

    def test_block_mode_denies_leads_with_rule_id(
        self, handler: VerificationResultGateHandler
    ) -> None:
        handler._mode = "block"

        result = handler.handle(_bash("ansible-lint x\ngit commit -m y"))

        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.VERIFICATION_RESULT_NOT_CONSUMED}]")

    def test_a_clean_command_allows_silently_in_block_mode(
        self, handler: VerificationResultGateHandler
    ) -> None:
        handler._mode = "block"

        result = handler.handle(_bash("ansible-lint x && git commit -m y"))

        assert result.decision == Decision.ALLOW
        assert not result.context


class TestProjectExtensibility:
    def test_extra_verifiers_are_honoured(self, handler: VerificationResultGateHandler) -> None:
        handler._extra_verifiers = ["my-project-check"]

        assert _fires(handler, "my-project-check\ngit commit -m x")

    def test_extra_mutators_are_honoured(self, handler: VerificationResultGateHandler) -> None:
        handler._extra_mutators = ["terraform apply"]

        assert _fires(handler, "ansible-lint x\nterraform apply")

    def test_a_non_list_option_is_ignored_rather_than_crashing(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """Options arrive by blind setattr from YAML, so the handler must not
        trust the type it is handed."""
        handler._extra_verifiers = "not-a-list"

        assert not _fires(handler, "ansible-lint-x\ngit commit -m y")

    def test_a_config_entry_cannot_smuggle_a_regex(
        self, handler: VerificationResultGateHandler
    ) -> None:
        handler._extra_verifiers = [".*"]

        assert not _fires(handler, "anything at all\ngit commit -m x")


class TestGuidance:
    def test_publishes_resident_guidance(self, handler: VerificationResultGateHandler) -> None:
        guidance = handler.get_claude_md()

        assert guidance is not None
        assert "verification" in guidance.lower()

    def test_guidance_does_not_read_as_a_style_rule_about_chaining(
        self, handler: VerificationResultGateHandler
    ) -> None:
        """Blanket `;`→`&&` enforcement is REJECTED, not deferred. Guidance
        that reads as one invites the disabling this handler cannot afford."""
        guidance = handler.get_claude_md() or ""

        assert "rejected" in guidance.lower() or "not a style" in guidance.lower()

    def test_publishes_acceptance_tests(self, handler: VerificationResultGateHandler) -> None:
        assert handler.get_acceptance_tests()


class TestVerificationResultGateDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder, block mode only."""

    @pytest.fixture
    def handler(self) -> VerificationResultGateHandler:
        handler = VerificationResultGateHandler()
        handler._mode = "block"
        return handler

    def _hook_input(self, command: str, transcript_path: str | None = None) -> dict[str, Any]:
        hook_input = _bash(command)
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_first_fire_for_agent_is_verbose(self, handler: VerificationResultGateHandler) -> None:
        result = handler.handle(
            self._hook_input("ansible-lint x\ngit commit -m y", "/tmp/agent-a/transcript.jsonl")
        )
        assert result.reason is not None
        assert "not consuming" not in result.reason.lower()
        assert "NEWLINE separates commands" in result.reason

    def test_second_fire_for_same_agent_is_terse(
        self, handler: VerificationResultGateHandler
    ) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("ansible-lint x\ngit commit -m y", transcript_path))
        result = handler.handle(self._hook_input("pytest\ngit push", transcript_path))
        assert result.reason is not None
        assert "NEWLINE separates commands" not in result.reason
        assert result.reason.startswith(f"BLOCKED [{RuleID.VERIFICATION_RESULT_NOT_CONSUMED}]")

    def test_missing_transcript_path_fails_toward_verbose_every_time(
        self, handler: VerificationResultGateHandler
    ) -> None:
        hook_input = self._hook_input("ansible-lint x\ngit commit -m y")
        first = handler.handle(hook_input)
        second = handler.handle(hook_input)
        assert first.reason is not None
        assert second.reason is not None
        assert "NEWLINE separates commands" in first.reason
        assert "NEWLINE separates commands" in second.reason


class TestVerificationResultGateGetRules:
    """get_rules() declares the single block-mode Rule (Plan 00116)."""

    @pytest.fixture
    def handler(self) -> VerificationResultGateHandler:
        return VerificationResultGateHandler()

    def test_returns_one_rule(self, handler: VerificationResultGateHandler) -> None:
        rules = handler.get_rules()
        assert len(rules) == 1
        assert all(isinstance(rule, Rule) for rule in rules)

    def test_rule_id_matches_constant(self, handler: VerificationResultGateHandler) -> None:
        rules = handler.get_rules()
        assert rules[0].rule_id == RuleID.VERIFICATION_RESULT_NOT_CONSUMED

    def test_rule_has_non_empty_verbose(self, handler: VerificationResultGateHandler) -> None:
        rules = handler.get_rules()
        assert rules[0].verbose
