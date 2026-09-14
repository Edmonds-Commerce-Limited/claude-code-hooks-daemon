"""The last backstop: a declared block-word never reaches a public issue.

Plan 00403. Every other protection in this package works by NOT COLLECTING
things — the hostname, the git remote, the config file, the logs. That design
cannot reach the one part a reporter types themselves, and free text is exactly
where somebody pastes the internal hostname because it seemed load-bearing to
the explanation.

Two decisions here differ from what the rest of the daemon does with those
terms, and both are deliberate.

``refused, not redacted``
    ``scrub_report`` REPLACES a term with a placeholder, which is right for a
    local diagnostic nobody has read. A report is different: the reporter is
    still at the keyboard, the sentence containing the term is theirs to
    rewrite, and a silently redacted report teaches them nothing while leaving
    prose that now reads as nonsense. Refusing hands the decision back.

``the refusal names an index, never the term``
    Identical to ``sensitive_content``'s rule, for the identical reason: the
    message goes into logs, transcripts and this session's context. "entry 2 of
    5" is meaningless without the gitignored file, and that is the point.
"""

from __future__ import annotations

from claude_code_hooks_daemon.issue_report.assemble import (
    ConfigConsideration,
    ReportFields,
    assemble_report,
)
from claude_code_hooks_daemon.issue_report.block_words import (
    describe_blocked_term,
    first_blocked_term_problem,
)

_TERMS = ("acmecorp", "internal.example.corp", "widgetco")


def _fields(
    *,
    summary: str = "sed_blocker denies a command with no sed in it",
    expected: str = "The fourth exemption should apply.",
    observed: str = "It is denied anyway.",
    reproduction: str = "1. echo x > untracked/scratch/probe.txt\n2. Run the command",
    option: str = "sed_blocker.extra_whitelist",
    why: str = "It whitelists a pipe producer, and there is no pipe stage here.",
    handler: str | None = "sed_blocker",
    citation: str | None = "src/claude_code_hooks_daemon/x.py:1",
) -> ReportFields:
    return ReportFields(
        summary=summary,
        expected=expected,
        observed=observed,
        reproduction=reproduction,
        daemon_version="3.64.0",
        generated_at="2026-09-14",
        platform="Linux x86_64, Python 3.12.4",
        install_mode="normal",
        config_considered=(ConfigConsideration(option=option, why_insufficient=why),),
        handler=handler,
        source_citation=citation,
    )


class TestTheRefusalNamesAnIndexOnly:
    def test_it_states_which_entry_matched(self) -> None:
        detail = describe_blocked_term(2, len(_TERMS))

        assert "entry 2 of 3" in detail

    def test_it_never_carries_the_term(self) -> None:
        """The message reaches logs, transcripts and this session's context."""
        detail = describe_blocked_term(1, len(_TERMS))

        for term in _TERMS:
            assert term not in detail

    def test_it_says_what_to_do_instead(self) -> None:
        """A refusal that does not say how to proceed gets worked around."""
        detail = describe_blocked_term(1, len(_TERMS))

        assert "rewrite" in detail.lower()


class TestWhichFieldsAreScanned:
    def test_a_term_in_the_summary_is_found(self) -> None:
        assert first_blocked_term_problem(_fields(summary="acmecorp sees a denial"), _TERMS)

    def test_a_term_in_the_expectation_is_found(self) -> None:
        assert first_blocked_term_problem(_fields(expected="acmecorp docs say otherwise"), _TERMS)

    def test_a_term_in_the_observation_is_found(self) -> None:
        assert first_blocked_term_problem(_fields(observed="It printed acmecorp"), _TERMS)

    def test_a_term_in_the_reproduction_is_found(self) -> None:
        assert first_blocked_term_problem(_fields(reproduction="1. cd acmecorp\n2. run it"), _TERMS)

    def test_a_term_in_a_config_reason_is_found(self) -> None:
        """This field is prose too, and it is the one people forget."""
        assert first_blocked_term_problem(
            _fields(why="acmecorp sets it in their own overlay"), _TERMS
        )

    def test_a_term_in_the_option_name_is_found(self) -> None:
        assert first_blocked_term_problem(_fields(option="acmecorp_custom_handler"), _TERMS)

    def test_a_term_in_the_handler_name_is_found(self) -> None:
        assert first_blocked_term_problem(_fields(handler="acmecorp_guard"), _TERMS)

    def test_a_term_in_the_citation_is_found(self) -> None:
        assert first_blocked_term_problem(_fields(citation="src/acmecorp/x.py:1"), _TERMS)

    def test_clean_fields_produce_nothing(self) -> None:
        assert first_blocked_term_problem(_fields(), _TERMS) is None

    def test_no_declared_terms_means_the_check_is_inert(self) -> None:
        """A project with no list gets silence, not an error."""
        assert first_blocked_term_problem(_fields(summary="acmecorp"), ()) is None


class TestAssemblyRefuses:
    def test_a_report_carrying_a_term_is_refused(self) -> None:
        result = assemble_report(_fields(observed="It printed acmecorp"), blocked_terms=_TERMS)

        assert result.problems

    def test_the_refused_report_leaves_no_document(self) -> None:
        """A file that exists is a file that can be filed by mistake."""
        result = assemble_report(_fields(observed="It printed acmecorp"), blocked_terms=_TERMS)

        assert result.document == ""

    def test_neither_the_problems_nor_the_document_carry_the_term(self) -> None:
        result = assemble_report(_fields(observed="It printed acmecorp"), blocked_terms=_TERMS)

        rendered = " ".join(problem.reason for problem in result.problems) + result.document

        assert "acmecorp" not in rendered

    def test_a_clean_report_still_assembles(self) -> None:
        result = assemble_report(_fields(), blocked_terms=_TERMS)

        assert not result.problems
        assert result.document

    def test_the_default_is_no_terms_so_existing_callers_are_unchanged(self) -> None:
        result = assemble_report(_fields(observed="It printed acmecorp"))

        assert not result.problems
