"""Tests for ``plan-doc-size`` (Plan 00190 Phase 3).

Plan documents are read in full every session, so their size is a direct
context-budget cost. Journals are not — they are tailed and grepped — which is
why the limit lands here and never on them.

Tiers escalate advisory -> warning -> block (Decision 1: wording escalates,
``Level`` stays two-valued).
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks.plan_doc_size import CHECK, CHECK_ID
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, PlanDocSizeLimits

_ROOT = Path("/repo")
_PLAN_REL = "CLAUDE/Plan/00190-thing/PLAN.md"

_HEADER = "# Plan 00190: Thing\n\n**Status**: In Progress\n\n"


def _body_of_bytes(total_bytes: int, line_length: int = 79) -> str:
    """Plan-ish content of approximately ``total_bytes``, with normal line lengths."""
    line = "x" * line_length + "\n"
    return _HEADER + line * max(1, (total_bytes - len(_HEADER)) // len(line))


def _body_of_lines(total_lines: int) -> str:
    return _HEADER + "short\n" * total_lines


def _context(
    content: str,
    *,
    rel_path: str = _PLAN_REL,
    content_before: str | None = None,
    limits: PlanDocSizeLimits | None = None,
    legacy: frozenset[int] = frozenset(),
) -> CheckContext:
    return CheckContext(
        project_root=_ROOT,
        plan_dir_rel="CLAUDE/Plan",
        file_path=_ROOT / rel_path,
        file_content=content,
        file_content_before=content_before,
        file_exists_before=content_before is not None,
        legacy_plan_allowlist=legacy,
        plan_doc_size=limits or PlanDocSizeLimits(),
    )


def _run(context: CheckContext):
    return CHECK.run(context)


class TestUnderThreshold:
    def test_small_plan_is_silent(self):
        assert _run(_context(_body_of_bytes(2_000))) == []

    def test_exactly_at_advisory_boundary_is_silent(self):
        """Rule shape is ``>`` not ``>=`` — the threshold itself is allowed."""
        limits = PlanDocSizeLimits()
        content = "y" * limits.advisory_bytes
        assert len(content) == limits.advisory_bytes
        assert _run(_context(content)) == []


class TestTiers:
    def test_advisory_tier_by_bytes(self):
        findings = _run(_context(_body_of_bytes(20_000)))
        assert len(findings) == 1
        assert findings[0].level is Level.ADVISE
        assert findings[0].check_id == CHECK_ID

    def test_advisory_tier_by_lines_alone(self):
        """Either axis trips the tier — a long thin plan costs context too."""
        content = _body_of_lines(400)
        assert len(content) < PlanDocSizeLimits().advisory_bytes
        findings = _run(_context(content))
        assert len(findings) == 1
        assert findings[0].level is Level.ADVISE

    def test_warning_tier_escalates_wording_not_level(self):
        advisory = _run(_context(_body_of_bytes(20_000)))[0]
        warning = _run(_context(_body_of_bytes(28_000)))[0]
        assert warning.level is Level.ADVISE
        assert warning.message != advisory.message

    def test_block_tier(self):
        findings = _run(_context(_body_of_bytes(40_000)))
        assert len(findings) == 1
        assert findings[0].level is Level.BLOCK

    def test_block_tier_by_lines(self):
        findings = _run(_context(_body_of_lines(1_000)))
        assert findings[0].level is Level.BLOCK


class TestMessageNamesTheBreachedAxis:
    """Naming both axes when only one breached misstates the facts.

    A 40 KB / 503-line plan is over the byte limit and well under the line
    limit; "past the hard limit of 35,000 bytes / 900 lines" reads as though
    both were exceeded.
    """

    def test_bytes_only_breach_does_not_cite_the_line_limit(self):
        content = _body_of_bytes(40_000)
        assert content.count("\n") < PlanDocSizeLimits().block_lines
        message = _run(_context(content))[0].message
        assert "35,000 bytes" in message
        assert "900 lines" not in message

    def test_lines_only_breach_does_not_cite_the_byte_limit(self):
        content = _body_of_lines(1_000)
        assert len(content.encode()) < PlanDocSizeLimits().block_bytes
        message = _run(_context(content))[0].message
        assert "900 lines" in message
        assert "35,000 bytes" not in message

    def test_both_axes_breached_cites_both(self):
        content = _body_of_bytes(40_000, line_length=20)
        assert len(content.encode()) > PlanDocSizeLimits().block_bytes
        assert content.count("\n") > PlanDocSizeLimits().block_lines
        message = _run(_context(content))[0].message
        assert "35,000 bytes" in message
        assert "900 lines" in message

    def test_actual_size_is_always_reported(self):
        message = _run(_context(_body_of_bytes(40_000)))[0].message
        assert "tokens" in message


class TestRemediationNamesAllThreeRemedies:
    """Plan 00211: naming only ``relocate``/``split`` leaves no slot for
    durable-but-current detail, so the remediation must also offer EXTRACT.

    Most oversized plans in the corpus carry detail that is neither history
    (relocate) nor an over-scoped task tree (split), so the message must
    offer extraction too — and list it first, since it is the most common
    correct answer.
    """

    @pytest.mark.parametrize("size", [20_000, 28_000, 40_000])
    def test_message_offers_extract_relocate_and_split(self, size):
        finding = _run(_context(_body_of_bytes(size)))[0]
        text = f"{finding.message} {finding.remediation}"
        assert "EXTRACT" in text
        assert "JOURNAL/" in text
        assert "split" in text.lower()

    @pytest.mark.parametrize("size", [20_000, 28_000, 40_000])
    def test_extract_is_listed_before_relocate_and_split(self, size):
        finding = _run(_context(_body_of_bytes(size)))[0]
        text = finding.remediation
        assert text.index("EXTRACT") < text.index("RELOCATE") < text.index("SPLIT")

    @pytest.mark.parametrize("size", [20_000, 28_000, 40_000])
    def test_message_never_recommends_deleting(self, size):
        finding = _run(_context(_body_of_bytes(size)))[0]
        text = f"{finding.message} {finding.remediation}".lower()
        assert "delete" not in text
        assert "trim" not in text


class TestFolderShapeHint:
    """Plan 00211: a suggestion, never a diagnosis (see the docstring on
    ``_folder_has_supporting_docs`` for the 00001 counter-example this
    honours: 19 supporting docs and still oversized because the task tree
    genuinely was the bulk).
    """

    def _context_with_real_folder(self, tmp_path: Path, *, with_supporting_doc: bool):
        plan_folder = tmp_path / "CLAUDE" / "Plan" / "00190-thing"
        plan_folder.mkdir(parents=True)
        if with_supporting_doc:
            (plan_folder / "RESEARCH.md").write_text("findings\n")
        return CheckContext(
            project_root=tmp_path,
            plan_dir_rel="CLAUDE/Plan",
            file_path=plan_folder / "PLAN.md",
            file_content=_body_of_bytes(20_000),
        )

    def test_no_supporting_docs_appends_hint(self, tmp_path: Path):
        context = self._context_with_real_folder(tmp_path, with_supporting_doc=False)
        finding = _run(context)[0]
        assert "no supporting documents" in finding.remediation.lower()
        assert "suggestion" in finding.remediation.lower()

    def test_hint_is_never_phrased_as_a_diagnosis(self, tmp_path: Path):
        context = self._context_with_real_folder(tmp_path, with_supporting_doc=False)
        finding = _run(context)[0]
        lowered = finding.remediation.lower()
        # Never assert the folder shape IS the cause — only suggest it.
        assert "is the cause" not in lowered
        assert "must be" not in lowered

    def test_supporting_doc_present_suppresses_hint(self, tmp_path: Path):
        context = self._context_with_real_folder(tmp_path, with_supporting_doc=True)
        finding = _run(context)[0]
        assert "no supporting documents" not in finding.remediation.lower()

    def test_journal_dayfile_alone_does_not_count_as_a_supporting_doc(self, tmp_path: Path):
        plan_folder = tmp_path / "CLAUDE" / "Plan" / "00190-thing"
        journal_dir = plan_folder / "JOURNAL"
        journal_dir.mkdir(parents=True)
        (journal_dir / "00190-Journal-26-08-12.md").write_text("# Journal\n")
        context = CheckContext(
            project_root=tmp_path,
            plan_dir_rel="CLAUDE/Plan",
            file_path=plan_folder / "PLAN.md",
            file_content=_body_of_bytes(20_000),
        )
        finding = _run(context)[0]
        assert "no supporting documents" in finding.remediation.lower()

    def test_nonexistent_folder_defaults_to_hint_present(self):
        """The fake ``/repo`` paths used elsewhere in this file have no real
        backing folder — the hint must still fire safely (no crash) rather
        than assume supporting docs exist."""
        finding = _run(_context(_body_of_bytes(20_000)))[0]
        assert "no supporting documents" in finding.remediation.lower()


class TestShrinkingIsNeverPenalised:
    """An oversized plan must always be refactorable downwards."""

    def test_shrinking_edit_is_silent_even_over_block_tier(self):
        before = _body_of_bytes(60_000)
        after = _body_of_bytes(40_000)
        assert len(after) < len(before)
        assert _run(_context(after, content_before=before)) == []

    def test_growing_edit_over_block_tier_still_blocks(self):
        before = _body_of_bytes(36_000)
        after = _body_of_bytes(40_000)
        assert _run(_context(after, content_before=before))[0].level is Level.BLOCK

    def test_creation_has_no_before_and_is_still_checked(self):
        assert _run(_context(_body_of_bytes(40_000), content_before=None))[0].level is Level.BLOCK

    def test_same_size_edit_on_an_oversized_plan_advises_but_does_not_block(self):
        """Ticking a checkbox is a same-size edit — blocking it traps the agent.

        The check exists to stop plans GROWING into logs. An edit that does not
        grow the file makes nothing worse, so it still advises (the size stays
        visible) but must never deny.
        """
        before = _body_of_bytes(40_000)
        after = before.replace("# Plan 00190: Thing", "# Plan 00190: Thing!", 1)
        after = after[: len(before)]
        assert len(after) == len(before)
        findings = _run(_context(after, content_before=before))
        assert len(findings) == 1
        assert findings[0].level is Level.ADVISE

    def test_growth_that_stays_oversized_still_blocks(self):
        before = _body_of_bytes(40_000)
        after = _body_of_bytes(44_000)
        assert _run(_context(after, content_before=before))[0].level is Level.BLOCK


class TestEscapeHatch:
    MARKER = "<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: tracks a 12-subsystem migration -->\n"

    def test_marker_downgrades_block_to_advise(self):
        content = self.MARKER + _body_of_bytes(40_000)
        findings = _run(_context(content))
        assert len(findings) == 1
        assert findings[0].level is Level.ADVISE

    def test_marker_without_a_reason_does_not_count(self):
        content = "<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: -->\n" + _body_of_bytes(40_000)
        assert _run(_context(content))[0].level is Level.BLOCK


class TestGrandfathering:
    def test_legacy_plan_only_advises(self):
        findings = _run(_context(_body_of_bytes(40_000), legacy=frozenset({190})))
        assert findings[0].level is Level.ADVISE


class TestScope:
    """The size rule applies to PLAN.md only — never to journals or the index."""

    @pytest.mark.parametrize(
        "rel_path",
        [
            "CLAUDE/Plan/00190-thing/JOURNAL/00190-Journal-26-07-31.md",
            "CLAUDE/Plan/00190-thing/JOURNAL/notes.md",
            "CLAUDE/Plan/00190-thing/JOURNAL/PLAN.md",
            "CLAUDE/Plan/README.md",
            "CLAUDE/Plan/00190-thing/RESEARCH.md",
            "docs/PLAN.md",
        ],
    )
    def test_exempt_paths(self, rel_path):
        assert _run(_context(_body_of_bytes(60_000), rel_path=rel_path)) == []

    def test_journal_is_exempt_at_any_size(self):
        huge = _body_of_bytes(500_000)
        journal = "CLAUDE/Plan/00190-thing/JOURNAL/00190-Journal-26-07-31.md"
        assert _run(_context(huge, rel_path=journal)) == []


class TestDisabled:
    def test_disabled_emits_nothing(self):
        limits = PlanDocSizeLimits(enabled=False)
        assert _run(_context(_body_of_bytes(60_000), limits=limits)) == []


class TestSpec:
    def test_registered_in_catalogue(self):
        from claude_code_hooks_daemon.plan_qa.checks import all_checks

        assert any(spec.check_id == CHECK_ID for spec in all_checks())

    def test_nominal_level_is_advise(self):
        """Ships advise-first; only the top tier blocks."""
        assert CHECK.level is Level.ADVISE
