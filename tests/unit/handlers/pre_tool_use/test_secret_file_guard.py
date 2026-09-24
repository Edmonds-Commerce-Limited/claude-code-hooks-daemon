"""Tests for SecretFileGuardHandler (Plan 00272).

Deny-by-default read guard over configured protected files: Read/Write/Edit/
NotebookEdit/Grep on a protected path, and any Bash command mentioning one,
are DENIED — except the ``secret-meta`` helper and allowlisted consumers with
the path in flag position. No escape hatch (Decision 3).
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.vault_payloads import vault_file_bytes

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import encrypted_at_rest


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


def _hook_input(tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": tool_name, "tool_input": tool_input}


def _handler() -> SecretFileGuardHandler:
    return SecretFileGuardHandler()


class TestInit:
    def test_identity(self) -> None:
        handler = _handler()
        assert handler.handler_id == HandlerID.SECRET_FILE_GUARD
        assert handler.priority == Priority.SECRET_FILE_GUARD
        assert handler.terminal is True

    def test_enabled_by_default(self) -> None:
        assert _handler().get_default_enabled() is True


class TestReadTools:
    def test_read_of_protected_path_matches(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_read_of_dot_secret_file_matches_default(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.claude/block-words.secret"})
        assert handler.matches(hook_input)

    def test_read_of_ordinary_file_does_not_match(self) -> None:
        handler = _handler()
        assert not handler.matches(_hook_input("Read", {"file_path": "/proj/src/main.py"}))

    def test_write_to_protected_path_matches(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Write", {"file_path": "/proj/.vault-pass", "content": "x"})
        assert handler.matches(hook_input)

    def test_edit_of_protected_path_matches(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Edit", {"file_path": "/proj/foo.secret.env", "old_string": "a", "new_string": "b"}
        )
        assert handler.matches(hook_input)

    def test_notebook_edit_of_protected_path_matches(self) -> None:
        handler = _handler()
        hook_input = _hook_input("NotebookEdit", {"notebook_path": "/proj/creds.secret.ipynb"})
        assert handler.matches(hook_input)

    def test_grep_of_protected_path_matches(self) -> None:
        """Grep on a protected file is a content oracle in EVERY output mode."""
        handler = _handler()
        hook_input = _hook_input("Grep", {"pattern": "^a", "path": "/proj/.vault-pass"})
        assert handler.matches(hook_input)

    def test_grep_of_ordinary_dir_does_not_match(self) -> None:
        handler = _handler()
        assert not handler.matches(_hook_input("Grep", {"pattern": "x", "path": "/proj/src"}))

    def test_grep_rooted_at_dir_containing_protected_file_matches(self, tmp_path: Any) -> None:
        """Review finding 2: directory-rooted Grep gets a bounded walk."""
        (tmp_path / ".vault-pass").write_text("x\n")
        handler = _handler()
        assert handler.matches(_hook_input("Grep", {"pattern": "x", "path": str(tmp_path)}))

    def test_glob_tool_is_never_matched(self) -> None:
        """Names-only: presence is the feature, deliberately allowed."""
        handler = _handler()
        assert not handler.matches(_hook_input("Glob", {"pattern": "**/.vault-pass"}))


class TestBash:
    def test_cat_of_protected_path_is_denied(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Bash", {"command": "cat .vault-pass"})
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_interpreter_one_liner_is_denied(self) -> None:
        handler = _handler()
        cmd = "python3 -c \"print(open('.claude/block-words.secret').read())\""
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_secret_meta_helper_is_allowed(self) -> None:
        handler = _handler()
        cmd = "bin/hooks-daemon secret-meta .vault-pass"
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_ansible_playbook_consumer_is_allowed(self) -> None:
        handler = _handler()
        cmd = "ansible-playbook --vault-password-file .vault-pass site.yml"
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_ansible_vault_view_is_denied(self) -> None:
        handler = _handler()
        cmd = "ansible-vault view --vault-password-file .vault-pass secrets.yml"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_clean_command_is_allowed(self) -> None:
        handler = _handler()
        assert not handler.matches(_hook_input("Bash", {"command": "git status"}))

    def test_replace_mode_pattern_denies_bare_positional_consumer_arg(self) -> None:
        """Review finding 1 regression (verified bypass): under mode replace
        the project pattern must reach the flag-position check, so a bare
        positional argument to an allowlisted consumer is DENIED."""
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = ["*.mysecretfile"]
        cmd = "ansible-playbook /x/prod.mysecretfile"
        assert handler.matches(_hook_input("Bash", {"command": cmd}))

    def test_replace_mode_pattern_still_exempts_flag_position(self) -> None:
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = ["*.mysecretfile"]
        cmd = "ansible-playbook --vault-password-file /x/prod.mysecretfile site.yml"
        assert not handler.matches(_hook_input("Bash", {"command": cmd}))


class TestContentScan:
    """Task 4.3: authored SCRIPTS referencing a protected path are denied."""

    def test_script_content_referencing_protected_path_is_denied(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/steal.sh", "content": "#!/bin/bash\ncat .vault-pass\n"},
        )
        assert handler.matches(hook_input)

    def test_markdown_prose_mentioning_protected_name_is_allowed(self) -> None:
        """Docs (this plan's own!) legitimately NAME protected files."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {"file_path": "/proj/CLAUDE/Plan/x/PLAN.md", "content": "protect .vault-pass files"},
        )
        assert not handler.matches(hook_input)

    def test_excluded_path_content_scan_is_skipped(self) -> None:
        """The guard's own source/tests legitimately NAME protected paths —
        the dogfood config excludes them (sensitive_content precedent)."""
        handler = _handler()
        handler._exclude_paths = ["tests/unit/handlers/**"]
        hook_input = _hook_input(
            "Write",
            {
                "file_path": "/proj/tests/unit/handlers/test_x.py",
                "content": "assert guard('cat .vault-pass')",
            },
        )
        assert not handler.matches(hook_input)

    def test_exclusion_never_exempts_a_protected_path_itself(self) -> None:
        """exclude_paths scopes the CONTENT scan only — a protected file stays
        protected even if a glob would exclude it."""
        handler = _handler()
        handler._exclude_paths = ["**/*"]
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))

    def test_clean_script_is_allowed(self) -> None:
        handler = _handler()
        hook_input = _hook_input(
            "Write", {"file_path": "/proj/run.sh", "content": "#!/bin/bash\nls\n"}
        )
        assert not handler.matches(hook_input)


