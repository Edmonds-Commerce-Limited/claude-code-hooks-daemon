"""IssueFilingGateHandler - the one enforced rule in the issue-reporting SOP.

Plan 00403 Phase 4. Everything else in that plan is advice: a generator that
refuses to build a leaky report, a form that asks for the right fields, a
document that says what to do. A reporter who types the issue body by hand walks
past all of it, and the material they paste in reaches a **public** tracker that
no edit and no deletion retracts. This handler is where the redaction guarantee
stops being a suggestion.

``gh issue create`` against this daemon's repository is denied unless its
``--body-file`` names a document :mod:`claude_code_hooks_daemon.issue_report`
produced and nobody has edited since.

Three boundaries decide whether this handler is usable or merely correct.

``it stands down in self-install``
    This project files and closes its own issues hourly (`issue-sdlc`). A gate
    that fired here would break the maintainer's delivery loop on its first
    tick — a far likelier outcome than the leak it guards. Self-install is
    resolved from :class:`ProjectContext`, and an UNRESOLVABLE answer is treated
    as a client install, because the failure it guards cannot be retracted while
    the cost of being wrong the other way is one round trip.

``it engages on the repository a command TARGETS, never on a mention``
    A client filing "upgrade Edmonds-Commerce-Limited/claude-code-hooks-daemon
    to 3.64" against their own backlog names this repository and is none of this
    handler's business. Substring matching would deny it, and a gate that blocks
    a project's own issues gets switched off within the day. The target comes
    from ``--repo``/``-R`` in the same shell segment, from a ``GH_REPO``
    assignment in the command, or — when neither says — from the git remotes of
    the working directory, which is what ``gh`` itself falls back to.

    That third route is not an exotic one and was missing. Every client install
    carries a clone of THIS repository under ``.claude/hooks-daemon/``, so a
    bare ``gh issue create`` typed with the shell inside that clone filed
    against a PUBLIC tracker with the gate standing by. The residual is
    narrower and stated rather than unnoticed: if git cannot answer for that
    directory, the answer is "not ours", because gating on an unresolvable cwd
    would deny a client's ordinary filing on their own tracker.

``a comment is deliberately NOT covered``
    No generator produces a comment body, so requiring provenance on one would
    make the tracker unusable for the reporter this plan exists to help. The
    secret-term scan in ``sensitive_content`` already covers ``gh issue
    comment`` bodies, which is the leak class that cannot be retracted.

Like the provenance header it checks, this is a guard against the accident
rather than against an adversary. An agent determined to file by hand can set
``GH_REPO`` in its environment, or use the API directly. What it reliably stops
is the ordinary path: a report generated clean, edited to paste in "just the
relevant bit of the log", and filed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.issue_report.provenance import (
    GENERATOR_COMMAND,
    verify_document,
)
from claude_code_hooks_daemon.issue_report.upstream import (
    UPSTREAM_REPO_DISPLAY,
    UPSTREAM_REPO_SLUG,
)
from claude_code_hooks_daemon.utils.command_evasion import compile_command_name_pattern
from claude_code_hooks_daemon.utils.git_repo import GitRepo
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

logger = logging.getLogger(__name__)

#: Shell operators separating one command from the next. Each segment is judged
#: alone so a ``--repo`` belonging to a neighbouring command cannot decide this
#: one's target.
_SEGMENT_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "|", "\n")

_GH_ISSUE_CREATE: Final[re.Pattern[str]] = compile_command_name_pattern("gh issue create")

#: ``--repo x``, ``--repo=x``, ``-R x``, bare or quoted. The leading
#: ``(?:\A|\s)`` keeps ``-R`` from matching inside a word such as a filename.
_REPO_FLAG: Final[re.Pattern[str]] = re.compile(
    r"(?:\A|\s)(?:--repo|-R)(?:\s+|=)(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
)

#: ``gh`` honours this when no flag is given, so it selects the target just as
#: surely as ``--repo`` does.
_GH_REPO_ENV: Final[re.Pattern[str]] = re.compile(
    r"(?:\A|\s)GH_REPO=(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
)

#: ``--body-file x``, ``--body-file=x``, ``-F x``, bare or quoted. ``-F`` is
#: ``gh``'s own short form for it on ``issue``/``pr`` subcommands.
_BODY_FILE: Final[re.Pattern[str]] = re.compile(
    r"(?:\A|\s)(?:--body-file|-F)(?:\s+|=)(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
)

#: Everything ``gh`` strips before the owner/name pair, across the spellings it
#: accepts for ``--repo``: an https URL, an ssh URL, and the scp-like form.
_REPO_URL_PREFIX: Final[re.Pattern[str]] = re.compile(r"\A(?:https?://|ssh://git@|git@)")
_REPO_HOST_PREFIX: Final[re.Pattern[str]] = re.compile(r"\Agithub\.com[:/]")

#: ``gh`` reads the body from stdin for this value, and nothing readable exists
#: to check before the fact.
_STDIN_BODY: Final[str] = "-"

#: Opens GitHub's own issue form in a browser instead of filing anything. This
#: is a DELIBERATE hole in the gate, and it is the escape hatch that keeps the
#: gate honest: the forms are the one place the redaction rule is stated to a
#: human, the defect form cannot be submitted without ticking two
#: acknowledgements, and nothing reaches the tracker until a person has read
#: them and clicked. Stated that precisely because the free-text form carries
#: the rule but no checkboxes, and a safety property this file overstates is
#: one a reader will rely on.
#:
#: Denying it would leave someone who genuinely cannot run the generator — a
#: defect that stops the CLI, a machine without the install — with no route at
#: all except working around the gate. A gate whose only escape is evasion
#: teaches evasion, which is the same reason `reference_repo_freshness` never
#: intercepts `git`.
_WEB_FLAG: Final[re.Pattern[str]] = re.compile(r"(?:\A|\s)--web(?=\s|\Z)")

#: A generated report is a few KiB. Past this bound the file is not one, and
#: reading it into a hook would cost the dispatch budget to reach the same
#: verdict. Matches the bound `sensitive_content` applies to the same files.
_MAX_BODY_BYTES: Final[int] = 65_536
_BODY_ENCODING: Final[str] = "utf-8"
_BODY_DECODE_ERRORS: Final[str] = "replace"


_RULE = Rule(
    rule_id=RuleID.UPSTREAM_ISSUE_UNVERIFIED_BODY,
    blocked=(
        "`gh issue create` against the hooks-daemon tracker with a body no generator produced"
    ),
    why=(
        "that tracker is PUBLIC and an issue cannot be retracted -- a pasted config, log "
        "excerpt or absolute path costs the CLIENT permanently, while an over-redacted "
        "report costs one round trip"
    ),
    fix=f"Generate the body with `{GENERATOR_COMMAND}` and file the file it writes",
    verbose=(
        "That tracker is PUBLIC, and an issue cannot be retracted by editing or deleting "
        "it. A pasted config, log excerpt or absolute path costs the CLIENT permanently, "
        "while an over-redacted report costs one round trip asking for more detail. The "
        "two are not comparable, which is why this is a block rather than a reminder.\n\n"
        f"Run `{GENERATOR_COMMAND} --fields <file.json>`. It collects a controlled field "
        "set -- summary, expectation, observation, reproduction, the config you ruled out "
        "and the source line you read -- and it gathers no hostname, no config dump, no "
        "environment file and no logs. Those are not scrubbed out afterwards; they are "
        "never collected, which is a guarantee an inspection pass cannot make.\n\n"
        "It then writes a document carrying a provenance header, and this gate accepts "
        f"that file:\n\n    gh issue create --repo {UPSTREAM_REPO_DISPLAY} "
        "--body-file <report>\n\n"
        "**Read the report before filing it.** The gate proves the body is the one the "
        "generator built, not that the prose you wrote inside it is safe to publish.\n\n"
        "Editing the generated file breaks its digest and is refused, deliberately: a "
        "clean report edited to paste in 'just the relevant bit of the log' is the exact "
        "failure this exists to catch. Extra detail belongs in the reproduction field, "
        "where the checks still run over it.\n\n"
        "**If you genuinely cannot run the generator** -- a defect that stops the CLI, a "
        "machine without the install -- use `--web`. It is allowed: it files nothing, it "
        "opens GitHub's own issue forms, every one of them states the same rule, and the "
        "defect form cannot be submitted without ticking two acknowledgements -- so a "
        "person is in the loop by construction.\n\n"
        "Issues on your OWN repository are untouched by this rule, and so is every "
        "`gh issue comment`, `list` and `view` -- including against this tracker."
    ),
)


class IssueFilingGateHandler(PreToolUseHandlerBase):
    """Deny an upstream issue whose body nothing checked."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ISSUE_FILING_GATE,
            priority=Priority.ISSUE_FILING_GATE,
            tags=[HandlerTag.GITHUB, HandlerTag.BLOCKING, HandlerTag.SAFETY],
        )
        self._formatter = RuleFormatter()
        self.self_install_reader: Callable[[], bool] = ProjectContext.self_install_mode

    # ---------------------------------------------------------------- matching

    def _is_self_install(self) -> bool:
        """Whether this IS the daemon repository, where the gate stands down.

        Fails CLOSED to "client install". An unresolvable project context means
        the handler does not know which side it is on, and the two errors are
        not comparable: leaving the gate on costs a maintainer one clear refusal
        naming the command to run instead, while turning it off costs a client a
        public disclosure nothing can withdraw.
        """
        try:
            return self.self_install_reader()
        except (RuntimeError, OSError) as exc:
            logger.debug("install mode unresolvable, assuming client install: %s", exc)
            return False

    @staticmethod
    def _flag_value(match: re.Match[str]) -> str:
        """The value of a flag, whichever quoting alternative captured it."""
        return next(group for group in match.groups() if group)

    @classmethod
    def _repo_slug(cls, value: str) -> str:
        """Normalise every spelling ``gh`` accepts down to ``owner/name``.

        ``gh --repo`` takes the slug, an https URL, an ssh URL and the scp-like
        ``git@github.com:owner/name.git``. They all address the same repository,
        so a gate that recognised only one of them would be trivially walked
        past by pasting the URL from a browser.
        """
        text = value.strip().strip("\"'")
        text = _REPO_URL_PREFIX.sub("", text)
        text = _REPO_HOST_PREFIX.sub("", text)
        text = text.removesuffix(".git")
        return text.strip("/").lower()

    @classmethod
    def _cwd_repo_slug(cls, cwd: str | None) -> str | None:
        """The slug ``gh`` would resolve from the working directory, or None.

        This is ``gh``'s DEFAULT answer, not an exotic one: with no ``--repo``
        and no ``GH_REPO`` it reads the base repository from the current
        directory's remotes. Leaving it out was a real hole rather than a
        theoretical one, because every client install carries a clone of THIS
        repository under ``.claude/hooks-daemon/`` — so a bare
        ``gh issue create`` typed with the shell inside that clone filed a
        hand-written body against a PUBLIC tracker while the gate stood by.

        Resolution failure answers None rather than "assume upstream". The
        alternative would gate a client's ordinary filing on their OWN tracker
        whenever git could not answer, which is the false positive the module
        docstring names as the one that gets this handler switched off.
        """
        if not cwd:
            return None
        # "Could not resolve" is carried in a variable and returned once below,
        # rather than returned from the handler body: an early return from an
        # except block reads as success to a reader AND is rejected by the
        # error-hiding audit, which matches the shape rather than the intent.
        url: str | None = None
        try:
            repo = GitRepo.resolve_for(Path(cwd))
            if repo is not None:
                url = repo.read_config("remote.origin.url")
        except (OSError, ValueError) as exc:  # pragma: no cover - defensive
            logger.debug("Could not resolve the repository for %s: %s", cwd, exc)
            url = None
        return cls._repo_slug(url) if url else None

    @classmethod
    def _targets_upstream(cls, segment: str, command: str, cwd: str | None = None) -> bool:
        """Whether this ``gh issue create`` would file against THIS repository.

        The segment's own ``--repo`` decides when it has one. Only when it does
        not does the command-wide ``GH_REPO`` assignment answer, which mirrors
        ``gh``'s own precedence — and means a command that sets ``GH_REPO`` to
        this repo and then overrides it with ``--repo theirs`` is left alone.
        The working directory answers last, for the same reason: it is what
        ``gh`` itself falls back to when nothing else names a repository.
        """
        flag = _REPO_FLAG.search(segment)
        if flag is not None:
            return cls._repo_slug(cls._flag_value(flag)) == UPSTREAM_REPO_SLUG
        env = _GH_REPO_ENV.search(command)
        if env is not None:
            return cls._repo_slug(cls._flag_value(env)) == UPSTREAM_REPO_SLUG
        return cls._cwd_repo_slug(cwd) == UPSTREAM_REPO_SLUG

    @classmethod
    def _filing_segments(cls, command: str, cwd: str | None = None) -> list[str]:
        """Every segment of ``command`` that would file an issue against us."""
        segments = []
        for raw in split_unquoted(command, _SEGMENT_SEPARATORS):
            segment = raw.strip()
            if not segment or _GH_ISSUE_CREATE.search(segment) is None:
                continue
            if cls._targets_upstream(segment, command, cwd):
                segments.append(segment)
        return segments

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Engage only for a filing against this repository, from a client.

        The order matters for cost, not for correctness: the command test is a
        regex over text already in hand, while resolving the install mode
        touches a singleton. The overwhelmingly common Bash call is neither, and
        should pay for neither.
        """
        command = get_bash_command(hook_input)
        if not command:
            return False
        if not self._filing_segments(command, hook_input.get("cwd")):
            return False
        return not self._is_self_install()

    # ----------------------------------------------------------------- verdict

    @staticmethod
    def _resolve(raw: str, hook_input: dict[str, Any]) -> Path:
        path = Path(raw)
        if path.is_absolute():
            return path
        cwd = hook_input.get("cwd")
        return Path(cwd) / path if isinstance(cwd, str) and cwd else path

    @staticmethod
    def _read(path: Path) -> tuple[str | None, str]:
        """The body to judge, or ``(None, reason)`` saying why there is none.

        An unreadable body file is a REFUSAL rather than a pass. The whole point
        of the gate is that nothing unchecked is filed, and "I could not read
        it" is not a check — ``gh`` would fail on a missing file anyway, so the
        only behaviour lost is a confusing error arriving from somewhere else.
        """
        try:
            size = path.stat().st_size
        except OSError as exc:
            return None, f"`{path}` could not be read ({exc.strerror})"
        except ValueError as exc:
            # Plan 00466 N24 follow-up: a NUL-bearing path raises ValueError
            # from stat(), not OSError -- still just "could not be read".
            return None, f"`{path}` could not be read ({exc})"
        if size > _MAX_BODY_BYTES:
            return None, (
                f"`{path}` is {size} bytes, far larger than any generated report. "
                "Whatever it is, it was not produced by the generator"
            )
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return None, f"`{path}` could not be read ({exc.strerror})"
        return raw.decode(_BODY_ENCODING, errors=_BODY_DECODE_ERRORS), ""

    def _segment_problems(self, segment: str, hook_input: dict[str, Any]) -> list[str]:
        """Why this filing cannot go ahead, or an empty list when it may."""
        if _WEB_FLAG.search(segment):
            # Files nothing: it opens GitHub's own forms, where a human meets
            # the rule before anything is published. See _WEB_FLAG for why this
            # hole is the one that keeps the gate honest rather than the one
            # that defeats it.
            return []

        matches = list(_BODY_FILE.finditer(segment))
        if not matches:
            return [
                "this `gh issue create` carries no `--body-file`, so its body was either "
                "typed inline or composed in an editor. Neither has been through any "
                "check"
            ]

        problems: list[str] = []
        for match in matches:
            raw = self._flag_value(match)
            if raw == _STDIN_BODY:
                problems.append(
                    "the body is being piped in on stdin, which cannot be read before the "
                    "fact. Write it to a file and name that file instead"
                )
                continue
            body, unreadable = self._read(self._resolve(raw, hook_input))
            if body is None:
                problems.append(unreadable)
                continue
            problems.extend(problem.reason for problem in verify_document(body))
        return problems

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Judge every filing in the command, not merely the first.

        A chain naming one valid report and one hand-written file must be
        denied: allowing it because something in the command verified would let
        a clean report launder whatever travels alongside it.
        """
        command = get_bash_command(hook_input) or ""
        problems: list[str] = []
        for segment in self._filing_segments(command, hook_input.get("cwd")):
            problems.extend(self._segment_problems(segment, hook_input))

        if not problems:
            return GatingResult(decision=Decision.ALLOW)

        detail = "\n".join(f"  - {problem}." for problem in problems)
        return GatingResult.deny(
            f"{self._formatter.verbose(_RULE)}\n\nWhat stopped this filing:\n\n{detail}"
        )

    # ------------------------------------------------------------- self-report

    def get_rules(self) -> list[Rule]:
        """One rule: every shape of an unchecked body is the same fact."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        """Guidance for the generated ``<hooksdaemon>`` block."""
        return (
            "## issue_filing_gate — an upstream issue body must come from the generator\n\n"
            "`gh issue create` against the hooks-daemon repository is **denied** unless "
            f"`--body-file` names a document `{GENERATOR_COMMAND}` produced and nobody has "
            "edited since. Issues on YOUR repository are untouched, and so are "
            "`gh issue comment`, `list` and `view` against any repository.\n\n"
            "**Why it is a block rather than advice:** that tracker is public, and an issue "
            "cannot be retracted by editing or deleting it. A pasted config, log excerpt or "
            "absolute path costs the client permanently; an over-redacted report costs one "
            "round trip asking for more detail. The two are not comparable.\n\n"
            f"**The remedy is one command.** `{GENERATOR_COMMAND} --fields <file.json>` "
            "collects a controlled field set and gathers no hostname, no config dump, no "
            "environment file and no logs — they are never collected rather than scrubbed "
            "out afterwards. File the document it writes with `--body-file`.\n\n"
            "**Editing that document is refused**, because the digest in its header stops "
            "matching. That is the failure this catches: a clean report edited to paste in "
            "'just the relevant bit of the log', then filed. Put the extra detail in the "
            "reproduction field, where the checks still run over it.\n\n"
            "**Read the report before you file it.** The gate proves the body is the one "
            "the generator built — not that the prose you wrote inside it is safe to "
            "publish. That judgement is still yours.\n\n"
            "**`--web` is allowed**, and is the fallback when the generator genuinely "
            "cannot run. It files nothing: it opens GitHub's own issue forms, which state "
            "the same rule, and the defect form cannot be submitted without ticking two "
            "acknowledgements.\n\n"
            "In the daemon's own repository this handler stands down entirely, so the "
            "project's own issue workflow is unaffected."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="issue filing gate - a hand-written body for our own tracker",
                command=(
                    f"gh issue create --repo {UPSTREAM_REPO_DISPLAY} --title x --body 'it broke'"
                ),
                description=(
                    "A `gh issue create` against the hooks-daemon tracker whose body no "
                    "generator produced is DENIED, and the refusal names the command that "
                    "produces an acceptable one."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[re.escape(GENERATOR_COMMAND)],
                safety_notes=(
                    "The command is never executed - the handler denies before the tool runs"
                ),
                test_type=TestType.BLOCKING,
                harness_cannot_produce=(
                    "The gate stands down in self-install, which is what this repository is, "
                    "so no verdict can be produced here without disabling the stand-down that "
                    "keeps `issue-sdlc` working. Running it anyway would file a real public "
                    "issue on this project's own tracker. The deny path is covered end to end "
                    "by tests/unit/handlers/pre_tool_use/test_issue_filing_gate.py, including "
                    "the self-install stand-down and the fail-closed unresolvable case."
                ),
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="issue filing gate - a client's own tracker is never touched",
                command="gh issue create --repo acme-corp/storefront --title x --body y",
                description=(
                    "The false positive that would get this handler switched off. A project "
                    "filing on its OWN backlog has nothing to do with this daemon, and must "
                    "pass whether or not the command mentions us."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Judged from the hook input alone; the command is never run, and the "
                    "repository named does not exist"
                ),
                test_type=TestType.BLOCKING,
                hook_input={
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": (
                            "gh issue create --repo acme-corp/storefront --title x --body y"
                        )
                    },
                    "session_id": "acceptance-issue-filing-other-repo",
                },
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
