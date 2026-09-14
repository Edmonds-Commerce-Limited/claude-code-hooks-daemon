"""Scrubbing a diagnostic report of the client's identity (Plan 00403 Phase 1).

Every route to a hooks-daemon bug report assembled the client's own config,
environment and absolute paths and then pointed the reporter at a PUBLIC issue
tracker. This module is the layer that makes those artefacts publishable, and
two of its rules are the interesting ones.

``daemon paths survive, client paths do not``
    `.claude/hooks-daemon/…` and `src/claude_code_hooks_daemon/…` ARE the
    substance of a daemon bug report. Scrubbing rewrites the project root that
    PREFIXES them, so the part we need stays readable and the part that
    identifies the client does not.

``a short value is never scrubbed``
    Replacing every occurrence of a two-character hostname would shred the
    report into placeholders. The guard is what keeps this safe to apply to a
    whole document rather than to hand-picked fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.report_scrubbing import (
    HOME_PLACEHOLDER,
    HOSTNAME_PLACEHOLDER,
    MIN_SCRUBBABLE_LENGTH,
    PROJECT_ROOT_PLACEHOLDER,
    REMOTE_PLACEHOLDER,
    scrub_report,
)


class TestTheProjectRoot:
    def test_the_project_root_becomes_a_placeholder(self) -> None:
        text = "failed at /home/jbloggs/acme-payments/src/thing.py"

        scrubbed = scrub_report(text, project_root=Path("/home/jbloggs/acme-payments"))

        assert "acme-payments" not in scrubbed
        assert PROJECT_ROOT_PLACEHOLDER in scrubbed

    def test_the_path_below_the_root_is_preserved(self) -> None:
        """The relative part is the diagnostic content; only the prefix identifies."""
        text = "/home/jbloggs/acme-payments/src/thing.py"

        scrubbed = scrub_report(text, project_root=Path("/home/jbloggs/acme-payments"))

        assert scrubbed.endswith("/src/thing.py")

    def test_a_daemon_path_survives_scrubbing(self) -> None:
        """A daemon bug report that lost its daemon paths would be unusable."""
        text = "/home/jbloggs/acme/.claude/hooks-daemon/bin/hooks-daemon status"

        scrubbed = scrub_report(text, project_root=Path("/home/jbloggs/acme"))

        assert ".claude/hooks-daemon/bin/hooks-daemon" in scrubbed

    def test_every_occurrence_is_replaced_not_just_the_first(self) -> None:
        root = Path("/home/jbloggs/acme")
        text = f"{root}/a.py and {root}/b.py and {root}/c.py"

        scrubbed = scrub_report(text, project_root=root)

        assert "jbloggs" not in scrubbed
        assert scrubbed.count(PROJECT_ROOT_PLACEHOLDER) == 3


class TestTheHomeDirectory:
    def test_home_becomes_a_placeholder(self) -> None:
        text = "venv at /home/jbloggs/.venvs/daemon"

        scrubbed = scrub_report(text, project_root=Path("/srv/app"), home=Path("/home/jbloggs"))

        assert "jbloggs" not in scrubbed
        assert HOME_PLACEHOLDER in scrubbed

    def test_the_project_root_wins_when_it_sits_inside_home(self) -> None:
        """The more specific prefix must be applied first, or it never matches.

        With `$HOME` scrubbed first, `/home/j/acme/x.py` becomes
        `<home>/acme/x.py` — and the project-root rule, which is looking for
        the literal `/home/j/acme`, then finds nothing and leaves the project
        name exposed.
        """
        text = "/home/jbloggs/acme-payments/src/thing.py"

        scrubbed = scrub_report(
            text,
            project_root=Path("/home/jbloggs/acme-payments"),
            home=Path("/home/jbloggs"),
        )

        assert "acme-payments" not in scrubbed
        assert scrubbed.startswith(PROJECT_ROOT_PLACEHOLDER)


class TestTheHostAndRemote:
    def test_the_hostname_becomes_a_placeholder(self) -> None:
        text = "HOSTNAME=acme-build-runner-07"

        scrubbed = scrub_report(
            text, project_root=Path("/srv/app"), hostname="acme-build-runner-07"
        )

        assert "acme-build-runner-07" not in scrubbed
        assert HOSTNAME_PLACEHOLDER in scrubbed

    def test_the_git_remote_becomes_a_placeholder(self) -> None:
        """A remote URL names the client, and often a private host."""
        text = "origin  git@git.acme-internal.example:payments/core.git (fetch)"

        scrubbed = scrub_report(
            text,
            project_root=Path("/srv/app"),
            git_remote="git@git.acme-internal.example:payments/core.git",
        )

        assert "acme-internal" not in scrubbed
        assert REMOTE_PLACEHOLDER in scrubbed


class TestTheShortValueGuard:
    def test_a_short_hostname_is_left_alone(self) -> None:
        """Replacing every 'ci' in the document would shred it into placeholders."""
        text = "the ci pipeline runs in a container with cilium networking"

        scrubbed = scrub_report(text, project_root=Path("/srv/app"), hostname="ci")

        assert scrubbed == text

    def test_the_boundary_value_is_scrubbed(self) -> None:
        """A guard nobody can locate exactly is a guard nobody can reason about."""
        host = "h" * MIN_SCRUBBABLE_LENGTH

        scrubbed = scrub_report(f"host={host}", project_root=Path("/srv/app"), hostname=host)

        assert HOSTNAME_PLACEHOLDER in scrubbed

    def test_one_below_the_boundary_is_not(self) -> None:
        host = "h" * (MIN_SCRUBBABLE_LENGTH - 1)

        scrubbed = scrub_report(f"host={host}", project_root=Path("/srv/app"), hostname=host)

        assert HOSTNAME_PLACEHOLDER not in scrubbed


class TestSecretTerms:
    def test_a_declared_secret_term_is_redacted(self) -> None:
        text = "the failure mentions Volcano twice"

        scrubbed = scrub_report(text, project_root=Path("/srv/app"), secret_terms=("Volcano",))

        assert "Volcano" not in scrubbed

    def test_secret_terms_are_applied_even_with_nothing_else_to_scrub(self) -> None:
        """The secret list is the one layer that must never be conditional."""
        scrubbed = scrub_report("Volcano", project_root=Path("/srv/app"), secret_terms=("Volcano",))

        assert "Volcano" not in scrubbed


class TestItIsSafeToApplyToAnything:
    def test_empty_text_is_returned_unchanged(self) -> None:
        assert scrub_report("", project_root=Path("/srv/app")) == ""

    def test_text_with_nothing_to_scrub_is_untouched(self) -> None:
        text = "daemon started successfully"

        assert scrub_report(text, project_root=Path("/srv/app")) == text

    @pytest.mark.parametrize("value", ["", None])
    def test_an_absent_optional_value_is_skipped(self, value: str | None) -> None:
        """An empty hostname must not turn every empty string into a placeholder."""
        text = "daemon started"

        assert scrub_report(text, project_root=Path("/srv/app"), hostname=value) == text