class TestDenyReason:
    def test_reason_names_glob_never_content(self) -> None:
        handler = _handler()
        result = handler.handle(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))
        assert result.reason is not None
        assert ".vault-pass*" in result.reason
        assert "secret-meta" in result.reason

    def test_reason_states_no_escape_hatch(self) -> None:
        handler = _handler()
        result = handler.handle(_hook_input("Bash", {"command": "cat .vault-pass"}))
        assert result.reason is not None
        assert "MUST_" not in result.reason
        assert "human" in result.reason.lower()

    def test_reason_names_the_offending_token_in_a_bash_command(self) -> None:
        """Plan 00356: the glob alone does not say WHICH word tripped it, so
        diagnosing a long command meant bisecting it across repeated denials.
        The token is the caller's own input, never file content."""
        handler = _handler()
        result = handler.handle(
            _hook_input("Bash", {"command": "tar -cf out.tar README.md .vault-pass extra.txt"})
        )
        assert result.reason is not None
        assert ".vault-pass" in result.reason
        assert "README.md" not in result.reason

    def test_reason_names_the_offending_token_in_authored_script_content(self) -> None:
        """The case that actually needed it: a whole FILE was scanned, and
        nothing said which of its lines was the problem."""
        handler = _handler()
        result = handler.handle(
            _hook_input(
                "Write",
                {
                    "file_path": "/proj/deploy.sh",
                    "content": "#!/usr/bin/env bash\nset -e\ncat .vault-pass\necho done\n",
                },
            )
        )
        assert result.reason is not None
        assert "token" in result.reason.lower()
        assert ".vault-pass" in result.reason

    def test_read_route_still_does_not_echo_the_path(self) -> None:
        """The token echo is deliberately NOT extended to the read route: a
        directory-rooted Grep reaches it carrying a protected filename the
        bounded walk DISCOVERED, which the caller never typed."""
        handler = _handler()
        result = handler.handle(_hook_input("Read", {"file_path": "/proj/other.vault-password"}))
        assert result.reason is not None
        assert "other.vault-password" not in result.reason

    def test_grep_of_directory_does_not_echo_the_discovered_filename(self, tmp_path: Any) -> None:
        """The disclosure case the scoping exists for: the walk finds a
        protected file the caller did not name, and must not reveal it."""
        (tmp_path / "found-by-the-walk.vault-password").write_text("x\n")
        handler = _handler()
        result = handler.handle(_hook_input("Grep", {"pattern": "x", "path": str(tmp_path)}))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "found-by-the-walk" not in result.reason

    def test_remediation_points_at_explain_handler_not_the_config_file(self) -> None:
        """Plan 00356: a project on shipped defaults has no `protected_paths`
        key, so the config file cannot answer which globs are in force —
        `explain-handler` prints the effective list."""
        handler = _handler()
        result = handler.handle(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))
        assert result.reason is not None
        assert "explain-handler secret_file_guard" in result.reason

    def test_jq_subscript_in_authored_script_is_no_longer_denied(self) -> None:
        """End-to-end regression for the reported defect: an array subscript
        after a one-letter field is an ordinary jq path, not a protected-path
        reference."""
        handler = _handler()
        hook_input = _hook_input(
            "Write",
            {
                "file_path": "/proj/bin/collect.sh",
                "content": "#!/usr/bin/env bash\nx=$(jq -r '.foo.v[0]' data.json)\n",
            },
        )
        assert handler.matches(hook_input) is False
        assert handler.handle(hook_input).decision == Decision.ALLOW


