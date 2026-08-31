"""Tests for the deny-message fingerprint table (Plan 00116 Task 2b.1).

Parity contract: every fingerprint fragment is a literal substring copied
from its handler's real deny-reason source, so embedding it in a realistic
surrounding template and running it back through :func:`attribute_deny`
must resolve to that same handler, and to no other handler's fingerprints.
This is the practical form of "every blocking handler's own deny output
matches its own fingerprint and no other handler's" the analyser needs:
constructing the full 39-handler real ``GatingResult`` set would require a
crafted ``hook_input`` per handler (effectively the acceptance-test suite),
so this test instead proves each stored fragment is unique across the
whole table (no ambiguity is possible for ANY text containing it) and
resolves correctly on its own.
"""

from __future__ import annotations

from claude_code_hooks_daemon.block_report.fingerprints import (
    FINGERPRINT_TABLE,
    UNRESOLVED_HANDLER_PAIRS,
    attribute_deny,
)


class TestFingerprintTable:
    def test_every_handler_has_at_least_one_fragment(self) -> None:
        for handler, fragments in FINGERPRINT_TABLE.items():
            assert fragments, f"{handler} has no fingerprint fragments"
            for fragment in fragments:
                assert fragment.strip(), f"{handler} has a blank fragment"

    def test_no_fragment_is_a_substring_of_another_handlers_fragment(self) -> None:
        """A short fragment nested inside a longer one would make matches ambiguous."""
        all_fragments = [
            (handler, fragment)
            for handler, fragments in FINGERPRINT_TABLE.items()
            for fragment in fragments
        ]
        for handler_a, fragment_a in all_fragments:
            for handler_b, fragment_b in all_fragments:
                if handler_a == handler_b:
                    continue
                assert fragment_a not in fragment_b, (
                    f"{handler_a}'s fragment {fragment_a!r} is contained in "
                    f"{handler_b}'s fragment {fragment_b!r} — ambiguous attribution"
                )


class TestAttributeDeny:
    def test_matches_a_realistic_wrapped_fragment(self) -> None:
        for handler, fragments in FINGERPRINT_TABLE.items():
            for fragment in fragments:
                wrapped = f"🚫 {fragment} — some trailing detail the handler generated\n\n"
                assert (
                    attribute_deny(wrapped) == handler
                ), f"fragment {fragment!r} did not attribute back to {handler}"

    def test_unrelated_text_is_unattributed(self) -> None:
        assert attribute_deny("Error: exit code 2, command not found") is None

    def test_empty_text_is_unattributed(self) -> None:
        assert attribute_deny("") is None

    def test_two_fragments_from_different_handlers_together_is_ambiguous(self) -> None:
        text = "BLOCKED: sed is forbidden and also SECRET FILE PROTECTED: nope"
        assert attribute_deny(text) is None

    def test_real_sed_blocker_transcript_text_attributes_correctly(self) -> None:
        # Verbatim shape observed in a real transcript (Plan 00116 research).
        real_text = (
            "BLOCKED: sed is forbidden. Use Edit tool (or parallel Haiku agents "
            'for bulk).\n\nBLOCKED command: echo "=== TOP LEVEL ===" && ls -la'
        )
        assert attribute_deny(real_text) == "sed_blocker"

    def test_real_pipe_blocker_transcript_text_attributes_correctly(self) -> None:
        real_text = (
            "\U0001f6ab BLOCKED: Pipe to tail/head detected\n\nCOMMAND: "
            'echo "=== TRACKED FILE COUNT ===" && git ls-files | wc -l'
        )
        assert attribute_deny(real_text) == "pipe_blocker"


class TestUnresolvedHandlerPairs:
    def test_documents_the_two_ambiguous_qa_gate_pairs(self) -> None:
        assert set(UNRESOLVED_HANDLER_PAIRS) == {
            "plan_qa_edit",
            "plan_qa_commit_gate",
            "docs_qa_edit",
            "docs_qa_commit_gate",
        }

    def test_unresolved_handlers_are_not_in_the_fingerprint_table(self) -> None:
        assert not set(UNRESOLVED_HANDLER_PAIRS) & set(FINGERPRINT_TABLE)
