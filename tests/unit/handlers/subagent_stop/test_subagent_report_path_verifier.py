"""SubagentReportPathVerifierHandler — a claimed report path must exist.

Ledger 00422 N15: a subagent's final message ended `Report written to:` and a
path that was well-formed, matched the convention exactly, and named a file
nobody ever created. The coordinator cannot detect that by inspecting what it
received, because what it received looks right — so, exactly as
``subagent_report_size_blocker`` argued for its own case, the check runs on
the SUBAGENT side at the moment it stops.

**The risk here is false positives, not false negatives.** This handler blocks
a stop. A final message that merely MENTIONS a path — one the agent read, one
it recommends the coordinator create, one quoted inside a fence — must sail
through untouched. `TestAMentionIsNotAClaim` is that control, and it is the
half of this file that decides whether the handler is safe to ship: the
positive cases below are satisfied just as well by a guard that blocks
everything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_report_path_verifier import (
    SubagentReportPathVerifierHandler,
    written_path_claims,
)


def _hook_input(message: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "SubagentStop",
        "last_assistant_message": message,
        "stop_hook_active": False,
    }
    payload.update(overrides)
    return payload


class TestAWrittenClaimIsExtracted:
    """The shapes an agent actually uses to say it wrote a file."""

    def test_the_shape_n15_actually_produced(self) -> None:
        message = (
            "Checked 30 live plans.\n\n"
            "Report written to:\n"
            "`CLAUDE/Plan/00441-the-two-link-resolvers-agree/subagent-reports/"
            "260918-scout-sonnet.md`"
        )
        assert written_path_claims(message) == [
            "CLAUDE/Plan/00441-the-two-link-resolvers-agree/subagent-reports/260918-scout-sonnet.md"
        ]

    def test_an_inline_written_to_claim(self) -> None:
        message = "Done. Full findings written to `untracked/agent-reports/260918-a-b.md`."
        assert written_path_claims(message) == ["untracked/agent-reports/260918-a-b.md"]

    def test_wrote_is_a_claim_too(self) -> None:
        message = "I wrote `untracked/agent-reports/x.md` with the detail."
        assert written_path_claims(message) == ["untracked/agent-reports/x.md"]

    def test_an_absolute_path_is_claimed_as_written(self) -> None:
        message = "Report saved to `/workspace/untracked/agent-reports/y.md`"
        assert written_path_claims(message) == ["/workspace/untracked/agent-reports/y.md"]

    def test_the_same_path_claimed_twice_is_reported_once(self) -> None:
        message = "Written to `untracked/agent-reports/z.md`. Report written to `untracked/agent-reports/z.md`."
        assert written_path_claims(message) == ["untracked/agent-reports/z.md"]


class TestAMentionIsNotAClaim:
    """The control. Every one of these must extract NOTHING.

    A guard that blocked on any path in a final message would fire on most
    honest reports, which cite the files they examined. That is worse than
    the defect it replaces: N15 cost one re-derivation by hand, whereas a
    guard that cannot be satisfied costs every dispatch after it.
    """

    def test_a_path_the_agent_read(self) -> None:
        assert written_path_claims("I read `CLAUDE/Plan/README.md` to get the count.") == []

    def test_a_path_it_recommends_creating(self) -> None:
        message = "You should write `untracked/agent-reports/260918-x.md` next."
        assert written_path_claims(message) == []

    def test_a_bare_path_with_no_verb(self) -> None:
        assert written_path_claims("Candidates: `CLAUDE/Plan/00422-.../PLAN.md`") == []

    def test_a_path_inside_a_fenced_block(self) -> None:
        message = "Run this:\n\n```bash\ncat untracked/agent-reports/x.md\n```\n"
        assert written_path_claims(message) == []

    def test_a_plain_summary_with_no_paths(self) -> None:
        assert written_path_claims("Checked 29 live plans. No duplicates found.") == []

    def test_an_empty_message(self) -> None:
        assert written_path_claims("") == []


class TestTheHandlerBlocksOnlyAMissingClaim:
    def test_a_claim_whose_file_exists_is_allowed(self, tmp_path: Path) -> None:
        report = tmp_path / "report.md"
        report.write_text("findings", encoding="utf-8")
        handler = SubagentReportPathVerifierHandler()
        handler._project_root = tmp_path
        result = handler.handle(_hook_input(f"Report written to `{report.name}`"))
        assert result.decision == Decision.ALLOW

    def test_a_claim_whose_file_is_absent_is_denied_and_names_it(self, tmp_path: Path) -> None:
        handler = SubagentReportPathVerifierHandler()
        handler._project_root = tmp_path
        result = handler.handle(_hook_input("Report written to `missing-report.md`"))
        assert result.decision == Decision.DENY
        assert "missing-report.md" in (result.reason or "")

    def test_the_deny_offers_dropping_the_claim_as_well_as_writing_it(self, tmp_path: Path) -> None:
        """An agent that genuinely reported inline is not at fault.

        Left with only "write the file", the cheapest way past this guard
        would be to invent one — which is a worse outcome than the claim it
        replaces, because an invented file looks like evidence.
        """
        handler = SubagentReportPathVerifierHandler()
        handler._project_root = tmp_path
        reason = (
            handler.handle(_hook_input("Report written to `missing.md`")).reason or ""
        ).lower()
        assert "without claiming a path" in reason
        assert "invented report" in reason

    def test_a_message_with_no_claim_is_allowed(self, tmp_path: Path) -> None:
        handler = SubagentReportPathVerifierHandler()
        handler._project_root = tmp_path
        result = handler.handle(_hook_input("Checked 29 live plans. No duplicates."))
        assert result.decision == Decision.ALLOW

    def test_a_path_outside_the_project_is_not_judged(self, tmp_path: Path) -> None:
        """Not this repository's business, and not reliably checkable."""
        handler = SubagentReportPathVerifierHandler()
        handler._project_root = tmp_path
        result = handler.handle(_hook_input("Report written to `/etc/nope-report.md`"))
        assert result.decision == Decision.ALLOW


class TestTheHandlerFailsOpen:
    def test_a_missing_message_allows(self, tmp_path: Path) -> None:
        handler = SubagentReportPathVerifierHandler()
        handler._project_root = tmp_path
        payload = _hook_input("dummy")
        del payload["last_assistant_message"]
        assert handler.handle(payload).decision == Decision.ALLOW

    def test_a_non_string_message_allows(self, tmp_path: Path) -> None:
        handler = SubagentReportPathVerifierHandler()
        handler._project_root = tmp_path
        assert (
            handler.handle(_hook_input("x", last_assistant_message=42)).decision == Decision.ALLOW
        )

    def test_a_re_entry_does_not_match(self) -> None:
        """A subagent that complied after one block must not be looped."""
        handler = SubagentReportPathVerifierHandler()
        assert handler.matches(_hook_input("x", stop_hook_active=True)) is False

    def test_an_ordinary_stop_matches(self) -> None:
        handler = SubagentReportPathVerifierHandler()
        assert handler.matches(_hook_input("x")) is True
