"""The provenance header on a generated issue report (Plan 00403 Task 2.3).

The filing gate needs to tell a body the generator produced from one somebody
typed. The header is how, and what it is worth is worth being precise about.

**It is tamper evidence, not authentication.** Nothing running in-process can
stop an agent that decides to compute a digest itself, and claiming otherwise
would be the kind of false comfort this plan exists to remove. What it does
catch is the realistic failure: a clean report generated, then edited to paste
in the log excerpt or the stack trace that seemed helpful, and filed. That
edit breaks the digest, and breaking it is the whole job.

Parsing never raises. The consumer is a PreToolUse handler, where an escaping
exception takes down the gate rather than reporting a bad document — the same
contract `remote_docs.provenance` runs on, for the same reason.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.issue_report.provenance import (
    PROVENANCE_MARKER,
    body_digest,
    render_document,
    split_document,
    verify_document,
)

_VERSION = "3.27.0"
_WHEN = "2026-09-14"
_BODY = "## What happened\n\nThe handler denied a read-only command.\n"


def _document(body: str = _BODY) -> str:
    return render_document(body, daemon_version=_VERSION, generated_at=_WHEN)


class TestRendering:
    def test_the_body_survives_intact(self) -> None:
        """A header that mangled the report would be worse than none."""
        assert _BODY.strip() in _document()

    def test_the_header_is_an_html_comment_so_github_hides_it(self) -> None:
        """A reader should see the report, not the bookkeeping."""
        document = _document()

        assert document.startswith("<!--")
        assert "-->" in document

    def test_the_marker_names_the_generator(self) -> None:
        assert PROVENANCE_MARKER in _document()

    def test_the_version_and_date_are_recorded(self) -> None:
        document = _document()

        assert _VERSION in document
        assert _WHEN in document

    def test_a_rendered_document_verifies(self) -> None:
        assert verify_document(_document()) == ()


class TestTamperEvidence:
    def test_appending_to_the_body_breaks_the_digest(self) -> None:
        """The realistic failure: a clean report, then a 'helpful' paste."""
        tampered = _document() + "\n\nAlso, here is /home/jbloggs/acme/app.log\n"

        assert verify_document(tampered)

    def test_editing_the_body_breaks_the_digest(self) -> None:
        document = _document().replace("read-only command", "read-only command in acme-payments")

        assert verify_document(document)

    def test_the_failure_says_the_body_changed_after_generation(self) -> None:
        """A gate message that does not say what to do gets worked around."""
        tampered = _document() + "\nextra\n"
        reasons = " ".join(problem.reason for problem in verify_document(tampered))

        assert "regenerate" in reasons.lower()


class TestAHandWrittenBody:
    def test_a_body_with_no_header_is_refused(self) -> None:
        assert verify_document("I think the sed blocker is too aggressive.")

    def test_the_refusal_names_the_generator_rather_than_just_failing(self) -> None:
        reasons = " ".join(problem.reason for problem in verify_document("please fix"))

        assert "issue-report" in reasons

    @pytest.mark.parametrize("text", ["", "   ", "\n"])
    def test_an_empty_document_is_refused(self, text: str) -> None:
        assert verify_document(text)


class TestAMalformedHeader:
    def test_a_header_missing_the_digest_is_refused(self) -> None:
        document = f"<!-- {PROVENANCE_MARKER}\ndaemon_version: 3.27.0\n-->\n\nbody\n"

        assert verify_document(document)

    def test_a_non_hex_digest_is_refused(self) -> None:
        document = (
            f"<!-- {PROVENANCE_MARKER}\n"
            f"daemon_version: {_VERSION}\n"
            f"generated_at: {_WHEN}\n"
            "body_sha256: not-a-digest\n"
            "-->\n\nbody\n"
        )

        assert verify_document(document)

    def test_an_unterminated_header_is_refused_not_raised(self) -> None:
        """Parsing never raises: the consumer is a hook handler."""
        document = f"<!-- {PROVENANCE_MARKER}\ndaemon_version: {_VERSION}\n"

        assert verify_document(document)

    def test_an_empty_body_under_a_valid_header_is_refused(self) -> None:
        """A report with a header and nothing to read helps nobody."""
        assert verify_document(render_document("", daemon_version=_VERSION, generated_at=_WHEN))


class TestSplitting:
    def test_the_body_is_recoverable_for_a_gate_to_re_check(self) -> None:
        """The filing gate re-runs the content rules over the body, not the header."""
        _header, body = split_document(_document())

        assert body.strip() == _BODY.strip()

    def test_a_document_with_no_header_yields_none_and_the_whole_text(self) -> None:
        header, body = split_document("just prose")

        assert header is None
        assert body == "just prose"


class TestTheDigestIsStableAcrossHarmlessDifferences:
    def test_trailing_whitespace_does_not_change_the_digest(self) -> None:
        """Otherwise an editor that strips it on save breaks every report."""
        assert body_digest(_BODY) == body_digest(f"{_BODY}   \n\n")

    def test_windows_line_endings_do_not_change_the_digest(self) -> None:
        """A client on Windows must not be refused for their editor's default."""
        assert body_digest(_BODY) == body_digest(_BODY.replace("\n", "\r\n"))

    def test_a_real_content_change_does_change_it(self) -> None:
        """The guard against a normalisation that normalises everything away."""
        assert body_digest(_BODY) != body_digest(f"{_BODY}and one more thing\n")
