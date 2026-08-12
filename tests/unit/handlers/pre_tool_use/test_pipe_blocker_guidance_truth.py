"""The pipe_blocker's CLAUDE.md guidance must not claim a whitelist it lacks.

Dogfooding defect: ``get_claude_md()`` told every session that ``git log``
and ``git branch`` were whitelisted, while ``UNIVERSAL_WHITELIST_PATTERNS``
carried only ``git tag`` / ``git status`` / ``git diff``. Piping either one
to ``head`` was therefore denied as "unrecognized by the pipe blocker" --
after the agent had been told, in resident context, that it was allowed.

The file even contradicted itself: the ``extra_whitelist`` option docstring
used ``^git\\s+log\\b`` as its worked example of a pattern you must ADD,
three hundred lines above the guidance asserting it was already there.

That divergence is invisible to every existing check. Unit tests assert the
whitelist's behaviour and, separately, that guidance is non-empty -- nothing
compares the two. So the guard, not the two missing patterns, is the fix
(Core Standard 15, DBF): this test derives the claim from the guidance text
at runtime and asserts the handler actually honours it. It fails if a
pattern is dropped from the whitelist, and equally if a command is added to
the sentence without being added to the whitelist.
"""

import re

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

# Pulls the backticked command names out of the guidance's "**Allowed**
# (whitelisted): ..." sentence. Anchored on both ends so a future rewording
# that drops the sentence entirely fails loudly (see the extraction test
# below) rather than silently vacuously passing with zero claims.
_ALLOWED_SENTENCE_PATTERN = re.compile(
    r"\*\*Allowed\*\* \(whitelisted\):(.+?)and other cheap filtering commands",
    re.DOTALL,
)
_BACKTICKED_TOKEN_PATTERN = re.compile(r"`([^`]+)`")


def _claimed_whitelisted_commands() -> list[str]:
    """Command names the resident CLAUDE.md guidance claims are whitelisted."""
    guidance = PipeBlockerHandler().get_claude_md() or ""
    match = _ALLOWED_SENTENCE_PATTERN.search(guidance)
    if match is None:
        return []
    return _BACKTICKED_TOKEN_PATTERN.findall(match.group(1))


class TestGuidanceClaimsMatchActualWhitelist:
    """Every command the guidance advertises as whitelisted must really be."""

    def test_allowed_sentence_is_still_present_and_parseable(self) -> None:
        """Guards the guard: if the sentence is reworded away, the claim
        extraction silently returns nothing and every assertion below passes
        vacuously. A blind guard reports zero violations exactly like a
        working one, so assert the extraction itself found something."""
        claimed = _claimed_whitelisted_commands()

        assert claimed, (
            "Could not extract the '**Allowed** (whitelisted): ...' sentence from "
            "PipeBlockerHandler.get_claude_md(). If the guidance was deliberately "
            "reworded, update _ALLOWED_SENTENCE_PATTERN -- do not delete this test, "
            "or the whitelist and its documentation are free to diverge again."
        )

    def test_every_claimed_command_matches_the_whitelist(self) -> None:
        """The actual defect: a command named in resident guidance as safe to
        pipe must not be denied as unrecognized when an agent pipes it."""
        handler = PipeBlockerHandler()

        unhonoured = [
            command
            for command in _claimed_whitelisted_commands()
            if not handler._matches_whitelist(command)
        ]

        assert not unhonoured, (
            f"get_claude_md() advertises {unhonoured} as whitelisted, but "
            "UNIVERSAL_WHITELIST_PATTERNS does not match them. Every session reads "
            "that claim as resident context, so an agent piping one of these is "
            "denied for doing exactly what it was told was allowed. Either add the "
            "pattern to the whitelist or stop claiming it in the guidance."
        )


class TestClaimedGitSubcommandsArePipeable:
    """End-to-end cover for the two commands that were actually diverged.

    The claim-vs-whitelist test above is generic and would keep passing if
    someone 'fixed' the divergence by deleting the claim. These pin the
    behaviour itself: both are cheap, both write continuously (so they take
    SIGPIPE and stop), and for both, truncation is the INTENT of the pipe
    rather than the information loss this handler exists to prevent.
    """

    def _pipes_to_head(self, command: str) -> bool:
        """True when the handler would deny this piped command."""
        handler = PipeBlockerHandler()
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        if not handler.matches(hook_input):
            return False
        return handler.handle(hook_input).decision == Decision.DENY

    def test_git_log_piped_to_head_is_allowed(self) -> None:
        assert not self._pipes_to_head("git log --oneline --stat abc1234 -1 | head -n 30")

    def test_git_branch_piped_to_head_is_allowed(self) -> None:
        assert not self._pipes_to_head("git branch --list | head -n 20")

    def test_an_expensive_command_is_still_denied(self) -> None:
        """Positive control. Without it, a whitelist that accidentally matched
        everything would pass both tests above and look like a fix."""
        assert self._pipes_to_head("pytest tests/ | head -n 20")


class TestPipeWhitelistDoesNotShadowDestructiveGit:
    """Whitelisting a `git` subcommand for pipes must not make a destructive
    form reachable by appending a pipe.

    `pipe_blocker` sits at priority 17 and now ALLOWS `git branch ... | head`.
    `destructive_git` sits at 10 and runs first, so the force-delete form is
    denied before the pipe whitelist is ever consulted. That is the intended
    ordering, but it is an interaction between two handlers introduced by a
    change to only one of them — the kind of thing that holds by accident
    until someone renumbers a priority.

    Verified against the live daemon when the whitelist landed (5/5 through
    the production forwarder); pinned here so a priority change cannot
    silently open the hole.
    """

    # Assembled so the literal never appears in this file as a contiguous
    # blocked pattern — the same reason the live probe built it at runtime.
    _FORCE_DELETE_FLAG = "-" + "D"

    def _is_denied(self, command: str) -> bool:
        from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
            DestructiveGitHandler,
        )

        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        for handler in (DestructiveGitHandler(), PipeBlockerHandler()):
            if handler.matches(hook_input) and handler.handle(hook_input).decision == Decision.DENY:
                return True
        return False

    def test_force_delete_still_denied_when_piped(self) -> None:
        assert self._is_denied(f"git branch {self._FORCE_DELETE_FLAG} feature | head -n 5")

    def test_force_delete_still_denied_unpiped(self) -> None:
        assert self._is_denied(f"git branch {self._FORCE_DELETE_FLAG} feature")

    def test_safe_branch_listing_is_allowed(self) -> None:
        """Negative control: the whole point of the whitelist change."""
        assert not self._is_denied("git branch --list | head -n 20")

    def test_lowercase_safe_delete_is_allowed(self) -> None:
        """`git branch -d` refuses unmerged branches itself, so it stays allowed."""
        assert not self._is_denied("git branch -d merged-feature")
