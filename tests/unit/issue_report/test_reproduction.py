"""The minimal synthetic reproduction rule (Plan 00403 Task 2.2).

This is the load-bearing rule of the whole redaction design. Every other field
in an upstream issue report is assembled by the generator from values it
controls; the reproduction is the ONE place a client's own material can enter,
because a human or an agent writes it in free text.

A reproduction authored against invented fixtures under ``untracked/scratch/``
cannot leak, removes most of the remaining surface in a single move, and
independently produces a better issue — a maintainer can run it.

Two boundaries matter and are easy to get backwards:

``daemon paths are ours; client paths are not``
    ``.claude/hooks-daemon/…`` and ``src/claude_code_hooks_daemon/…`` ARE the
    substance of a daemon bug report. A reproduction that could not name the
    handler's source file would be useless. The project root that PREFIXES a
    path is what identifies somebody, which is why an absolute path is refused
    whatever it points at.

``the escape is not an unchecked free-text field``
    A bug that genuinely cannot be reproduced synthetically is still
    reportable, and the report says so explicitly instead of carrying client
    data. So the sentinel waives the requirement to HAVE steps — it does not
    waive the checks on what is written.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.issue_report.reproduction import (
    CANNOT_REPRODUCE_SENTINEL,
    SCRATCH_PREFIX,
    check_reproduction,
)


def _reasons(text: str) -> str:
    return " | ".join(problem.reason for problem in check_reproduction(text))


class TestAGoodReproductionPasses:
    def test_a_scratch_fixture_is_accepted(self) -> None:
        text = (
            "mkdir -p untracked/scratch/repro\n"
            "echo 'x = 1' > untracked/scratch/repro/sample.py\n"
            "Then Write to untracked/scratch/repro/sample.py and expect a DENY."
        )

        assert check_reproduction(text) == ()

    def test_prose_with_no_paths_at_all_is_accepted(self) -> None:
        text = "Run the status line twice in a row; the second render is blank."

        assert check_reproduction(text) == ()

    def test_a_daemon_source_path_is_accepted(self) -> None:
        """A report that could not cite the daemon's own source is unusable."""
        text = "src/claude_code_hooks_daemon/handlers/pre_tool_use/sed_blocker.py:112"

        assert check_reproduction(text) == ()

    def test_a_deployed_daemon_path_is_accepted(self) -> None:
        """This is where the daemon lives in a client install."""
        text = "Run .claude/hooks-daemon/bin/hooks-daemon status"

        assert check_reproduction(text) == ()

    def test_the_client_config_file_may_be_named(self) -> None:
        """Naming the file is how you say which option you changed.

        Its CONTENTS are the client's; its path is the same in every install.
        """
        text = "Set handlers.pre_tool_use.sed_blocker.enabled to false in .claude/hooks-daemon.yaml"

        assert check_reproduction(text) == ()


class TestAClientPathIsRefused:
    def test_an_absolute_path_is_refused(self) -> None:
        """An absolute path carries the project root and usually the username."""
        problems = check_reproduction("Edit /home/jbloggs/acme-payments/src/thing.py")

        assert problems
        assert "jbloggs" not in _reasons("Edit /home/jbloggs/acme-payments/src/thing.py")

    def test_an_absolute_path_is_refused_even_under_a_daemon_directory(self) -> None:
        """The prefix is what identifies, so the suffix cannot redeem it."""
        problems = check_reproduction("/home/jbloggs/acme/.claude/hooks-daemon/bin/hooks-daemon")

        assert problems

    def test_a_home_relative_path_is_refused(self) -> None:
        assert check_reproduction("Check ~/.config/acme/settings.toml")

    def test_a_windows_drive_path_is_refused(self) -> None:
        """Claude Code runs on Windows, and this carries a username identically.

        Found by running the checker over realistic prose rather than over the
        fixtures: every other case in this class is POSIX-shaped, so a
        backslash path sailed through a rule built entirely around `/`.
        """
        assert check_reproduction(r"Edit C:\Users\jbloggs\acme\thing.py then retry")

    def test_a_unc_path_is_refused(self) -> None:
        """A UNC path names a host as surely as a URL does."""
        assert check_reproduction(r"Open \\acme-fs01\payroll\export.csv")

    def test_a_relative_client_path_is_refused(self) -> None:
        """Outside scratch and outside the daemon, a path names the client's code."""
        assert check_reproduction("Open app/Services/PayrollExporter.php and save it")

    def test_the_refusal_says_where_a_reproduction_may_live(self) -> None:
        """A refusal nobody can act on just gets worked around."""
        assert SCRATCH_PREFIX in _reasons("Open app/Services/PayrollExporter.php")


class TestAReproductionIsRequired:
    @pytest.mark.parametrize("text", ["", "   ", "\n\n"])
    def test_an_empty_reproduction_is_refused(self, text: str) -> None:
        assert check_reproduction(text)

    def test_the_refusal_names_the_escape(self) -> None:
        """Refusing without naming the way out invites an invented one."""
        assert CANNOT_REPRODUCE_SENTINEL in _reasons("")


class TestTheCannotReproduceEscape:
    def test_the_sentinel_waives_the_requirement_for_steps(self) -> None:
        text = f"{CANNOT_REPRODUCE_SENTINEL}: only happens after a long session compacts."

        assert check_reproduction(text) == ()

    def test_the_sentinel_does_not_waive_the_path_checks(self) -> None:
        """The escape means 'no steps', not 'unchecked free text'."""
        text = f"{CANNOT_REPRODUCE_SENTINEL}: only fails in /srv/acme-payments/deploy"

        assert check_reproduction(text)

    def test_the_sentinel_buried_mid_text_is_refused_as_ambiguous(self) -> None:
        """The sentinel is a CLAIM a maintainer acts on, so it must be unambiguous.

        Buried mid-sentence there is no way to tell a report asserting "no
        synthetic reproduction exists" from one merely discussing the
        possibility — and a maintainer scanning for the token reads the first
        meaning either way.
        """
        text = "I wondered whether this was a CANNOT-REPRODUCE-SYNTHETICALLY situation"

        assert check_reproduction(text)


class TestUrls:
    def test_an_internal_tracker_url_is_refused(self) -> None:
        """A URL is a path to a machine, and an internal host names the client."""
        assert check_reproduction("See https://jira.acme-internal.example/browse/PAY-1423")

    def test_a_url_to_this_repository_is_accepted(self) -> None:
        text = (
            "Same as https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/12"
        )

        assert check_reproduction(text) == ()


class TestTheCheckIsSafeToRunOnAnything:
    @pytest.mark.parametrize(
        "text",
        [
            "a b c",
            "100/50 is a ratio, not a path",
            "use and/or here",
            "the handler returns allow/deny",
        ],
    )
    def test_ordinary_prose_containing_a_slash_is_not_a_path(self, text: str) -> None:
        """Over-refusing shreds a legitimate reproduction into noise."""
        assert check_reproduction(text) == ()
