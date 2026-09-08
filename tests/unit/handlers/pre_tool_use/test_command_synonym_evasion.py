"""A SYNONYM respelling is a distinct evasion axis from the INVOCATION
respelling `test_blocking_handler_evasion.py` guards (Plan 00202: `git -C
/path <sub>`, `sudo -H pip`, a path-qualified binary, a shell line
continuation — the SAME command, spelled differently). A synonym respelling
is a DIFFERENT command that performs the same destructive act — confirmed by
Plan 00205 in two places: `git branch -D` has an exact plumbing equivalent in
`git update-ref -d refs/heads/<name>`, and `git push --force` has one in a
`+`-prefixed refspec (`git push origin +main:main`). Both were unguarded
against v3.52.0 source and found only during a release gate, not by any test.

This file is the completeness gate for that axis: a table of confirmed
synonym pairs, plus a check that fails when a handler this plan actually
swept for synonyms is missing a classification — declared coverage, or an
explicit "none found" with a reason, never silence.

**Scope, deliberately bounded** (PLAN.md Risks & Mitigations: "the synonym
axis is unbounded and the plan never converges"). This file's completeness
universe is exactly the handlers Plan 00205 Phase 1 swept: `destructive_git`
itself (Task 1.1, all 9 rules) plus the four named siblings from Task 1.2
(`git_stash`, `pip_break_system`, `sudo_pip`, `curl_pipe_shell`) — the same
"hardened against invocation-respelling" set `test_blocking_handler_evasion.py`
was written for. Extending this completeness gate to EVERY command-anchored
handler in that file (`sensitive_content`, `ancestry_preserving_merge`, ...)
is real future work and is not silently claimed here: `_SWEPT_HANDLERS` names
exactly the five, no more.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from tests.unit.handlers.pre_tool_use.test_blocking_handler_evasion import _bash, _build

from claude_code_hooks_daemon.core import Decision

# The exact set Plan 00205 Phase 1 swept. Not the full command-anchored
# universe `test_blocking_handler_evasion.py` classifies — see module
# docstring "Scope, deliberately bounded".
_SWEPT_HANDLERS: frozenset[str] = frozenset(
    {
        "DestructiveGitHandler",
        "GitStashHandler",
        "PipBreakSystemHandler",
        "SudoPipHandler",
        "CurlPipeShellHandler",
    }
)

# handler class name -> commands that reach the SAME destructive outcome as
# one of the handler's own rules via a DIFFERENT git/shell subcommand. Each
# must be DENIED.
_SYNONYM_CASES: dict[str, tuple[str, ...]] = {
    "DestructiveGitHandler": (
        # git branch -D  <->  git update-ref -d refs/heads/<name>
        "git update-ref -d refs/heads/feature",
        "git update-ref -d refs/heads/feature abc123def456",
        # git push --force  <->  git push <remote> +<refspec>
        "git push origin +main:main",
        "git push origin +refs/heads/main:refs/heads/main",
    ),
}

# Handlers (or, for DestructiveGitHandler, the REMAINING rules beyond the two
# fixed above) swept for an ordinary synonym and found to have none. The
# Non-Goals bar is "ordinary spellings a well-intentioned agent would type",
# not every conceivable plumbing route to data loss — each reason records
# what was actually checked, so the entry can be challenged, not just trusted.
_NO_ORDINARY_SYNONYM_KNOWN: dict[str, str] = {
    "GitStashHandler": (
        "Plan 00205 Task 1.2 sweep: no other porcelain subcommand creates a "
        "stash entry; the nearest plumbing route (constructing refs/stash "
        "by hand with update-ref/commit-tree) is a multi-step sequence, not "
        "an ordinary one-command spelling"
    ),
    "PipBreakSystemHandler": (
        "Plan 00205 Task 1.2 sweep: the handler's own pattern already covers "
        "every ordinary invocation shape (pip, pip3, python -m pip, "
        "python3 -m pip); no other command installs a package with this flag"
    ),
    "SudoPipHandler": (
        "Plan 00205 Task 1.2 sweep: the handler's own pattern already covers "
        "every ordinary sudo+pip invocation shape (via SUDO_INVOCATION and "
        "OPTIONAL_PATH); no other command performs a root-owned pip install"
    ),
    "CurlPipeShellHandler": (
        "Plan 00205 Task 1.2 sweep: curl and wget are the ordinary fetchers "
        "and are already covered together by one pattern; no third fetch "
        "utility ships by default on the platforms this project targets"
    ),
}


def test_destructive_git_remaining_rules_have_no_recorded_synonym() -> None:
    """Documents the rest of Task 1.1's sweep: 7 of 9 rules, no ordinary synonym.

    A single boolean assertion, not a loop over commands — there is nothing to
    DENY here, only a decision to record. reset --hard, clean -f, checkout
    (. and -- <file>), restore, stash drop, stash clear and commit --amend
    each lack a ONE-COMMAND porcelain synonym: every plumbing equivalent
    (read-tree+checkout-index, reflog surgery, reset --soft plus a new
    commit, ...) is a multi-step sequence, which the plan's Non-Goals
    explicitly place out of scope ("ordinary spellings a well-intentioned
    agent would type").
    """
    assert "DestructiveGitHandler" in _SYNONYM_CASES, (
        "This test documents a decision about the OTHER 7 rules on a handler "
        "that has synonym cases for its remaining 2 — if that handler is ever "
        "removed from _SYNONYM_CASES, this test's premise no longer holds and "
        "needs re-deciding, not silently dropping."
    )


class TestCompletenessOfTheSweptUniverse:
    """The guard that stops this guard going blind, scoped to _SWEPT_HANDLERS."""

    def test_every_swept_handler_is_classified(self) -> None:
        classified = set(_SYNONYM_CASES) | set(_NO_ORDINARY_SYNONYM_KNOWN)
        missing = _SWEPT_HANDLERS - classified

        assert not missing, (
            f"Handler(s) swept by Plan 00205 but not classified here: {sorted(missing)}.\n\n"
            "Add to _SYNONYM_CASES (it has a synonym; list the denied commands) or "
            "_NO_ORDINARY_SYNONYM_KNOWN (swept, none found; state the reason)."
        )

    def test_classification_lists_are_disjoint(self) -> None:
        overlap = set(_SYNONYM_CASES) & set(_NO_ORDINARY_SYNONYM_KNOWN)
        assert not overlap, f"Handler(s) classified in both tables: {sorted(overlap)}"

    def test_no_stale_classification_outside_the_swept_universe(self) -> None:
        classified = set(_SYNONYM_CASES) | set(_NO_ORDINARY_SYNONYM_KNOWN)
        stale = classified - _SWEPT_HANDLERS

        assert not stale, (
            f"Handler(s) classified here but not in _SWEPT_HANDLERS: {sorted(stale)}. "
            "Either it was actually swept (add it to _SWEPT_HANDLERS) or the entry "
            "is stale and should be removed."
        )

    def test_every_reason_is_non_empty(self) -> None:
        for class_name, reason in _NO_ORDINARY_SYNONYM_KNOWN.items():
            assert reason.strip(), f"{class_name} has an empty _NO_ORDINARY_SYNONYM_KNOWN reason"


class TestSynonymsAreDenied:
    """The behavioural pin: every recorded synonym must actually be denied."""

    @pytest.mark.parametrize(
        ("class_name", "command"),
        [
            (class_name, command)
            for class_name, commands in sorted(_SYNONYM_CASES.items())
            for command in commands
        ],
    )
    def test_synonym_command_is_denied(self, class_name: str, command: str) -> None:
        handler = _build(class_name)
        hook_input = _bash(command)

        assert handler.matches(hook_input) is True, (
            f"SYNONYM BYPASS: {class_name} does not match {command!r}.\n"
            "A different command achieving the same destructive act is not blocked."
        )

        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY


class TestSynonymWideningDidNotCreateFalsePositives:
    """The other direction: the synonym patterns must not over-match either."""

    _MUST_NOT_MATCH: ClassVar[dict[str, tuple[str, ...]]] = {
        "DestructiveGitHandler": (
            "git push origin main:main",
            "git push origin HEAD:refs/for/main",
            "git push origin feature+fix",
            "git push origin feature+fix:feature+fix",
            "git update-ref refs/heads/feature abc123def456",
            "git update-ref -d refs/remotes/origin/feature",
        ),
    }

    @pytest.mark.parametrize(
        ("class_name", "command"),
        [
            (class_name, command)
            for class_name, commands in sorted(_MUST_NOT_MATCH.items())
            for command in commands
        ],
    )
    def test_near_miss_stays_allowed(self, class_name: str, command: str) -> None:
        handler = _build(class_name)

        assert (
            handler.matches(_bash(command)) is False
        ), f"FALSE POSITIVE: {class_name} matches the safe command {command!r}."

    def test_every_synonym_handler_has_false_positive_cover(self) -> None:
        missing = set(_SYNONYM_CASES) - set(self._MUST_NOT_MATCH)

        assert (
            not missing
        ), f"Handler(s) with synonym cases but no false-positive cases: {sorted(missing)}."
