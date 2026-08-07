"""The blocking-response debug log must never leak a secret term.

Plan 00201 closed four leak vectors — payload capture, the router's PreToolUse
dump, the front controller's error log, and transcript archives. A fifth
survived: ``HooksDaemon._handle_client`` logs the FULL serialised response at
DEBUG whenever it contains ``deny``/``block``/``permissionDecision``.

That response is not safe by construction. ``sensitive_content`` deliberately
keeps the matched term out of its own deny reason — but every OTHER blocking
handler quotes the offending content back to the user so the block is
actionable: ``error_hiding_blocker`` and ``security_antipattern`` both echo the
matched line. A secret pasted into a Write that one of those denies therefore
reached the daemon log verbatim.

Found by re-reading the log sites after a teammate reported an employer
identifier surfacing in a DEBUG line and classified it out of scope for the
handler. It was out of scope for the handler and squarely in scope for the
redaction pass.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from claude_code_hooks_daemon.daemon import server as server_module

SECRET = "zzqx-nonsense-term"


class TestIsBlockingResponse:
    """Which responses count as blocking — decided structurally, not by substring.

    The original test was ``"deny" in response_json or "block" in response_json
    or "permissionDecision" in response_json`` against the SERIALISED response.
    That matches any response whose text happens to contain those letters, and
    the status line does: `🛡️ 1 blocks`. Every status render was therefore
    written to the log labelled "BLOCKING RESPONSE" — which is how an account
    name ended up in a log about blocking decisions in the first place.

    Each event type states its decision in a different place (Claude Code's
    contract, mirrored in ``core/response_schemas.py``), so all three are read
    explicitly.
    """

    def test_pre_tool_use_deny_is_blocking(self) -> None:
        assert server_module.is_blocking_response(
            {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"}}
        )

    def test_pre_tool_use_ask_is_blocking(self) -> None:
        """`ask` interrupts the user exactly as `deny` does."""
        assert server_module.is_blocking_response(
            {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask"}}
        )

    def test_pre_tool_use_allow_is_not_blocking(self) -> None:
        assert not server_module.is_blocking_response(
            {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
        )

    def test_top_level_block_decision_is_blocking(self) -> None:
        """PostToolUse / Stop / SubagentStop / UserPromptSubmit shape."""
        assert server_module.is_blocking_response({"decision": "block", "reason": "no"})

    def test_permission_request_nested_behavior_is_blocking(self) -> None:
        assert server_module.is_blocking_response(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "deny"},
                }
            }
        )

    def test_permission_request_allow_behavior_is_not_blocking(self) -> None:
        assert not server_module.is_blocking_response(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "allow"},
                }
            }
        )

    def test_status_line_containing_the_word_blocks_is_not_blocking(self) -> None:
        """THE regression. This exact shape put an account name in the log.

        The status line reports how many handlers are blocking, so its rendered
        text contains "blocks" on every render — roughly three times a second.
        """
        status = {"text": "🤖 Opus 5 | 📁 my-repo | 🛡️ 1 blocks | 👤 someone"}

        assert not server_module.is_blocking_response(status)

    def test_advisory_context_mentioning_deny_is_not_blocking(self) -> None:
        """Handler guidance routinely explains what gets DENIED. That is prose."""
        assert not server_module.is_blocking_response(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "This handler will deny a git reset and block a stash.",
                }
            }
        )

    def test_empty_response_is_not_blocking(self) -> None:
        assert not server_module.is_blocking_response({})

    def test_malformed_shapes_do_not_raise(self) -> None:
        """A log predicate must never be able to break dispatch."""
        for malformed in (
            {"hookSpecificOutput": "not-a-dict"},
            {"hookSpecificOutput": {"decision": "not-a-dict"}},
            {"decision": {"unexpected": "shape"}},
            {"decision": None},
        ):
            assert not server_module.is_blocking_response(malformed)


def test_secret_term_is_redacted_from_the_blocking_response_log() -> None:
    response = {
        "hookSpecificOutput": {
            "permissionDecision": "deny",
            "permissionDecisionReason": f"matched line: password = '{SECRET}'",
        }
    }
    response_json = json.dumps(response)

    with patch.object(server_module, "get_active_secret_terms", return_value=(SECRET,)):
        logged = server_module.redacted_blocking_response(response_json)

    assert SECRET not in logged
    assert "permissionDecision" in logged, "redaction must not destroy the diagnostic"


def test_clean_response_is_logged_unchanged_when_no_terms_configured() -> None:
    """No secret list -> behaviour is exactly as before (backward compatible)."""
    response_json = json.dumps({"decision": "block", "reason": "plain reason"})

    with patch.object(server_module, "get_active_secret_terms", return_value=()):
        logged = server_module.redacted_blocking_response(response_json)

    assert "plain reason" in logged


def test_response_is_truncated_to_the_log_limit() -> None:
    response_json = "x" * (server_module.BLOCKING_RESPONSE_LOG_CHARS + 500)

    with patch.object(server_module, "get_active_secret_terms", return_value=()):
        logged = server_module.redacted_blocking_response(response_json)

    assert len(logged) == server_module.BLOCKING_RESPONSE_LOG_CHARS


def test_redaction_is_skipped_when_debug_logging_is_off() -> None:
    """The cost must not be paid for a record that is then discarded.

    ``logger.debug(fmt, expensive(x))`` evaluates ``expensive(x)`` eagerly --
    logging only skips FORMATTING, not argument evaluation. Measured at ~0.97ms
    per call on an 8KB response with 12 terms configured, against a daemon-side
    dispatch budget of ~1.8ms, so an unguarded call would have added ~50% to
    every deny/block response at INFO level for a log line nobody would read.
    """
    with patch.object(server_module, "get_active_secret_terms") as terms:
        server_module.log_blocking_response(json.dumps({"decision": "block"}), debug_enabled=False)

    terms.assert_not_called()


def test_redaction_runs_when_debug_logging_is_on() -> None:
    with patch.object(server_module, "get_active_secret_terms", return_value=(SECRET,)) as terms:
        server_module.log_blocking_response(
            json.dumps({"decision": "block", "reason": SECRET}), debug_enabled=True
        )

    terms.assert_called_once()


def test_only_a_bounded_window_is_redacted() -> None:
    """Cost must not scale with response size.

    Redaction is linear in length -- measured at 0.94ms for 8KB, 8.2ms for
    64KB and 30ms for 256KB with 12 terms. A SessionStart response carrying the
    full resident guidance sits in that top bracket, and the first version of
    this helper redacted ALL of it in order to log the first 1000 characters.

    Asserted as a property of the call rather than as a stopwatch: a timing
    test would be flaky, but "never hand redact_text more than the window"
    is exact.
    """
    huge = "x" * 500_000
    longest = "a" * 40
    terms = (SECRET, longest)
    expected_window = server_module.BLOCKING_RESPONSE_LOG_CHARS + len(longest)

    with patch.object(server_module, "get_active_secret_terms", return_value=terms):
        with patch.object(server_module, "redact_text", side_effect=lambda text, _: text) as spy:
            server_module.redacted_blocking_response(huge)

    (passed_text, _), _ = spy.call_args
    assert len(passed_text) == expected_window, (
        f"redact_text received {len(passed_text):,} chars; the window is "
        f"{expected_window:,}. Redacting the whole response to log 1000 chars "
        "reintroduces a cost linear in response size."
    )


def test_redaction_happens_before_truncation() -> None:
    """A term straddling the cut must not leave a readable prefix behind.

    Truncating first and redacting the window would let the head of a secret
    sitting on the boundary survive — half a credential in a log is still a
    credential in a log.
    """
    limit = server_module.BLOCKING_RESPONSE_LOG_CHARS
    # Place the term so it starts just inside the window and ends outside it.
    padding = "x" * (limit - (len(SECRET) // 2))
    response_json = padding + SECRET + "tail"

    with patch.object(server_module, "get_active_secret_terms", return_value=(SECRET,)):
        logged = server_module.redacted_blocking_response(response_json)

    assert SECRET[: len(SECRET) // 2] not in logged