class TestConfigModes:
    def test_project_patterns_are_additive_by_default(self) -> None:
        handler = _handler()
        handler._protected_paths = ["secrets/prod-token"]
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/secrets/prod-token"}))
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))

    def test_replace_mode_uses_only_project_patterns(self) -> None:
        handler = _handler()
        handler._mode = "replace"
        handler._protected_paths = ["secrets/prod-token"]
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/secrets/prod-token"}))
        assert not handler.matches(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))

    def test_unknown_mode_fails_closed_as_additive(self) -> None:
        handler = _handler()
        handler._mode = "bogus"
        handler._protected_paths = ["extra.thing"]
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/.vault-pass"}))
        assert handler.matches(_hook_input("Read", {"file_path": "/proj/extra.thing"}))


class TestGuidance:
    def test_claude_md_present_with_honest_limits(self) -> None:
        text = _handler().get_claude_md()
        assert text is not None
        assert "secret_file_guard" in text
        assert "no escape hatch" in text.lower() or "NO escape hatch" in text

    def test_acceptance_tests_use_dummy_paths(self) -> None:
        tests = _handler().get_acceptance_tests()
        assert tests
        for test in tests:
            assert "block-words" not in test.command


class TestGetRules:
    """get_rules() declares the 4 Rule objects backing this handler (Plan 00116,
    plus the evaluation-error rule added by Plan 00466 N11)."""

    def test_returns_four_rules(self) -> None:
        rules = _handler().get_rules()
        assert len(rules) == 4
        assert all(isinstance(rule, Rule) for rule in rules)

    def test_rule_ids_match_constants(self) -> None:
        expected = {
            RuleID.SECRET_READ,
            RuleID.SECRET_BASH_MENTION,
            RuleID.SECRET_SCRIPT_AUTHOR,
            RuleID.SECRET_EVALUATION_ERROR,
        }
        actual = {rule.rule_id for rule in _handler().get_rules()}
        assert actual == expected

    def test_every_rule_has_non_empty_verbose(self) -> None:
        for rule in _handler().get_rules():
            assert rule.verbose, f"{rule.rule_id} has empty verbose content"


