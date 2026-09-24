"""The filing gate over `gh issue create` against the daemon's own tracker.

Plan 00403 Phase 4. Everything upstream of this is advice — a generator that
refuses to build a leaky report is worth nothing if the reporter can type the
body by hand instead. This is the only place in the plan where a rule is
ENFORCED rather than documented.

Three properties carry the design, and each has tests that would fail loudly if
it were traded away:

``it stands down in the daemon's own repository``
    `issue-sdlc` files and edits issues here every hour. A gate that fires in
    self-install would break the project's own delivery loop on its first tick,
    which is a far more likely outcome than the leak it is guarding against.

``it must not touch a client filing on their OWN tracker``
    The overwhelmingly common `gh issue create` in any client project has
    nothing to do with this daemon. The gate engages on the repository a command
    TARGETS, never on the slug appearing somewhere in its text — a client filing
    "upgrade Edmonds-Commerce-Limited/claude-code-hooks-daemon to 3.64" against
    their own backlog is the exact false positive that would get the handler
    switched off.

``an unresolvable install mode fails CLOSED``
    The failure it guards is unretractable, and the cost of being wrong the
    other way is one round trip. So "I could not tell whether this is the daemon
    repo" is answered as "assume it is a client", which leaves the gate ON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.issue_filing_gate import (
    IssueFilingGateHandler,
)
from claude_code_hooks_daemon.issue_report.provenance import (
    GENERATOR_COMMAND,
    render_document,
)
from claude_code_hooks_daemon.utils.git_repo import run_git

_UPSTREAM = "Edmonds-Commerce-Limited/claude-code-hooks-daemon"
_CLIENT_REPO = "acme-corp/storefront"


def _handler(*, self_install: bool = False) -> IssueFilingGateHandler:
    handler = IssueFilingGateHandler()
    handler.self_install_reader = lambda: self_install
    return handler


def _git_checkout_with_origin(tmp_path: Path, origin_url: str) -> Path:
    """A real checkout with a real remote, because that is what `gh` reads.

    Mocking the resolver would assert that the handler calls what the test
    thinks it calls; a real `git init` asserts the property that matters -- the
    slug this checkout would actually resolve to.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    run_git(checkout, "init", "--quiet")
    run_git(checkout, "remote", "add", "origin", origin_url)
    return checkout


def _bash(command: str, *, cwd: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "filing-gate",
    }
    if cwd is not None:
        hook_input["cwd"] = cwd
    return hook_input


def _generated(
    tmp_path: Path, body: str = "## Summary\n\nThe gate denies a hand-written body."
) -> Path:
    path = tmp_path / "issue-report.md"
    path.write_text(render_document(body, daemon_version="3.64.0", generated_at="2026-09-14"))
    return path


class TestWhatEngagesTheGate:
    def test_a_create_against_the_upstream_tracker_engages(self) -> None:
        assert _handler().matches(_bash(f"gh issue create --repo {_UPSTREAM} --title x"))

    def test_the_short_repo_flag_engages(self) -> None:
        assert _handler().matches(_bash(f"gh issue create -R {_UPSTREAM} --title x"))

    def test_the_joined_repo_flag_engages(self) -> None:
        assert _handler().matches(_bash(f"gh issue create --repo={_UPSTREAM} --title x"))

    @pytest.mark.parametrize(
        "spelling",
        [
            f"https://github.com/{_UPSTREAM}",
            f"https://github.com/{_UPSTREAM}.git",
            f"git@github.com:{_UPSTREAM}.git",
            f"ssh://git@github.com/{_UPSTREAM}.git",
            f"github.com/{_UPSTREAM}",
        ],
    )
    def test_every_url_spelling_of_the_same_repo_engages(self, spelling: str) -> None:
        """`gh` accepts all of these for `--repo`, so all of them target us."""
        assert _handler().matches(_bash(f"gh issue create --repo {spelling} --title x"))

    def test_the_environment_variable_form_engages(self) -> None:
        """`GH_REPO` selects the target without a flag, and gh honours it."""
        assert _handler().matches(_bash(f"GH_REPO={_UPSTREAM} gh issue create --title x"))

    def test_a_path_qualified_gh_engages(self) -> None:
        assert _handler().matches(_bash(f"/usr/bin/gh issue create --repo {_UPSTREAM} --title x"))

    def test_a_line_continuation_does_not_hide_it(self) -> None:
        assert _handler().matches(_bash(f"gh issue create \\\n  --repo {_UPSTREAM} --title x"))

    def test_a_later_segment_of_a_chain_engages(self) -> None:
        assert _handler().matches(
            _bash(f"pytest tests/ && gh issue create --repo {_UPSTREAM} --title x")
        )


