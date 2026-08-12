"""Tests for the plan-doc-size remedy single source of truth (Plan 00211).

Field report: the plan-size guidance offered exactly TWO remedies (RELOCATE,
SPLIT) with no slot for durable-but-current detail — the most common cause
of an oversized ``PLAN.md``. The fix adds EXTRACT as the first-listed
remedy, but three surfaces (``plan_doc_size.py``, ``plan_qa_edit.py``,
``plan_workflow.py``) had each hand-copied the wording, which is exactly
how it drifted in the first place. This module is the single source of
truth; these tests pin its content and ordering so future edits cannot
silently regress it.
"""

from claude_code_hooks_daemon.plan_qa.remedy import REMEDIES, remedy_markdown_list, remedy_sentence


class TestRemedyOrdering:
    """EXTRACT must lead: it is the correct answer most often (Plan 00211)."""

    def test_exactly_three_remedies(self) -> None:
        assert len(REMEDIES) == 3

    def test_extract_is_first(self) -> None:
        assert REMEDIES[0].verb == "EXTRACT"

    def test_relocate_is_second(self) -> None:
        assert REMEDIES[1].verb == "RELOCATE"

    def test_split_is_third(self) -> None:
        assert REMEDIES[2].verb == "SPLIT"

    def test_every_remedy_has_non_empty_detail(self) -> None:
        assert all(remedy.detail for remedy in REMEDIES)


class TestRemedySentenceRendering:
    """Inline-prose rendering used in a ``Finding.remediation`` string."""

    def test_states_none_is_deletion(self) -> None:
        assert "NONE is deletion" in remedy_sentence()

    def test_states_three_remedies(self) -> None:
        assert "Three remedies" in remedy_sentence()

    def test_orders_verbs_extract_relocate_split(self) -> None:
        sentence = remedy_sentence()
        assert sentence.index("EXTRACT") < sentence.index("RELOCATE") < sentence.index("SPLIT")

    def test_mentions_journal_and_supporting_document(self) -> None:
        sentence = remedy_sentence()
        assert "JOURNAL/" in sentence
        assert "supporting document" in sentence

    def test_never_recommends_deleting_or_trimming(self) -> None:
        lowered = remedy_sentence().lower()
        assert "delete" not in lowered
        assert "trim" not in lowered

    def test_is_a_single_line(self) -> None:
        """No embedded newlines — must drop cleanly into prose contexts."""
        assert "\n" not in remedy_sentence()

    def test_is_deterministic(self) -> None:
        assert remedy_sentence() == remedy_sentence()


class TestRemedyMarkdownListRendering:
    """Numbered markdown list rendering used in CLAUDE.md prose contexts."""

    def test_three_numbered_lines(self) -> None:
        lines = remedy_markdown_list().split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("1. **EXTRACT**")
        assert lines[1].startswith("2. **RELOCATE**")
        assert lines[2].startswith("3. **SPLIT**")

    def test_never_recommends_deleting_or_trimming(self) -> None:
        lowered = remedy_markdown_list().lower()
        assert "delete" not in lowered
        assert "trim" not in lowered

    def test_is_deterministic(self) -> None:
        assert remedy_markdown_list() == remedy_markdown_list()
