"""Every handler's `get_claude_md()` verdict must be recorded, with a reason.

DBF. The v3.52.0 release ran a hand-written audit of `get_claude_md()`
coverage, found six PreToolUse *advisory* handlers returning `None`, and filed
them. Plan 00203 then applied a written criterion to all 107 handlers and found
that **all six were correct** — while two handlers the audit never looked at
were not: `LintOnEditHandler` (PostToolUse, and it DENIES) and the Stop-event
hedging detector (whose identical twin was covered).

A scan of one event type could not have found either. So the audit is replaced
by this table, which enumerates every handler and forces a verdict with a
reason attached.

**A verdict can be right about the section and wrong about the handler.** Both
language detectors existed twice — a Stop-event copy and a `nitpick`
pseudo-event copy — and this table exempted the nitpick pair *because the Stop
pair's resident section already carried the guidance*. That was true and
useless: the Stop pair sat behind `auto_continue_stop` (terminal, priority 10)
and never ran, so the handler holding the section was the dead one and the one
that fires was exempt. Plan 00237 deleted the Stop pair and moved the sections
onto the handlers that actually run. Nothing in this file could have caught
that — every reason here was accurate. `test_stop_chain_terminal_shadowing.py`
is the guard that can, which is why it must never be silenced.

`get_claude_md()` is `@abstractmethod`, so the method itself can never be
missing — every one of the handler classes on disk implements it. What escapes
is the *reasoning*: `return None` satisfies the ABC in five seconds and records
nothing about whether the question was asked. This file is where the answer
lives.

**Why a reason string and not a bare name.** Guidance is inlined into every
client project's resident `CLAUDE.md` and read IN FULL at the start of every
session. Measured on this repository, the injected block is ~73 KB across 53
sections — 68% of the whole file, ~18,300 tokens per session, paid whether or
not a handler ever fires. Both answers cost something, so both must be argued.

The criterion is in `CLAUDE/HANDLER_DEVELOPMENT.md`, four tests in precedence
order:

1. Can the handler DENY a tool call?
2. Is the advice too late for the call it fires on?
3. Is it a standing policy rather than a one-shot correction?
4. Would a reader who already has the fire-time message, and the rest of the
   block, learn anything? (overrides 1-3)

Discovery is deliberately intolerant: a handler that cannot be constructed
FAILS this suite rather than being skipped. `measure_instruction_footprint.py`
skips such handlers, which is right for a measurement and fatal for a guard —
a silently-dropped handler is exactly what this file exists to prevent.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any, ClassVar

import pytest

from claude_code_hooks_daemon import handlers as handlers_pkg
from claude_code_hooks_daemon.core.handler import Handler

# Handlers whose guidance is inlined into every client's resident CLAUDE.md.
# The value names the test from the criterion that the handler passes, so a
# reviewer can check the verdict rather than take it on trust.
_EARNS_GUIDANCE: dict[str, str] = {
    # -- Test 1: can DENY a tool call ------------------------------------
    "AbsolutePathHandler": "T1 denies relative Read/Write/Edit paths",
    "AncestryPreservingMergeHandler": "T1 denies squash/rebase merges",
    "AskUserQuestionBlockerHandler": "T1 denies unjustified AskUserQuestion",
    "CommentChangelogHandler": "T1 denies changelog narrative in comments",
    "CommentSizeHandler": "T1 denies growth of an over-limit comment",
    "CurlPipeShellHandler": "T1 denies piping network content to a shell",
    "DaemonLocationGuardHandler": "T1 denies cd into the daemon directory",
    "DangerousPermissionsHandler": "T1 denies chmod 777 and friends",
    "DestructiveGitHandler": "T1 denies irreversible git commands",
    "ErrorHidingBlockerHandler": "T1 denies error-suppression patterns",
    "GhIssueCommentsHandler": "T1 denies gh issue view without --comments",
    "GhPrCommentsHandler": "T1 denies gh pr view without --comments",
    "GitMessageBacktickHandler": "T1 denies a message whose backticks would execute",
    "GithubAutoCloseKeywordsHandler": (
        "T1 denies a message carrying an auto-closing keyword reference"
    ),
    "GitStashHandler": "T1 denies git stash without the escape hatch",
    "LintOnEditHandler": "T1 denies a write whose lint fails, in nine languages",
    "ValidateEslintOnWriteHandler": (
        "T1 denies a .ts/.tsx write on ESLint errors, on timeout, and on any "
        "failure to run ESLint — languages and failure behaviour that "
        "lint_on_edit's section does NOT cover"
    ),
    "LockFileEditBlockerHandler": "T1 denies direct lock-file edits",
    "LspEnforcementHandler": "T1 denies the first symbol-lookup grep in a session",
    "PipBreakSystemHandler": "T1 denies --break-system-packages",
    "PipeBlockerHandler": "T1 denies expensive pipes to head/tail",
    "DocsQaEditHandler": "T1 denies documentation writes that break the docs QA rules",
    "DocsQaCommitGateHandler": "T2 fires on the commit whose contents are already staged",
    "PlanQaEditHandler": "T1 denies plan documents that break the QA rules",
    "PlanTimeEstimatesHandler": "T1 denies time estimates in plan documents",
    "QaSuppressionHandler": "T1 denies QA suppression annotations",
    "RootRecursionGuardHandler": "T1 denies recursive scanners rooted at /",
    "SecurityAntipatternHandler": "T1 denies known-dangerous constructs",
    "SedBlockerHandler": "T1 denies sed used to modify files",
    "SensitiveContentHandler": "T1 denies blocked terms in content and git metadata",
    "SecretFileGuardHandler": (
        "T1 denies every read route to a protected file, and the guidance carries "
        "what a deny reason cannot: the deny-by-default framing, the honest "
        "(b)/(c)/(d) limits so an unblocked evasion is never read as permission, "
        "the secret-meta/consumer exemptions, and the no-escape-hatch doctrine"
    ),
    "FlaggableContentChannelGuardHandler": (
        "T1 denies a content-revealing git/grep command over a flaggable path, "
        "and the guidance carries what the deny reason cannot: this is a "
        "command-SHAPE guard (git status/log/add without -p stay allowed even "
        "naming a flaggable path), the config split (mode governs only the "
        "glob list; extra shapes are always additive, never a replacement), "
        "and the no-escape-hatch doctrine"
    ),
    "QuarantineArtefactReadGuardHandler": (
        "T1 denies reading a quarantined DETAIL artefact, and the guidance "
        "carries what the deny reason cannot: the two-file SUMMARY/DETAIL "
        "contract this enforces, that Write/authoring the artefact and the "
        "subagent's own git add/commit/push are deliberately unaffected, and "
        "the no-escape-hatch doctrine"
    ),
    "WriteClobberGuardHandler": (
        "T1 denies a Write that would destroy unread file contents, and the guidance "
        "carries what the deny reason cannot: that new files and Edits are never "
        "blocked, so an agent does not over-correct into avoiding Write entirely"
    ),
    "ArtifactPublishBlockerHandler": (
        "T1 denies publishing an artefact, and the guidance carries something the "
        "deny reason alone cannot: that there is deliberately NO escape hatch, so an "
        "agent does not waste turns hunting for one or try to lift the config itself"
    ),
    "SudoPipHandler": "T1 denies sudo pip install",
    "TddEnforcementHandler": "T1 denies a source file with no test file",
    "ValidateInstructionContentHandler": "T1 denies ephemeral content in CLAUDE.md",
    "WorktreeFileCopyHandler": "T1 denies copying across worktree boundaries",
    "AutoContinueStopHandler": "T1 denies a stop with no declared reason",
    "AutoApproveReadsHandler": "T1 decides a permission request outright",
    "SubagentReportSizeBlockerHandler": "T1 denies an oversized SubagentStop return",
    "DispatchDeclarationHandler": (
        "T1 strict mode denies an undeclared Task dispatch; the fire-time "
        "additionalContext alone would not teach the standing filename "
        "convention the fallback dir needs before the first dispatch"
    ),
    # -- Test 2: the advice is too late for the call it fires on ---------
    "AgentIsolationAdvisorHandler": "T2 the isolation argument is already set",
    "DaemonRestartVerifierHandler": "T2 fires on the commit the restart should precede",
    "MarkdownOrganizationHandler": "T2 the destination path is already chosen",
    "NpmCommandHandler": "T2 the npm script name is already chosen",
    "PlanNumberHelperHandler": "T2 fires on the folder scan that should never have run",
    "PlanQaCommitGateHandler": "T2 fires on the commit whose contents are already staged",
    "StagedLintGateHandler": "T2 fires on files whose staleness predates the commit",
    "PlanWorkflowHandler": "T2 the document shape is chosen before the write",
    "BashSafeModeHandler": "T2 the prelude must be written before the command runs",
    "VerificationResultGateHandler": "T2 the gating (&&/set -e) must be written before the command runs",
    "WorktreeCreateHandler": "T2 the agent name that becomes the path is already chosen",
    # -- Test 3: standing policy that decays after one delivery ----------
    "BackgroundProcessTrackerHandler": "T3 watchdog protocol outlives the command",
    "CommandHintsHandler": "T3 explains the rate-limited hint mechanism itself",
    "GoalInjectionHandler": (
        "T3 standing policy: an injected /goal is machine-marked and can never "
        "constitute human authorisation; also documents the inject-goal fallback"
    ),
    "DismissiveLanguageNitpickHandler": (
        "T3 standing norm about deflecting; the fire-time line is one sentence "
        "and the remedy (acknowledge, then fix) is a habit, not a correction. "
        "Held by the Stop twin until Plan 00237 deleted it as unreachable"
    ),
    "HedgingLanguageNitpickHandler": (
        "T3 standing norm about guessing; the section's whole argument — that "
        "deleting the hedge is WORSE than the hedge — cannot fit in the "
        "fire-time line. Held by the Stop twin until Plan 00237 deleted it"
    ),
    "IdleHousekeepingAdvisoryHandler": "T3 a mode the agent opts into and sustains",
    "RecoveryCronAdvisorHandler": "T3 cron-is-not-a-heartbeat governs the whole session",
    "StandingAuthorisationsHandler": "T3 replaying a recorded request is the whole point",
    # -- Test 3, session-scoped: state the agent must hold all session ---
    "CcySupervisorIntegrityHandler": "T3 remediation spans a restart, not one call",
    "GitUpstreamCheckerHandler": "T3 the rewritten-upstream case must never be 'fixed' by pulling",
    "HookRegistrationCheckerHandler": "T3 self-repair changes settings.json under the agent",
    "DocsQaSweepHandler": "T3 drift findings are worked through across the session",
    "ToolDisableAdvisorHandler": "T3 the named settings change awaits a user decision later",
    "PlanQaSweepHandler": "T3 drift findings are worked through across the session",
    "PlanWorkflowAssetCheckerHandler": "T3 names a provisioning command to run later",
    "ProjectHandlerLoadCheckerHandler": "T3 'your guardrails are OFF' must persist",
    "GitHooksExecutableFixerHandler": "T3 the daemon changed file permissions on your behalf",
    "MarkdownTableFormatterHandler": "T3 the daemon rewrites your .md files after every write",
    "SecretFileHygieneCheckerHandler": "T3 the remediation commands must survive to be actioned",
    "ModelFallbackDetectorHandler": (
        "T3 'your session runs a substituted model' must persist until the "
        "restart; the snapshot/tuning workflow outlives the fire-time alert"
    ),
    "FlaggableWorkAdvisorHandler": (
        "T2 the delegate-before-reading decision must be made before the tool "
        "call this fires on; the standing delegation discipline cannot fit in "
        "the once-per-path fire-time line"
    ),
    "FailsafeCronBlockageSuppressorHandler": (
        "T1 denies a delivered failsafe-cron tick while a still-valid "
        "'blocked only on human input' marker exists for the session"
    ),
}

# Handlers that correctly return None. The reason is the point: it is what a
# future auditor reads instead of re-deriving the verdict by hand.
_EXEMPT_FROM_GUIDANCE: dict[str, str] = {
    # -- Emit nothing an agent acts on -----------------------------------
    "AccountDisplayHandler": "status-line renderer, no agent-facing action",
    "ContextSidecarHandler": "status-line renderer, no agent-facing action",
    "CurrentTimeHandler": "status-line renderer, no agent-facing action",
    "DaemonStatsHandler": "status-line renderer, no agent-facing action",
    "DowngradeIndicatorHandler": "status-line renderer, no agent-facing action",
    "EnvironmentIndicatorHandler": "status-line renderer, no agent-facing action",
    "GitBranchHandler": "status-line renderer, no agent-facing action",
    "GitRepoNameHandler": "status-line renderer, no agent-facing action",
    "ModelContextHandler": "status-line renderer, no agent-facing action",
    "MultithreadIndicatorHandler": "status-line renderer, no agent-facing action",
    "StartupCleanupHandler": "status-line renderer, no agent-facing action",
    "SupervisorIndicatorHandler": "status-line renderer, no agent-facing action",
    "UpgradeNotifierHandler": "status-line renderer, no agent-facing action",
    "WorkingDirectoryHandler": "status-line renderer, no agent-facing action",
    "CompactionSignalHandler": "writes a signal file for the supervisor, not the agent",
    "MonorepoDetectorHandler": (
        "never denies (T1 no); one-shot correction delivered fully at fire-time "
        "(paste-ready projects: block), not a standing policy to hold across "
        "later decisions (T3 no)"
    ),
    "DisclosureResetPreCompactHandler": "resets internal disclosure state, no agent-facing action",
    "DisclosureResetSessionStartHandler": "resets internal disclosure state, no agent-facing action",
    "WorktreeRemoveHandler": "prunes stale registrations; nothing to do differently",
    # -- Test 4: the fire-time message already says all of it ------------
    "BritishEnglishHandler": "T4 names the exact spelling and its replacement",
    "DaemonDocsGuardHandler": "T4 one sentence at fire time carries the whole advice",
    "GitContextInjectorHandler": "T4 the injected git status IS the content",
    "GlobalNpmAdvisorHandler": "T4 never denies; the fire-time note is the whole advice",
    "WebSearchYearHandler": "T4 message already carries the year, query and alternatives",
    "GitFilemodeCheckerHandler": "T4 fires once at session start with the full remedy",
    "GitignoreSafetyCheckerHandler": "T4 fires once at session start with the full remedy",
    "OptimalConfigCheckerHandler": "T4 fires once at session start with the full remedy",
    "SuggestStatusLineHandler": "T4 fires once at session start with the full remedy",
    "VersionCheckHandler": "T4 fires once at session start with the full remedy",
    "ContractStalenessHandler": "T4 fires once at session start with the full remedy",
    "SkillOpportunityDetectorHandler": "T4 fires once per cadence with the full remedy",
    "ConfigOptimisationReminderHandler": "T4 fires once at session start with the full remedy",
    "CriticalThinkingAdvisoryHandler": "T4 the injected advisory IS the content",
    # -- Test handlers ---------------------------------------------------
}


def _project_root() -> Path:
    """Return the repository root (this file is tests/integration/<name>.py)."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _project_context() -> None:
    """Initialise ProjectContext so handlers that read it can be constructed.

    Six handlers call ``project_root()`` from ``__init__`` and raise without
    it. They must be CONSTRUCTED, not skipped — a handler that drops out of
    discovery is precisely the silent escape this suite prevents.

    Function-scoped on purpose: the root ``conftest.py`` resets the singleton
    after EVERY test, so a module-scoped setup would serve the first test in
    this file and leave the rest to fail on a torn-down context.
    """
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    if not getattr(ProjectContext, "_initialized", False):
        ProjectContext.initialize(_project_root() / ".claude" / "hooks-daemon.yaml")