class TestWhatTheGateLeavesAlone:
    def test_a_client_filing_on_their_own_tracker_is_not_touched(self) -> None:
        assert not _handler().matches(_bash(f"gh issue create --repo {_CLIENT_REPO} --title x"))

    def test_a_create_with_no_repo_at_all_is_not_touched(self) -> None:
        """A bare create targets whatever repo the cwd is in — theirs."""
        assert not _handler().matches(_bash("gh issue create --title x --body y"))

    def test_a_bare_create_from_a_client_checkout_is_not_touched(self, tmp_path: Path) -> None:
        """Resolving the cwd must not start gating a client's own tracker."""
        checkout = _git_checkout_with_origin(tmp_path, f"git@github.com:{_CLIENT_REPO}.git")

        assert not _handler().matches(
            _bash("gh issue create --title x --body y", cwd=str(checkout))
        )


class TestTheCwdIsAThirdWayToNameARepository:
    """`gh` resolves the base repo from the cwd's remotes when no flag says.

    That is `gh`'s DEFAULT, and the gate answered only `--repo` and `GH_REPO`.
    It matters because every client install carries a clone of THIS repository
    under `.claude/hooks-daemon/`: a bare `gh issue create` with the shell
    sitting in that clone files a hand-written body against a PUBLIC tracker,
    and the gate never engaged. That is an accident rather than an evasion,
    which is precisely the class this handler exists to catch.
    """

    def test_a_bare_create_from_inside_the_vendored_clone_is_gated(self, tmp_path: Path) -> None:
        clone = _git_checkout_with_origin(tmp_path, f"git@github.com:{_UPSTREAM}.git")

        assert _handler().matches(_bash("gh issue create --title x --body y", cwd=str(clone)))

    def test_an_https_remote_resolves_the_same_way(self, tmp_path: Path) -> None:
        clone = _git_checkout_with_origin(tmp_path, f"https://github.com/{_UPSTREAM}.git")

        assert _handler().matches(_bash("gh issue create --title x --body y", cwd=str(clone)))

    def test_an_explicit_repo_flag_still_wins_over_the_cwd(self, tmp_path: Path) -> None:
        """`gh`'s own precedence: the flag decides when it is present."""
        clone = _git_checkout_with_origin(tmp_path, f"git@github.com:{_UPSTREAM}.git")

        assert not _handler().matches(
            _bash(f"gh issue create --repo {_CLIENT_REPO} --title x", cwd=str(clone))
        )

    def test_merely_naming_us_in_the_title_is_not_targeting_us(self) -> None:
        """The false positive that would get this handler switched off."""
        assert not _handler().matches(
            _bash(f'gh issue create --repo {_CLIENT_REPO} --title "upgrade {_UPSTREAM} to 3.64"')
        )

    def test_reading_our_tracker_is_not_touched(self) -> None:
        assert not _handler().matches(_bash(f"gh issue list --repo {_UPSTREAM}"))

    def test_viewing_one_of_our_issues_is_not_touched(self) -> None:
        assert not _handler().matches(_bash(f"gh issue view 12 --repo {_UPSTREAM} --comments"))

    def test_commenting_is_not_touched(self) -> None:
        """Deliberately out of scope: no generator produces a COMMENT body.

        Requiring provenance on a follow-up comment would make the tracker
        unusable for the very reporter this plan is trying to help, and the
        secret-term scan in `sensitive_content` already covers a comment body.
        """
        assert not _handler().matches(_bash(f"gh issue comment 12 --repo {_UPSTREAM} --body hi"))

    def test_a_non_bash_tool_is_not_touched(self) -> None:
        assert not _handler().matches(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": "/x"},
            }
        )

    def test_a_bash_call_with_no_command_is_not_touched(self) -> None:
        assert not _handler().matches(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {}}
        )