class TestFailsClosedOnEvaluationError:
    """Plan 00466 N11 (major M4): any exception during evaluation is a DENY,
    structurally -- independent of the daemon's global `strict_mode`.

    N5 fixed the one raise path the coordinator found; this pins the CLASS.
    `matches()`/`handle()` must never propagate an exception at all, since a
    propagated exception is exactly what `core/chain.py`'s non-strict
    default (every client install unless `strict_mode: true`) treats as "no
    match" -- silently disabling this guard for that call, including any
    genuine protected-path mention elsewhere in the same input.
    """

    def test_bash_route_exception_still_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic failure injected by the test")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        hook_input = _hook_input("Bash", {"command": "echo hello"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason
        # n1 (Plan 00466 guard-defects review 2): the exception MESSAGE goes
        # to the log only, never the deny reason -- see
        # TestErrorRouteEchoesOnlyTheExceptionType below.
        assert "synthetic failure injected by the test" not in result.reason

    def test_read_route_exception_still_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> bool:
            raise ValueError("synthetic path_is_protected failure")

        monkeypatch.setattr(guard_module.sfm, "path_is_protected", _raise)
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/ordinary.py"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "ValueError" in result.reason

    def test_bash_scan_deadline_timeout_still_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """B1 (Plan 00466 guard-defects review 2): the mention scan raises
        ``TimeoutError`` when it exceeds the deadline this handler supplies
        (``sfm.SCAN_DEADLINE_SECONDS``) -- a real ``iter_protected_mentions``
        run out of time reaches exactly this same route, since a raise from
        ``find_protected_mention_detail`` is indistinguishable from any
        other evaluation exception to ``_evaluate``'s wrapper."""

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise TimeoutError("secret_file_guard mention scan exceeded its deadline")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        hook_input = _hook_input("Bash", {"command": "echo hello"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "TimeoutError" in result.reason

    def test_grep_directory_route_exception_still_denies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(guard_module.sfm, "path_is_protected", lambda *_a, **_k: False)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError("synthetic directory-walk failure")

        monkeypatch.setattr(guard_module.sfm, "directory_contains_protected", _raise)
        handler = _handler()
        hook_input = _hook_input("Grep", {"path": "/proj/some-dir", "pattern": "x"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "OSError" in result.reason

    def test_script_content_route_exception_still_denies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic script-content-scan failure")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        hook_input = _hook_input(
            "Write", {"file_path": "scripts/x.py", "content": "print('hello')"}
        )

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason

    def test_the_live_nul_byte_path_still_denies(self) -> None:
        """The one raise path the review found still live after N5: a file
        path containing a NUL byte raises `ValueError: embedded null byte`
        out of `os.path.realpath`/`os.path.relpath`. Not exploitable for
        disclosure (no tool can open a NUL path), but the class fix must
        cover it without a dedicated patch."""
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/a\x00b"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_an_evaluation_error_denial_uses_its_own_rule_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        result = handler.handle(_hook_input("Bash", {"command": "echo hello"}))

        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_EVALUATION_ERROR}]")


class TestChainLevelFailClosedBehaviour:
    """n4 (Plan 00466 guard-defects review 2): every prior N11/m1/m2 test in
    this file calls ``matches()``/``handle()`` directly -- not through
    ``HandlerChain.execute(..., strict_mode=False)``, which is the property
    actually claimed ("this guard fails closed independent of the daemon's
    strict_mode"). That gap is exactly why m1 (an exception in `handle()`'s
    own tail) was not caught by the existing direct-call tests.
    """

    def test_a_handle_tail_exception_still_denies_through_the_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(self: object, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic chain-level failure")

        monkeypatch.setattr(guard_module.RuleFormatter, "verbose", _raise)
        chain = HandlerChain()
        chain.add(_handler())
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})

        result = chain.execute(hook_input, strict_mode=False)
        assert result.result.decision == Decision.DENY

    def test_an_evaluation_exception_still_denies_through_the_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic chain-level evaluation failure")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        chain = HandlerChain()
        chain.add(_handler())
        hook_input = _hook_input("Bash", {"command": "echo hello"})

        result = chain.execute(hook_input, strict_mode=False)
        assert result.result.decision == Decision.DENY


