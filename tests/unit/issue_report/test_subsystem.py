"""Checking the handler a report names (Plan 00403 Task 3.2).

The task asked to "surface the named handler's options". Half of it is real and
half rests on a premise that does not hold, and the module says which is which
rather than approximating the impossible half.

**Options cannot be enumerated authoritatively.** A handler's options are not
declared in any schema — they are whatever the project's config supplies, read
at registration time. There is no list to print, so this does not invent one;
it points at `hooks-daemon explain-handler <name>`, which IS the authoritative
source.

**The NAME can be checked, and that is the part with teeth.** 127 handler
config keys are machine-readable in `HandlerID`. A report naming a handler that
does not exist is one a maintainer cannot route, and the reporter has almost
certainly been debugging the wrong thing — which is worth catching before it
becomes a public issue rather than after.
"""

from __future__ import annotations

from claude_code_hooks_daemon.issue_report.subsystem import (
    check_handler_name,
    known_handler_keys,
)


class TestARealHandler:
    def test_a_known_config_key_resolves(self) -> None:
        assert check_handler_name("sed_blocker").resolved

    def test_the_display_spelling_also_resolves(self) -> None:
        """A rule ID and the generated docs use the hyphenated form."""
        assert check_handler_name("sed-blocker").resolved

    def test_the_match_ignores_case(self) -> None:
        assert check_handler_name("Sed_Blocker").resolved

    def test_a_recently_added_handler_resolves(self) -> None:
        """Guards against a stale hardcoded list masquerading as a registry."""
        assert check_handler_name("reference_repo_freshness").resolved


class TestAnUnknownHandler:
    def test_it_does_not_resolve(self) -> None:
        assert not check_handler_name("sed_blockker").resolved

    def test_a_near_miss_is_suggested(self) -> None:
        """A typo is the likeliest cause, so the fix should be one line away."""
        verdict = check_handler_name("sed_blockker")

        assert "sed_blocker" in verdict.detail

    def test_an_invented_handler_says_how_to_list_them(self) -> None:
        verdict = check_handler_name("magic_fixer_9000")

        assert "explain-handler" in verdict.detail or "handlers" in verdict.detail


class TestNoHandlerNamed:
    def test_an_absent_name_is_allowed(self) -> None:
        """Not every defect belongs to one handler — the daemon has other parts."""
        assert check_handler_name(None).resolved

    def test_an_empty_name_is_allowed(self) -> None:
        assert check_handler_name("   ").resolved


class TestTheRegistryIsReal:
    def test_it_carries_every_handler_not_a_sample(self) -> None:
        keys = known_handler_keys()

        assert len(keys) > 100, "a short list means the enumeration broke, not that we have few"

    def test_the_keys_are_config_spellings(self) -> None:
        assert "sed_blocker" in known_handler_keys()


class TestOptionsAreNotInvented:
    def test_the_detail_points_at_the_authoritative_source(self) -> None:
        """No option schema exists, so the report must not pretend one does."""
        verdict = check_handler_name("sed_blocker")

        assert "explain-handler" in verdict.detail