class TestSelfInstall:
    def test_the_gate_stands_down_in_the_daemon_repo(self) -> None:
        """`issue-sdlc` runs here hourly; a gate that fired would break it."""
        assert not _handler(self_install=True).matches(
            _bash(f"gh issue create --repo {_UPSTREAM} --title x")
        )

    def test_an_unresolvable_install_mode_leaves_the_gate_on(self) -> None:
        """Fails CLOSED: the leak it guards cannot be retracted."""
        handler = IssueFilingGateHandler()

        def _raise() -> bool:
            raise RuntimeError("ProjectContext not initialized")

        handler.self_install_reader = _raise

        assert handler.matches(_bash(f"gh issue create --repo {_UPSTREAM} --title x"))


class TestABodyTheGeneratorProduced:
    def test_it_is_allowed(self, tmp_path: Path) -> None:
        path = _generated(tmp_path)

        result = _handler().handle(
            _bash(f"gh issue create --repo {_UPSTREAM} --title x --body-file {path}")
        )

        assert result.decision == Decision.ALLOW

    def test_the_short_flag_is_allowed(self, tmp_path: Path) -> None:
        path = _generated(tmp_path)

        result = _handler().handle(_bash(f"gh issue create -R {_UPSTREAM} -F {path}"))

        assert result.decision == Decision.ALLOW

    def test_the_joined_flag_is_allowed(self, tmp_path: Path) -> None:
        path = _generated(tmp_path)

        result = _handler().handle(_bash(f"gh issue create --repo {_UPSTREAM} --body-file={path}"))

        assert result.decision == Decision.ALLOW

    def test_a_quoted_path_with_a_space_is_allowed(self, tmp_path: Path) -> None:
        """`str.split()` would cut this path in half and find no report at all."""
        directory = tmp_path / "my reports"
        directory.mkdir()
        path = _generated(directory)

        result = _handler().handle(
            _bash(f'gh issue create --repo {_UPSTREAM} --body-file "{path}"')
        )

        assert result.decision == Decision.ALLOW

    def test_a_relative_path_resolves_against_the_call_cwd(self, tmp_path: Path) -> None:
        _generated(tmp_path)

        result = _handler().handle(
            _bash(
                f"gh issue create --repo {_UPSTREAM} --body-file issue-report.md",
                cwd=str(tmp_path),
            )
        )

        assert result.decision == Decision.ALLOW


class TestTheBrowserFallback:
    """`--web` is ALLOWED, and that is a deliberate hole in the gate.

    It opens GitHub's own issue forms in a browser — the one place the redaction
    rule is stated to a human, and the defect form cannot be submitted without
    ticking two acknowledgements. Nothing reaches the tracker until a person has
    read them and clicked, so the human is in the loop by construction.

    Denying it would leave someone who genuinely cannot run the generator — a
    defect that stops the CLI, a machine without the install — with no route at
    all except working around the gate. A gate whose only escape is evasion
    teaches evasion.
    """

    def test_it_is_allowed(self) -> None:
        result = _handler().handle(_bash(f"gh issue create --repo {_UPSTREAM} --web"))

        assert result.decision == Decision.ALLOW

    def test_it_is_allowed_alongside_a_title(self) -> None:
        result = _handler().handle(
            _bash(f'gh issue create --repo {_UPSTREAM} --web --title "sed_blocker denies"')
        )

        assert result.decision == Decision.ALLOW

    def test_the_deny_message_names_it_so_the_fallback_is_discoverable(self) -> None:
        """A refusal that hides the legitimate alternative gets worked around."""
        result = _handler().handle(_bash(f"gh issue create --repo {_UPSTREAM} --title x"))

        assert "--web" in str(result.reason)