class TestErrorRouteEchoesOnlyTheExceptionType:
    """n1 (Plan 00466 guard-defects review 2): the deny reason on an
    evaluation-error route must show only the exception TYPE -- the message
    itself goes to the log only (``logger.exception``). Today no raise path
    carries a filename, but Plan 00356's rule is that a name DISCOVERED by
    a directory walk must never be echoed, and an ``OSError`` message from a
    future ``stat`` call could easily carry one.
    """

    def test_the_evaluation_error_route_omits_the_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("a message that must never reach the deny reason")

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _raise)
        handler = _handler()
        result = handler.handle(_hook_input("Bash", {"command": "echo hello"}))

        assert result.reason is not None
        assert "RuntimeError" in result.reason
        assert "a message that must never reach the deny reason" not in result.reason

    def test_the_handle_tail_error_route_omits_the_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(self: object, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("a different message that must never reach the deny reason")

        monkeypatch.setattr(guard_module.RuleFormatter, "verbose", _raise)
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})
        result = handler.handle(hook_input)

        assert result.reason is not None
        assert "RuntimeError" in result.reason
        assert "a different message that must never reach the deny reason" not in result.reason


class TestMatchesAndHandleShareOneEvaluation:
    """m2 (Plan 00466 guard-defects review 2): ``matches()`` and ``handle()``
    each independently called ``_matched_pattern_and_route`` -- so a
    TRANSIENT raise seen by ``matches()`` (denied, correctly, via the error
    route) could be silently overwritten by a clean re-evaluation inside
    ``handle()``, turning a correct DENY into an ALLOW for a call ``matches()``
    itself already flagged. The two calls must share ONE evaluation per
    dispatch.
    """

    def test_a_transient_raise_seen_by_matches_is_not_erased_by_handle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"count": 0}

        def _flaky(*_args: object, **_kwargs: object) -> tuple[str, str] | None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("transient failure, first call only")
            return None  # a clean re-evaluation finds nothing

        monkeypatch.setattr(guard_module.sfm, "find_protected_mention_detail", _flaky)
        handler = _handler()
        hook_input = _hook_input("Bash", {"command": "echo hello"})

        assert handler.matches(hook_input) is True  # error route: matches() saw the raise
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason


class TestHandleTailFailsClosed:
    """m1 (Plan 00466 guard-defects review 2): ``_evaluate``'s fail-closed
    wrapper only covers reaching a VERDICT. Once ``handle()`` has a real
    match it does further work UNWRAPPED -- resolving the disclosure
    tracker, formatting the rule, string-building the message -- and an
    exception there used to propagate straight out of ``handle()``, which a
    non-strict chain (every install unless ``strict_mode: true``, and M3
    found that inert here too) treats as "no match": ALLOW, for a call that
    had a GENUINE protected mention. ``matches()`` already returned True
    for every case below; the only question is whether ``handle()`` denies
    or raises.
    """

    def test_data_layer_lookup_exception_still_denies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise() -> None:
            raise RuntimeError("synthetic get_data_layer failure")

        monkeypatch.setattr(guard_module, "get_data_layer", _raise)
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason

    def test_rule_formatter_exception_still_denies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(self: object, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic RuleFormatter.verbose failure")

        monkeypatch.setattr(guard_module.RuleFormatter, "verbose", _raise)
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "RuntimeError" in result.reason

    def test_unhashable_transcript_path_still_denies(self) -> None:
        """The review's own concrete case: a list where a string is
        expected (harness-supplied, not agent-controllable, but the fail
        path must hold regardless of how the bad value got there)."""
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})
        hook_input["transcript_path"] = ["not", "a", "string"]

        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY


class TestDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Decision G)."""

    def _read_with_transcript(self, path: str, transcript_path: str) -> dict[str, Any]:
        hook_input = _hook_input("Read", {"file_path": path})
        hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_first_fire_for_agent_is_verbose(self) -> None:
        handler = _handler()
        hook_input = self._read_with_transcript(
            "/proj/.vault-pass", "/tmp/agent-a/transcript.jsonl"
        )
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "secret-meta" in result.reason

    def test_second_fire_for_same_agent_same_rule_is_terse(self) -> None:
        handler = _handler()
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._read_with_transcript("/proj/.vault-pass", transcript_path))
        result = handler.handle(
            self._read_with_transcript("/proj/other.vault-password", transcript_path)
        )

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "NO escape hatch" not in result.reason
        assert "other.vault-password" not in result.reason  # only the glob is echoed

    def test_terse_message_leads_with_rule_id(self) -> None:
        handler = _handler()
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._read_with_transcript("/proj/.vault-pass", transcript_path))
        result = handler.handle(self._read_with_transcript("/proj/.vault-pass", transcript_path))

        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_READ}]")

    def test_different_route_same_agent_is_independently_verbose(self) -> None:
        handler = _handler()
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._read_with_transcript("/proj/.vault-pass", transcript_path))
        hook_input = _hook_input("Bash", {"command": "cat .vault-pass"})
        hook_input["transcript_path"] = transcript_path
        result = handler.handle(hook_input)

        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_BASH_MENTION}]")
        assert "secret-meta" in result.reason

    def test_missing_transcript_path_is_always_verbose(self) -> None:
        handler = _handler()
        hook_input = _hook_input("Read", {"file_path": "/proj/.vault-pass"})
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert result.reason is not None
        assert "secret-meta" in result.reason


# ── Plan 00459: a protected file whose content is encrypted at rest ──────────

_VAULT_REL = "group_vars/all/vault_passwords.yml"
_TEMPLATE_REL = "templates/app.secrets"


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project root the guard resolves as its own, with an encrypted vars file."""
    root = tmp_path / "project"
    root.mkdir()
    _put(root, _VAULT_REL, vault_file_bytes())
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        yield root


def _put(root: Path, relpath: str, data: bytes) -> Path:
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _decrypt_in_place(root: Path, relpath: str) -> None:
    """What `ansible-vault decrypt` leaves behind: the same path, plaintext."""
    (root / relpath).write_bytes(b"db_password: not-a-real-secret\n")


