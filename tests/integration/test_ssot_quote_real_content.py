"""Integration test: ssot-quote mechanism against REAL repo content (Plan 00284, Task 3.1d).

Proves the anchor slug algorithm, span extraction, and quote verification
work against an actual document in this repository — not just synthetic
fixtures. Deliberately does NOT migrate any real snippet into an
``ssot-quote`` block (that is Task 3.2 content work); it only proves the
mechanism WOULD work if such a block existed.
"""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.quotes import resolve_anchor_span, verify_quote

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GENERAL_LIFECYCLE_DOC = _REPO_ROOT / "CLAUDE" / "CodeLifecycle" / "General.md"

# Verbatim from CLAUDE/CodeLifecycle/General.md's "## Overview" section, as
# it read when this test was written. A real ssot-quote author would copy
# this same excerpt into a quoting doc; this test just proves the
# resolve+verify pipeline accepts it. Spans two paragraphs (not just the
# single 79-character opening sentence) to clear MIN_QUOTE_LENGTH_CHARS.
_REAL_QUOTE = (
    "Standard process for any code modification that isn't a new feature or "
    "bug fix.\n\n**Use this for**:"
)


class TestRealDocumentAnchorResolution:
    def test_general_lifecycle_doc_exists(self) -> None:
        """Guard: if this doc moves, the test below would silently no-op."""
        assert _GENERAL_LIFECYCLE_DOC.is_file()

    def test_overview_heading_slugs_and_resolves(self) -> None:
        text = _GENERAL_LIFECYCLE_DOC.read_text(encoding="utf-8")
        span = resolve_anchor_span(text, "overview")
        assert span is not None
        assert "Standard process for any code modification" in span
        # The NEXT section's heading must not leak into this span.
        assert "## Quick Checklist" not in span

    def test_real_excerpt_verifies_against_the_real_span(self) -> None:
        text = _GENERAL_LIFECYCLE_DOC.read_text(encoding="utf-8")
        span = resolve_anchor_span(text, "overview")
        assert span is not None
        assert verify_quote(_REAL_QUOTE, span) is True

    def test_a_deliberately_drifted_excerpt_fails_against_the_real_span(self) -> None:
        text = _GENERAL_LIFECYCLE_DOC.read_text(encoding="utf-8")
        span = resolve_anchor_span(text, "overview")
        assert span is not None
        drifted = (
            "Standard process for any code modification that IS a brand-new "
            "feature request, not a bug fix at all."
        )
        assert verify_quote(drifted, span) is False


class TestRealDocumentThroughTheCheck:
    """The same real content, run through the actual quote-drift check."""

    def test_a_synthetic_quoting_file_verifies_clean_against_the_real_source(self) -> None:
        from claude_code_hooks_daemon.docs_qa.checks.quote_drift import CHECKS
        from claude_code_hooks_daemon.docs_qa.context import edit_context
        from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
        from claude_code_hooks_daemon.docs_qa.types import CheckStage

        edit_spec = next(spec for spec in CHECKS if spec.stage is CheckStage.EDIT)
        quoting_content = (
            "<!-- ssot-quote: CLAUDE/CodeLifecycle/General.md#overview -->\n"
            f"{_REAL_QUOTE}\n"
            "<!-- /ssot-quote -->\n"
        )
        # file_path must resolve UNDER the real repo root (the check computes
        # its rel_path from project_root) without actually writing into the
        # tracked tree -- the file is never created, only its path is used.
        context = edit_context(
            project_root=_REPO_ROOT,
            policy=DocumentationPolicy(),
            file_path=_REPO_ROOT / "CLAUDE" / "_scratch_quote_probe.md",
            file_content=quoting_content,
            file_exists_before=False,
        )
        findings = edit_spec.run(context)
        assert findings == []