def _discover_handler_classes() -> dict[str, type[Handler]]:
    """Every concrete Handler subclass under the handlers package.

    Discovered, not hardcoded — a hardcoded list is blind to exactly the new
    handler this guard exists to catch.
    """
    found: dict[str, type[Handler]] = {}
    for _finder, module_name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        module = importlib.import_module(module_name)
        for attribute_name, attribute in vars(module).items():
            if (
                inspect.isclass(attribute)
                and issubclass(attribute, Handler)
                and attribute is not Handler
                and attribute.__module__ == module.__name__
                and not getattr(attribute, "__abstractmethods__", None)
            ):
                found[attribute_name] = attribute
    return found


def _guidance_of(class_name: str) -> str | None:
    """Construct the handler and return its guidance.

    Constructor failures are raised, never swallowed: an uninstantiable
    handler is a real defect and must fail loudly here.
    """
    handler: Any = _discover_handler_classes()[class_name]()
    return handler.get_claude_md()


class TestEveryHandlerHasARecordedVerdict:
    """The completeness property. Everything else is detail."""

    def test_no_handler_is_unclassified(self) -> None:
        discovered = set(_discover_handler_classes())
        classified = set(_EARNS_GUIDANCE) | set(_EXEMPT_FROM_GUIDANCE)

        unclassified = sorted(discovered - classified)

        assert not unclassified, (
            "These handlers have no recorded get_claude_md() verdict:\n  "
            + "\n  ".join(unclassified)
            + "\n\nApply the four tests in CLAUDE/HANDLER_DEVELOPMENT.md and add each "
            "handler to _EARNS_GUIDANCE or _EXEMPT_FROM_GUIDANCE above, with a reason. "
            "`return None` is a decision that costs a future auditor real work to "
            "re-derive; the reason string is what makes it a decision rather than a "
            "deferral."
        )

    def test_no_classification_names_a_handler_that_no_longer_exists(self) -> None:
        """Also the vacuity guard for the whole suite.

        If discovery silently returned nothing — a broken import, a renamed
        package — the unclassified check above would pass on an empty set and
        the suite would be green while checking nothing. This test fails loudly
        in that case, because every classified name would look stale.
        """
        discovered = set(_discover_handler_classes())
        classified = set(_EARNS_GUIDANCE) | set(_EXEMPT_FROM_GUIDANCE)

        stale = sorted(classified - discovered)

        assert not stale, (
            f"Classified handlers that no longer exist: {stale}. Remove them — a "
            "stale entry makes the table look more complete than it is."
        )

    def test_the_two_classifications_are_disjoint(self) -> None:
        both = sorted(set(_EARNS_GUIDANCE) & set(_EXEMPT_FROM_GUIDANCE))

        assert not both, f"Handlers classified as both covered and exempt: {both}"

    @pytest.mark.parametrize(
        "class_name", sorted(set(_EARNS_GUIDANCE) | set(_EXEMPT_FROM_GUIDANCE))
    )
    def test_every_verdict_carries_a_reason(self, class_name: str) -> None:
        reason = _EARNS_GUIDANCE.get(class_name) or _EXEMPT_FROM_GUIDANCE.get(class_name) or ""

        assert reason.strip(), (
            f"{class_name} is classified with an empty reason. A bare name records "
            "that someone typed something, not that they decided anything."
        )