def _in(root: Path, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    return {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(root)}


def _verdict(hook_input: dict[str, Any]) -> Decision:
    handler = _handler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestEncryptedFileOnPathTools:
    def test_read_of_encrypted_file_is_allowed(self, project: Path) -> None:
        hook_input = _in(project, "Read", {"file_path": str(project / _VAULT_REL)})
        assert not _handler().matches(hook_input)
        assert _handler().handle(hook_input).decision == Decision.ALLOW

    def test_read_of_the_same_path_decrypted_in_place_is_denied(self, project: Path) -> None:
        hook_input = _in(project, "Read", {"file_path": str(project / _VAULT_REL)})
        assert _verdict(hook_input) == Decision.ALLOW
        _decrypt_in_place(project, _VAULT_REL)
        assert _verdict(hook_input) == Decision.DENY

    def test_encrypted_dot_secrets_template_is_allowed(self, project: Path) -> None:
        _put(project, _TEMPLATE_REL, vault_file_bytes(version="1.2", label="prod"))
        hook_input = _in(project, "Read", {"file_path": str(project / _TEMPLATE_REL)})
        assert _verdict(hook_input) == Decision.ALLOW

    def test_relative_path_resolves_against_cwd(self, project: Path) -> None:
        assert _verdict(_in(project, "Read", {"file_path": _VAULT_REL})) == Decision.ALLOW

    def test_relative_path_without_cwd_is_denied(self, project: Path) -> None:
        assert _verdict(_hook_input("Read", {"file_path": _VAULT_REL})) == Decision.DENY

    def test_edit_and_write_of_encrypted_file_are_allowed(self, project: Path) -> None:
        path = str(project / _VAULT_REL)
        edit = _in(project, "Edit", {"file_path": path, "old_string": "a", "new_string": "b"})
        write = _in(project, "Write", {"file_path": path, "content": "x"})
        assert _verdict(edit) == Decision.ALLOW
        assert _verdict(write) == Decision.ALLOW

    def test_grep_of_encrypted_file_is_allowed(self, project: Path) -> None:
        hook_input = _in(project, "Grep", {"pattern": "x", "path": str(project / _VAULT_REL)})
        assert _verdict(hook_input) == Decision.ALLOW

    def test_grep_rooted_at_a_tree_of_only_encrypted_files_is_allowed(self, project: Path) -> None:
        hook_input = _in(project, "Grep", {"pattern": "x", "path": str(project / "group_vars")})
        assert _verdict(hook_input) == Decision.ALLOW

    def test_grep_rooted_at_a_tree_with_a_plaintext_sibling_is_denied(self, project: Path) -> None:
        _put(project, "group_vars/all/.vault-pass", b"not-a-real-secret\n")
        hook_input = _in(project, "Grep", {"pattern": "x", "path": str(project / "group_vars")})
        assert _verdict(hook_input) == Decision.DENY

    def test_symlink_named_like_a_vault_file_to_a_plaintext_secret_is_denied(
        self, project: Path
    ) -> None:
        plaintext = _put(project, "notes/plain.txt", b"db_password: not-a-real-secret\n")
        link = project / "group_vars/web/vault_passwords.yml"
        link.parent.mkdir(parents=True)
        link.symlink_to(plaintext)
        assert _verdict(_in(project, "Read", {"file_path": str(link)})) == Decision.DENY
        assert _verdict(_in(project, "Bash", {"command": f"cat {link}"})) == Decision.DENY

    def test_file_too_large_to_verify_is_denied(self, project: Path) -> None:
        hook_input = _in(project, "Read", {"file_path": str(project / _VAULT_REL)})
        with patch.object(encrypted_at_rest, "MAX_INSPECTED_BYTES", 16):
            assert _verdict(hook_input) == Decision.DENY

    def test_empty_file_is_denied(self, project: Path) -> None:
        _put(project, _VAULT_REL, b"")
        assert _verdict(_in(project, "Read", {"file_path": _VAULT_REL})) == Decision.DENY
        assert _verdict(_in(project, "Bash", {"command": f"git add {_VAULT_REL}"})) == Decision.DENY

    def test_encrypted_file_outside_the_project_root_is_denied(
        self, tmp_path: Path, project: Path
    ) -> None:
        outside = _put(tmp_path, "elsewhere/vault_passwords.yml", vault_file_bytes())
        assert _verdict(_in(project, "Read", {"file_path": str(outside)})) == Decision.DENY

    def test_plaintext_vault_password_file_is_protected_as_before(self, project: Path) -> None:
        for name in (".vault_pass", ".vault-pass", "vault_pass.txt"):
            _put(project, name, b"not-a-real-secret\n")
            for hook_input in (
                _in(project, "Read", {"file_path": name}),
                _in(project, "Grep", {"pattern": "x", "path": str(project / name)}),
                _in(project, "Bash", {"command": f"cat {name}"}),
                _in(project, "Bash", {"command": f"git add {name}"}),
            ):
                assert _verdict(hook_input) == Decision.DENY, (name, hook_input)


class TestEncryptedFileOnBash:
    def test_git_add_naming_it_is_allowed(self, project: Path) -> None:
        assert _verdict(_in(project, "Bash", {"command": f"git add {_VAULT_REL}"})) == (
            Decision.ALLOW
        )

    def test_git_commit_naming_it_is_allowed(self, project: Path) -> None:
        command = f"git commit -m 'Rotate the database password' -- {_VAULT_REL}"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.ALLOW

    def test_git_add_after_decrypting_in_place_is_denied(self, project: Path) -> None:
        hook_input = _in(project, "Bash", {"command": f"git add {_VAULT_REL}"})
        _decrypt_in_place(project, _VAULT_REL)
        handler = _handler()
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_BASH_MENTION}]")

    def test_glob_covering_the_encrypted_file_and_a_plaintext_sibling_is_denied(
        self, project: Path
    ) -> None:
        _put(project, f"{_VAULT_REL}.bak", b"db_password: not-a-real-secret\n")
        command = "cat group_vars/all/vault_pass*"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY

    def test_encrypted_and_plaintext_protected_files_together_are_denied(
        self, project: Path
    ) -> None:
        _put(project, ".vault-pass", b"not-a-real-secret\n")
        command = f"git add {_VAULT_REL} .vault-pass"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY

    def test_ansible_vault_view_and_decrypt_stay_denied(self, project: Path) -> None:
        for command in (
            f"ansible-vault view {_VAULT_REL}",
            f"ansible-vault decrypt {_VAULT_REL}",
            f"ansible-vault edit {_VAULT_REL}",
        ):
            assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY, command

    def test_commands_that_could_decrypt_via_configured_password_stay_denied(
        self, project: Path
    ) -> None:
        for command in (
            f"ansible localhost -m debug -a var=db_password -e @{_VAULT_REL}",
            f"git diff {_VAULT_REL}",
            f"python3 decrypt.py {_VAULT_REL}",
        ):
            assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY, command

    def test_directory_change_before_the_read_is_denied(self, project: Path) -> None:
        command = f"cd inventories/staging && cat {_VAULT_REL}"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.DENY

    def test_bash_without_cwd_cannot_resolve_a_relative_mention(self, project: Path) -> None:
        hook_input = _hook_input("Bash", {"command": f"git add {_VAULT_REL}"})
        assert _verdict(hook_input) == Decision.DENY

    def test_existing_consumer_exemption_is_unchanged(self, project: Path) -> None:
        command = "ansible-playbook --vault-password-file .vault-pass site.yml"
        assert _verdict(_in(project, "Bash", {"command": command})) == Decision.ALLOW


