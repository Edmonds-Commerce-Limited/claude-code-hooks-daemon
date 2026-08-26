"""Plan 00275: GitHub auto-closing keyword references in git messages.

A commit message containing "Fixes #123" (or any of GitHub's nine closing
keywords followed by an issue reference) auto-closes that issue the moment
the commit reaches the default branch. The behaviour cannot be disabled
repository-side, and agents write these forms accidentally. This handler
denies the commit at source, quoting the matched span and offering the
non-closing rewrites GitHub links but does not close ("Addresses #123",
"Refs #123", "See #123").

Grammar verified against docs.github.com "Linking a pull request to an
issue": keywords close/closes/closed/fix/fixes/fixed/resolve/resolves/
resolved, case-insensitive, optionally followed by a colon, then a
reference — ``#N``, ``owner/repo#N``, ``GH-N``, or a full issue URL.
The keyword ALONE never matches: "fixes the race" is prose.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.github_auto_close_keywords import (
    GithubAutoCloseKeywordsHandler,
)


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestInitialisation:
    def test_identity_and_priority(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.name == HandlerID.GITHUB_AUTO_CLOSE_KEYWORDS.display_name
        assert handler.priority == Priority.GITHUB_AUTO_CLOSE_KEYWORDS
        # Non-terminal on purpose: warn mode returns ALLOW, and a terminal
        # ALLOW would end dispatch and shadow every later handler.
        assert handler.terminal is False


class TestEveryKeywordFormIsDenied:
    @pytest.mark.parametrize(
        "keyword",
        [
            "close",
            "closes",
            "closed",
            "fix",
            "fixes",
            "fixed",
            "resolve",
            "resolves",
            "resolved",
        ],
    )
    def test_each_keyword_with_hash_reference(self, keyword: str) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        hook_input = _bash(f"git commit -m '{keyword} #123'")
        assert handler.matches(hook_input)
        assert handler.handle(hook_input).decision == Decision.DENY

    @pytest.mark.parametrize(
        "reference",
        [
            "#42",
            "GH-42",
            "gh-42",
            "octo-org/octo.repo#42",
            "https://github.com/octo-org/octo-repo/issues/42",
        ],
    )
    def test_each_reference_form(self, reference: str) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash(f"git commit -m 'Fixes {reference}'"))

    def test_case_insensitive(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash("git commit -m 'FIXES #7'"))
        assert handler.matches(_bash("git commit -m 'Resolves #7'"))

    def test_colon_after_keyword(self) -> None:
        """GitHub documents `Closes: #10` as a recognised form."""
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash("git commit -m 'Closes: #10'"))

    def test_double_quoted_message(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash('git commit -m "Fixes #123"'))

    def test_second_of_multiple_m_paragraphs(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash("git commit -m 'Add feature' -m 'closes #9'"))

    def test_am_combined_flags(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash("git commit -am 'fixed #55'"))

    def test_git_merge_message(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash("git merge feature -m 'Merge: resolves #12'"))

    def test_git_tag_message(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash("git tag -a v1.0 -m 'fixes #12 shipped'"))

    def test_git_global_options_do_not_evade(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash("git -C /workspace commit -m 'Fixes #3'"))

    def test_heredoc_visible_in_command_string(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        command = 'git commit -F - <<EOF\nAdd thing\n\nFixes #88\nEOF'
        assert handler.matches(_bash(command))


class TestNegativeCases:
    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m 'fixes the race condition'",  # keyword, no reference
            "git commit -m 'fix flaky test on CI'",
            "git commit -m 'see #123 for background'",  # reference, no keyword
            "git commit -m 'Addresses #123'",  # the recommended rewrite
            "git commit -m 'Refs #123'",
            "git log --grep=fixes",  # not a message write
            "git commit -m 'prefixes #dir handling'",  # keyword inside a word
            "gh issue close 123",  # deliberate, different act
            "echo fixes",
            "ls -la",
        ],
    )
    def test_does_not_match(self, command: str) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert not handler.matches(_bash(command))

    def test_non_bash_tool_ignored(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert not handler.matches(
            {"tool_name": "Write", "tool_input": {"content": "Fixes #123"}}
        )

    def test_bare_issue_number_without_keyword(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert not handler.matches(_bash("git commit -m 'Plan 00275: work on #tags'"))


class TestScratchFileRoute:
    def test_dash_f_file_with_closing_reference_is_denied(self, tmp_path: Path) -> None:
        msg = tmp_path / "msg.txt"
        msg.write_text("Add feature\n\nFixes #123\n", encoding="utf-8")
        handler = GithubAutoCloseKeywordsHandler()
        hook_input = _bash(f"git commit -F {msg}")
        assert handler.matches(hook_input)
        assert handler.handle(hook_input).decision == Decision.DENY

    def test_file_equals_form(self, tmp_path: Path) -> None:
        msg = tmp_path / "msg.txt"
        msg.write_text("resolves GH-9\n", encoding="utf-8")
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(_bash(f"git commit --file={msg}"))

    def test_clean_file_is_allowed(self, tmp_path: Path) -> None:
        msg = tmp_path / "msg.txt"
        msg.write_text("Add feature\n\nAddresses #123\n", encoding="utf-8")
        handler = GithubAutoCloseKeywordsHandler()
        assert not handler.matches(_bash(f"git commit -F {msg}"))

    def test_missing_file_is_allowed(self, tmp_path: Path) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert not handler.matches(_bash(f"git commit -F {tmp_path}/nope.txt"))

    def test_relative_path_resolved_against_cwd(self, tmp_path: Path) -> None:
        msg = tmp_path / "rel.txt"
        msg.write_text("closes #4\n", encoding="utf-8")
        handler = GithubAutoCloseKeywordsHandler()
        hook_input: dict[str, object] = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -F rel.txt"},
            "cwd": str(tmp_path),
        }
        assert handler.matches(hook_input)

    def test_template_flag_is_not_a_message_source(self, tmp_path: Path) -> None:
        tpl = tmp_path / "tpl.txt"
        tpl.write_text("Fixes #123\n", encoding="utf-8")
        handler = GithubAutoCloseKeywordsHandler()
        assert not handler.matches(_bash(f"git commit -t {tpl} -m 'clean message'"))


class TestEscapeHatch:
    def test_declared_intent_allows(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert not handler.matches(
            _bash('MUST_AUTO_CLOSE_BECAUSE="issue is done"; git commit -m \'Fixes #1\'')
        )

    def test_empty_reason_does_not_allow(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        assert handler.matches(
            _bash('MUST_AUTO_CLOSE_BECAUSE=""; git commit -m \'Fixes #1\'')
        )


class TestWarnMode:
    def test_warn_mode_allows_with_context(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        handler._mode = "warn"
        hook_input = _bash("git commit -m 'Fixes #123'")
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context


class TestDenyMessage:
    def test_quotes_match_and_offers_rewrites(self) -> None:
        handler = GithubAutoCloseKeywordsHandler()
        result = handler.handle(_bash("git commit -m 'Fixes #123'"))
        assert result.decision == Decision.DENY
        assert "Fixes #123" in result.reason
        assert "Addresses #123" in result.reason
        assert "Refs" in result.reason
        assert "MUST_AUTO_CLOSE_BECAUSE" in result.reason


class TestGuidanceAndAcceptance:
    def test_get_claude_md_names_the_hatch_and_rewrites(self) -> None:
        guidance = GithubAutoCloseKeywordsHandler().get_claude_md()
        assert guidance is not None
        assert "MUST_AUTO_CLOSE_BECAUSE" in guidance
        assert "Addresses" in guidance

    def test_acceptance_tests_exist_and_are_echo_safe(self) -> None:
        tests = GithubAutoCloseKeywordsHandler().get_acceptance_tests()
        assert tests
        for test in tests:
            assert test.title
            assert test.command