class TestABodyItDidNot:
    def test_an_inline_body_is_denied(self) -> None:
        result = _handler().handle(
            _bash(f'gh issue create --repo {_UPSTREAM} --title x --body "it crashed"')
        )

        assert result.decision == Decision.DENY

    def test_a_create_with_no_body_at_all_is_denied(self) -> None:
        """An editor-composed body is a hand-written body arriving by another route."""
        result = _handler().handle(_bash(f"gh issue create --repo {_UPSTREAM} --title x"))

        assert result.decision == Decision.DENY

    def test_a_hand_written_file_is_denied(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.md"
        path.write_text("The daemon broke. Here is my whole config:\n\ndaemon:\n  secret: x\n")

        result = _handler().handle(_bash(f"gh issue create --repo {_UPSTREAM} --body-file {path}"))

        assert result.decision == Decision.DENY
        assert GENERATOR_COMMAND in str(result.reason)

    def test_an_edited_generated_report_is_denied(self, tmp_path: Path) -> None:
        """The failure that actually happens: generate clean, then paste a log in."""
        path = _generated(tmp_path)
        path.write_text(path.read_text() + "\n\nAlso, here is the log:\n\n    /home/jo/secret\n")

        result = _handler().handle(_bash(f"gh issue create --repo {_UPSTREAM} --body-file {path}"))

        assert result.decision == Decision.DENY
        assert "changed since it was generated" in str(result.reason)

    def test_a_body_on_stdin_is_denied(self) -> None:
        """`-F -` cannot be judged before the fact, so it cannot be allowed."""
        result = _handler().handle(
            _bash(f"echo hi | gh issue create --repo {_UPSTREAM} --body-file -")
        )

        assert result.decision == Decision.DENY

    def test_a_missing_file_is_denied(self, tmp_path: Path) -> None:
        result = _handler().handle(
            _bash(f"gh issue create --repo {_UPSTREAM} --body-file {tmp_path}/absent.md")
        )

        assert result.decision == Decision.DENY

    def test_a_nul_byte_in_the_body_file_path_is_denied_not_raised(self, tmp_path: Path) -> None:
        """Plan 00466 N24 follow-up (guard-defects review 2, m3): the fuzzer

        found ``Path.stat()`` raising ``ValueError: embedded null byte`` on
        NUL-bearing paths, uncaught here -- only ``OSError`` was handled.
        """
        result = _handler().handle(
            _bash(f"gh issue create --repo {_UPSTREAM} --body-file {tmp_path}/x\x00y.md")
        )

        assert result.decision == Decision.DENY

    def test_a_second_unverified_body_file_is_not_laundered_by_the_first(
        self, tmp_path: Path
    ) -> None:
        """Every body file named is judged, not just the first that passes."""
        good = _generated(tmp_path)
        bad = tmp_path / "extra.md"
        bad.write_text("whatever I felt like writing")

        result = _handler().handle(
            _bash(
                f"gh issue create --repo {_UPSTREAM} --body-file {good} && "
                f"gh issue create --repo {_UPSTREAM} --body-file {bad}"
            )
        )

        assert result.decision == Decision.DENY


class TestTheDenyMessage:
    def test_it_names_the_command_that_produces_a_valid_body(self) -> None:
        result = _handler().handle(_bash(f"gh issue create --repo {_UPSTREAM} --title x"))

        assert GENERATOR_COMMAND in str(result.reason)

    def test_it_carries_the_rule_id(self) -> None:
        result = _handler().handle(_bash(f"gh issue create --repo {_UPSTREAM} --title x"))

        assert RuleID.UPSTREAM_ISSUE_UNVERIFIED_BODY in str(result.reason)

    def test_it_says_why_a_public_tracker_is_different(self) -> None:
        result = _handler().handle(_bash(f"gh issue create --repo {_UPSTREAM} --title x"))

        assert "public" in str(result.reason).lower()


class TestTheHandlerSelfReports:
    def test_it_declares_its_rule(self) -> None:
        rules = _handler().get_rules()

        assert [rule.rule_id for rule in rules] == [RuleID.UPSTREAM_ISSUE_UNVERIFIED_BODY]

    def test_it_contributes_claude_md_guidance(self) -> None:
        guidance = _handler().get_claude_md()

        assert guidance is not None
        assert GENERATOR_COMMAND in guidance

    def test_it_declares_acceptance_tests(self) -> None:
        assert _handler().get_acceptance_tests()
