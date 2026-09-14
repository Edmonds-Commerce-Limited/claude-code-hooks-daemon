"""Where an upstream report is filed, named in exactly one place.

Plan 00403. Found by running the finished generator rather than by a test: the
command it printed was

    gh issue create --body-file untracked/scratch/smoke-report.md

with no `--repo`. In a CLIENT project — the only place the generator matters —
`gh` resolves the target from the working directory, so that command files a
hooks-daemon defect on the CLIENT'S OWN tracker. It also means the filing gate
never engages, because the gate judges the repository a command targets and
that command targets somebody else's.

Two surfaces have to agree about which repository that is: the CLI prints a
command, and `issue_filing_gate` decides whether a command points at us. If
they disagreed, the printed command would be the one the gate refuses — a gate
that blocks the remedy it recommends, which is the failure
`reference_repo_freshness` had to be designed around. So both read the slug
from here.
"""

from __future__ import annotations

from claude_code_hooks_daemon.issue_report.upstream import (
    UPSTREAM_REPO_SLUG,
    filing_command,
)


class TestTheSlug:
    def test_it_names_this_repository(self) -> None:
        assert UPSTREAM_REPO_SLUG == "edmonds-commerce-limited/claude-code-hooks-daemon"

    def test_it_is_lowercase_so_comparisons_can_normalise_to_it(self) -> None:
        assert UPSTREAM_REPO_SLUG == UPSTREAM_REPO_SLUG.lower()


class TestTheFilingCommand:
    def test_it_names_the_repository_explicitly(self) -> None:
        """Without `--repo`, `gh` files against the client's own tracker."""
        command = filing_command("untracked/issue-reports/report.md")

        assert "--repo" in command
        assert UPSTREAM_REPO_SLUG in command.lower()

    def test_it_names_the_report_it_was_given(self) -> None:
        command = filing_command("untracked/issue-reports/report.md")

        assert "--body-file untracked/issue-reports/report.md" in command

    def test_it_starts_with_gh_issue_create(self) -> None:
        """The gate anchors on that head; a different spelling would not engage."""
        assert filing_command("x.md").startswith("gh issue create ")


class TestTheGateAcceptsWhatTheCliPrints:
    def test_the_printed_command_is_one_the_filing_gate_judges(self) -> None:
        """The two surfaces must agree, or the remedy is itself refused."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.issue_filing_gate import (
            IssueFilingGateHandler,
        )

        handler = IssueFilingGateHandler()
        handler.self_install_reader = lambda: False

        assert handler.matches(
            {
                "tool_name": "Bash",
                "tool_input": {"command": filing_command("untracked/issue-reports/report.md")},
            }
        )