class TestAnExemptHandlerCannotQuietlyDeny:
    """Test 1 is the strongest test, so a `None` that defeats it needs argument.

    Added after this suite shipped, because the suite as first written could
    not have caught its own worst entry. `ValidateEslintOnWriteHandler` was
    recorded exempt on the reason that `lint_on_edit`'s section already covered
    it. Both handlers agreed with their table rows, so every check passed —
    while the exemption was wrong twice over: `lint_on_edit` lists nine
    languages and TypeScript is not one of them, and the two degrade in
    OPPOSITE directions (`lint_on_edit` ALLOWs a missing linter or a timeout;
    the ESLint handler DENIES both). The section claimed to cover it stated a
    guarantee that was false for the case it supposedly covered.

    Reading the reasons found nothing. Asking mechanically which exempt
    handlers contain a DENY path found it immediately — which is the whole
    argument for a guard over a review.

    A future handler may genuinely deny and still be exempt under Test 4. That
    is a real possibility, not an impossible one, so the remedy is an entry in
    `_EXEMPT_DESPITE_DENYING` naming the section that covers it — verified by
    reading that section, not assumed.
    """

    # Exempt handlers that CAN deny, each naming the resident section that
    # genuinely covers them. Deliberately empty: every deny-capable handler
    # currently earns its own section. An addition here should be argued.
    _EXEMPT_DESPITE_DENYING: ClassVar[dict[str, str]] = {}

    @staticmethod
    def _module_can_deny(handler_class: type[Handler]) -> bool:
        """Whether the handler's own module names a DENY decision.

        Deliberately a static check on the module source, not a call into
        ``handle()`` — constructing every handler with inputs that reach its
        deny branch is not tractable, and a guard that is hard to run is a
        guard that gets deleted.

        Its reach, measured rather than assumed: all 33 handlers currently
        recorded as passing Test 1 are detected, so there are no false
        negatives across the known deniers. It would miss a handler that denies
        via a helper in another module, or through a decision held in a
        variable. Neither shape exists today; if one appears, this returns
        False and the handler escapes the check — so a new deny path that does
        not read ``Decision.DENY`` in its own module needs the classification
        made by hand.
        """
        module = inspect.getmodule(handler_class)
        source = inspect.getsource(module) if module else ""
        return "Decision.DENY" in source

    def test_no_exempt_handler_has_an_unargued_deny_path(self) -> None:
        classes = _discover_handler_classes()

        offenders = sorted(
            name
            for name in _EXEMPT_FROM_GUIDANCE
            if name not in self._EXEMPT_DESPITE_DENYING and self._module_can_deny(classes[name])
        )

        assert not offenders, (
            "These handlers are recorded as exempt from resident guidance but can "
            f"DENY a tool call: {offenders}.\n\n"
            "Test 1 says a denial burns a turn and cancels every sibling tool call, "
            "so guidance that prevents one has already paid for itself. Either move "
            "the handler to _EARNS_GUIDANCE and write the section, or add it to "
            "_EXEMPT_DESPITE_DENYING naming the resident section that covers it — "
            "having READ that section and confirmed it covers this handler's "
            "languages AND its failure behaviour. That check is the one that was "
            "skipped last time."
        )

    def test_the_deny_exemption_list_names_real_handlers(self) -> None:
        discovered = set(_discover_handler_classes())

        stale = sorted(set(self._EXEMPT_DESPITE_DENYING) - discovered)

        assert not stale, f"_EXEMPT_DESPITE_DENYING names handlers that do not exist: {stale}"