class TestEncryptedFileOnScriptAuthoring:
    def test_script_naming_an_encrypted_file_is_still_denied(self, project: Path) -> None:
        """A script runs LATER, by a command that does not name the file, so
        no check can happen at the time of use -- and the file may have been
        decrypted in place by then."""
        hook_input = _in(
            project,
            "Write",
            {"file_path": str(project / "deploy.sh"), "content": f"cat {_VAULT_REL}\n"},
        )
        handler = _handler()
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.SECRET_SCRIPT_AUTHOR}]")


class TestEncryptedFileGuidance:
    def test_claude_md_explains_the_encrypted_exemption(self) -> None:
        text = _handler().get_claude_md()
        assert text is not None
        assert "encrypted at rest" in text.lower()
        assert "ansible-vault view|decrypt" in text

    def test_deny_text_explains_the_encrypted_exemption(self) -> None:
        """The three content-policy rules (read/bash/script) all teach the
        encrypted-at-rest exemption. The evaluation-error rule (Plan 00466
        N11) is a different failure mode entirely -- the guard crashed, it
        never reached a content verdict -- so mentioning an exemption that
        was never evaluated would mislead, not help."""
        for rule in _handler().get_rules():
            if rule.rule_id == RuleID.SECRET_EVALUATION_ERROR:
                continue
            assert "encrypted" in rule.verbose.lower(), rule.rule_id


class TestEncryptedFileAcceptanceProbes:
    def _probe(self, title_fragment: str) -> Any:
        matches = [t for t in _handler().get_acceptance_tests() if title_fragment in t.title]
        assert len(matches) == 1, title_fragment
        return matches[0]

    def test_allow_probe_for_an_encrypted_file(self) -> None:
        probe = self._probe("allows naming an encrypted")
        assert probe.expected_decision == Decision.ALLOW
        assert probe.setup_commands
        assert probe.cleanup_commands

    def test_deny_probe_for_the_decrypted_twin(self) -> None:
        probe = self._probe("decrypted in place")
        assert probe.expected_decision == Decision.DENY
        assert probe.setup_commands

    def test_allow_probe_fixture_is_a_confirmed_vault_payload(self, tmp_path: Path) -> None:
        """The printf fixture must decode to what the detector confirms, or the
        ALLOW probe would pass or fail for the wrong reason."""
        probe = self._probe("allows naming an encrypted")
        writes = [cmd for cmd in probe.setup_commands if cmd.startswith("printf '")]
        assert len(writes) == 1
        payload = writes[0].split("'")[1].replace("\\n", "\n")
        target = tmp_path / "fixture.yml"
        target.write_text(payload)
        assert encrypted_at_rest.is_encrypted_at_rest(target, tmp_path)