class TestTheVerdictsMatchReality:
    """A table that drifts from the code is worse than no table."""

    @pytest.mark.parametrize("class_name", sorted(_EARNS_GUIDANCE))
    def test_a_covered_handler_actually_returns_guidance(self, class_name: str) -> None:
        guidance = _guidance_of(class_name)

        assert guidance is not None and guidance.strip(), (
            f"{class_name} is recorded as earning resident guidance "
            f"({_EARNS_GUIDANCE[class_name]}) but get_claude_md() returned nothing. "
            "Either implement it or move the handler to _EXEMPT_FROM_GUIDANCE with "
            "the reason it no longer earns a section."
        )

    @pytest.mark.parametrize("class_name", sorted(_EXEMPT_FROM_GUIDANCE))
    def test_an_exempt_handler_actually_returns_none(self, class_name: str) -> None:
        guidance = _guidance_of(class_name)

        assert guidance is None, (
            f"{class_name} is recorded as exempt ({_EXEMPT_FROM_GUIDANCE[class_name]}) "
            "but get_claude_md() now returns content. Every client project pays for "
            "that content on every session. Move it to _EARNS_GUIDANCE naming the test "
            "it passes, or remove the guidance."
        )


class TestGuidanceActuallyReachesClaudeMd:
    """Returning a section is not the same as the section arriving.

    Everything above this class checks what a handler RETURNS. Plan 00237
    proved that is only half the property: the language detectors' guidance was
    moved onto the `nitpick` handlers — live, enabled, returning a full section
    that `test_a_covered_handler_actually_returns_guidance` was perfectly happy
    with — and the next daemon restart DELETED both sections from CLAUDE.md and
    auto-committed the deletion. Pseudo-event handlers dispatch through
    `PseudoEventDispatcher`, and the injector walked only `EventRouter`'s
    chains, so it never saw them.

    Every check in this file passed throughout. So did the whole QA suite. The
    only visible symptom was a commit titled "Auto: hooks daemon regenerated
    CLAUDE.md handler guidance" whose diff was 37 deletions and no additions.

    `check_repo_hygiene.py`'s `orphaned-handler-guidance` rule covers the
    OPPOSITE direction — a section in CLAUDE.md with no handler behind it. This
    is the missing half: a handler with guidance and no section. Both
    directions are needed; neither implies the other.
    """

    def _markers_in_claude_md(self) -> set[str]:
        """Handler display names recorded in the repo's own CLAUDE.md.

        Read through the injector's own reader, never a local regex — a second
        copy of the marker format is the copy that silently stops matching.
        """
        from claude_code_hooks_daemon.core.claude_md_injector import handler_names_in_guidance

        claude_md = _project_root() / "CLAUDE.md"
        return set(handler_names_in_guidance(claude_md.read_text(encoding="utf-8")))

    def test_the_markers_are_readable_at_all(self) -> None:
        """Vacuity guard: an empty marker set would make the next test pass blind."""
        assert self._markers_in_claude_md(), (
            "No handler provenance markers found in CLAUDE.md. Either the guidance "
            "block is missing entirely or the marker format changed — in both cases "
            "the coverage check below would pass while checking nothing."
        )

    def test_every_earning_handler_has_a_section_in_claude_md(self) -> None:
        classes = _discover_handler_classes()
        present = self._markers_in_claude_md()

        missing = sorted(
            f"{class_name} (name={classes[class_name]().name})"
            for class_name in _EARNS_GUIDANCE
            if classes[class_name]().name not in present
        )

        assert not missing, (
            "These handlers are recorded as earning resident guidance, and their "
            "get_claude_md() returns it, but no section for them reached this "
            "repository's CLAUDE.md:\n  " + "\n  ".join(missing) + "\n\n"
            "The guidance is being produced and dropped. Check that the handler is "
            "reachable by ClaudeMdInjector — the injector is handed a list built in "
            "DaemonController.initialise(), and a handler registered anywhere other "
            "than an EventRouter chain (a pseudo-event, for instance) has to be added "
            "to that list explicitly. Restart the daemon after fixing, since the block "
            "is only regenerated on startup.\n"
            "If the handler is instead DISABLED in this project's config, that is "
            "worth fixing too: this repo dogfoods its own handlers, so an earning "
            "handler that is off here is untested guidance."
        )
