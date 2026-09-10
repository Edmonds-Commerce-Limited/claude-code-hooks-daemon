"""LspNoiseCheckerHandler - a project's LSP diagnostics must be signal.

Plan 00368 Task 2.2. Claude Code injects a language server's diagnostics
into the agent's context after every edit. When the server analyses trees
that are not this project's code - the daemon's own runtime directory with
its linked worktrees and venvs, the plan archive's probes, vendored and
build output, the vendored remote-docs tree - those trees' half-built or
deliberately broken files are reported as defects HERE, by the thousand,
and the agent learns to skim the stream. A skimmed stream reports nothing:
"if there's noise, there's no signal and LSP is pointless".

**Every supported language, not Python alone** (owner ruling, Plan 00368):
this handler is a thin orchestrator with ZERO language-specific logic - see
``strategies/lsp_noise/CLAUDE.md`` for the Strategy Pattern this follows,
one ``LspNoiseStrategy`` per language (Python, TypeScript/JavaScript, Go,
Rust, PHP), each owning how ITS language server learns what is not project
code, verified against Claude Code's own marketplace plugin configs and
each tool's own docs, never assumed.

Two checks per relevant language, both advisory, both with the exact fix:

``R-LSP-CONFIG-EXCLUDE``
    The tree the daemon KNOWS is not project code (its runtime dir, the
    plan directory, vendored/build directories, the remote-docs tree - the
    ``required_excludes()`` set below, derived from ``DaemonPath``, the
    plan-workflow config and ``constants.layout``, never hand-typed) is not
    excluded from that language's server. Each strategy owns the fix
    wording for its own language's mechanism.

``R-LSP-SERVER-STALE``
    A running language-server process (matched by the relevant strategy's
    ``process_names``) started BEFORE the file anchoring that language's
    check was last written, so it is still analysing the old scope.

Silent on a resumed session, and silent for a language whose toolchain
marker is not present in the project.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psutil

from claude_code_hooks_daemon.constants import DaemonPath, HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.strategies.lsp_noise.protocol import LspNoiseStrategy
from claude_code_hooks_daemon.strategies.lsp_noise.registry import LspNoiseStrategyRegistry
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

_ANY_DEPTH_PREFIX: Final[str] = "**/"


@dataclass(frozen=True, slots=True)
class RunningServer:
    """One live language-server process, and which known names matched it."""

    pid: int
    started_at: float
    matched_names: frozenset[str]


def running_language_servers(known_names: frozenset[str]) -> list[RunningServer]:
    """Every live process whose cmdline matches one of ``known_names``.

    Scanned ONCE per session-start check across every registered language,
    not once per language - the process table is scanned a single time and
    each strategy filters the result by its own ``process_names``. A
    process that vanishes mid-scan is skipped, not raised: this feeds a
    session-start advisory, and a race with a process exiting is the
    ordinary state of a process table, not an error.
    """
    found: list[RunningServer] = []
    for proc in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            info: dict[str, Any] = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            logger.debug("process vanished during langserver scan: %s", exc)
            continue
        cmdline = " ".join(str(part) for part in (info.get("cmdline") or []))
        matched = frozenset(name for name in known_names if name in cmdline)
        if matched:
            found.append(
                RunningServer(
                    pid=int(info["pid"]),
                    started_at=float(info["create_time"]),
                    matched_names=matched,
                )
            )
    return found


def required_excludes(layout: ProjectLayout | None) -> frozenset[str]:
    """Every tree no language's server should analyse, from what the daemon already knows.

    Nothing here is typed by hand: the runtime dir is the daemon's path
    constant, the plan and remote-docs trees come from the configured layout
    (built-in defaults when no layout has been injected), and the
    vendored/build names are the reviewed core set, at any depth. Shared by
    every language strategy - this is daemon knowledge, not a language's.
    """
    resolved = layout if layout is not None else ProjectLayout.built_in_default()
    entries = {DaemonPath.UNTRACKED_DIR, resolved.plan_dir, resolved.remote_docs_dir}
    entries.update(f"{_ANY_DEPTH_PREFIX}{name}" for name in CORE_VENDORED_BUILD_DIR_NAMES)
    return frozenset(entries)


class LspNoiseCheckerHandler(SessionStartHandlerBase):
    """Advise when a project's LSP config lets noise into the diagnostics stream.

    Thin orchestrator: every language-specific check lives in a
    ``LspNoiseStrategy`` (``strategies/lsp_noise/``). Reports a missing
    exclude for a tree the daemon knows is not project code, and a language
    server older than the file that check is anchored to. Advisory only.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.LSP_NOISE_CHECKER,
            priority=Priority.LSP_NOISE_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )
        # Injection point for tests; production scans the process table.
        self.process_reader: Callable[[frozenset[str]], list[RunningServer]] = (
            running_language_servers
        )
        self._registry = LspNoiseStrategyRegistry.create_default()
        self._exclude_rule = Rule(
            rule_id=RuleID.LSP_CONFIG_EXCLUDE,
            blocked=(
                "a language server config with no exclude for a tree that is not project code"
            ),
            why=(
                "The language server reports other checkouts' and fixtures' "
                "defects against this one, and a noisy stream is skimmed"
            ),
            fix="Add the listed exclude entries (the advisory prints them ready to use)",
            verbose=(
                "ADVISORY (never blocks). Claude Code injects a language server's "
                "diagnostics after every edit. Without an exclude for the daemon's "
                "runtime directory, the plan directory, vendored/build directories and "
                "the remote-docs tree, the server analyses linked worktrees' half-built "
                "branches, venvs, archived probes and deliberately broken fixtures, "
                "and reports them as defects in THIS checkout by the thousand. An "
                "agent learns to skim that stream, and a skimmed stream reports "
                "nothing: fix the noise at its source, never ignore it.\n\n"
                "REQUIRED ACTION:\n"
                "  Each language's finding names its own fix - a config file's "
                "`exclude` key, a module or workspace boundary, or (when the tool takes "
                "no project-level exclude at all) the exact client-settings snippet to "
                "add. Then end the running language server so it re-reads the config "
                "(R-LSP-SERVER-STALE)."
            ),
        )
        self._stale_rule = Rule(
            rule_id=RuleID.LSP_SERVER_STALE,
            blocked="a running language server older than the config file its check is anchored to",
            why="It is still analysing the scope the OLD config declared",
            fix="End the named process (the harness respawns it on the next LSP use)",
            verbose=(
                "ADVISORY (never blocks). A language server reads its configuration "
                "when it starts and never again, so a config change made after it "
                "started - a new exclude, a workspace boundary - changes nothing until "
                "the process is replaced. The advisory names the pid(s) whose start "
                "time predates the anchoring file's last write, and the command that "
                "ends that language's process.\n\n"
                "REQUIRED ACTION:\n"
                "  End the named pid (the exact command is in the advisory). It is "
                "safe: the harness respawns a fresh server, which reads the current "
                "config, on the next LSP request."
            ),
        )

    # ------------------------------------------------------------------
    # Handler protocol
    # ------------------------------------------------------------------

    def get_rules(self) -> list[Rule]:
        """Both advisory rules, so `explain-rule` and the CLAUDE.md table know them."""
        return [self._exclude_rule, self._stale_rule]

    def get_relevance(self, context: RelevanceContext) -> Relevance:
        return Relevance.when(
            self._any_strategy_relevant(context),
            present="a supported language's toolchain marker is at the project root",
            absent="no supported language's toolchain marker at the project root",
        )

    def _any_strategy_relevant(self, context: RelevanceContext) -> bool:
        return any(strategy.is_relevant(context) for strategy in self._registry.strategies)

    def _get_project_root(self) -> Path | None:
        try:
            return ProjectContext.project_root()
        except RuntimeError as exc:
            logger.debug("ProjectContext not initialised; skipping LSP noise check: %s", exc)
            return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if is_resume_session(hook_input):
            return False
        root = self._get_project_root()
        if root is None:
            return False
        return self._any_strategy_relevant(RelevanceContext.probe(root))

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        root = self._get_project_root()
        if root is None:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        context = RelevanceContext.probe(root)
        required = required_excludes(self._project_layout)
        relevant = [s for s in self._registry.strategies if s.is_relevant(context)]
        known_names = frozenset(name for s in relevant for name in s.process_names)
        servers = self.process_reader(known_names) if relevant else []

        lines: list[str] = []
        for strategy in relevant:
            exclude_lines, config_path = strategy.exclude_finding(root, required)
            lines.extend(exclude_lines)
            lines.extend(self._stale_finding(strategy, config_path, servers))
        return AdvisoryResult(decision=Decision.ALLOW, context=lines)

    # ------------------------------------------------------------------
    # Check (b): a stale server, generalised across every language
    # ------------------------------------------------------------------

    def _stale_finding(
        self,
        strategy: LspNoiseStrategy,
        config_path: Path | None,
        servers: list[RunningServer],
    ) -> list[str]:
        if config_path is None:
            return []
        try:
            config_mtime = config_path.stat().st_mtime
        except OSError as exc:
            logger.debug("could not stat %s for staleness: %s", config_path, exc)
            return []
        own_names = set(strategy.process_names)
        stale = [s for s in servers if s.matched_names & own_names and s.started_at < config_mtime]
        if not stale:
            return []
        pids = ", ".join(str(s.pid) for s in stale)
        process_label = "/".join(strategy.process_names)
        return [
            f"⚠️  LSP NOISE [{RuleID.LSP_SERVER_STALE}] ({strategy.language_name}): "
            f"{len(stale)} running {process_label} process(es) (pid {pids}) started "
            f"before {config_path.name} was last written, so they are analysing the "
            "OLD scope.",
            "",
            f"Fix: end the process, e.g. pkill -f '[{process_label[0]}]{process_label[1:]}' "
            "(bracketed so the pattern cannot match the shell running it); the harness "
            "respawns a fresh server, which reads the current config, on the next LSP use.",
            "",
        ]

    # ------------------------------------------------------------------
    # Resident guidance and acceptance tests
    # ------------------------------------------------------------------

    def get_claude_md(self) -> str | None:
        languages = ", ".join(self._registry.language_names)
        return (
            "## lsp_noise_checker — LSP output must be signal\n"
            "\n"
            "On a new session this handler checks, for every supported language "
            f"present ({languages}), that its server's noise-exclusion mechanism "
            "covers every tree the daemon knows is not project code (its runtime "
            "dir, the plan directory, vendored/build dirs, the remote-docs tree), "
            "and that no matching language-server process predates that check's "
            "anchor file. When it reports, FIX THE NOISE SOURCE — never skim the "
            "diagnostics stream. A stream with noise in it trains you to skip "
            "real defects, which is the same as having no LSP at all.\n"
            "\n"
            f"- `{RuleID.LSP_CONFIG_EXCLUDE}`: apply the printed fix for that "
            "language — a config file's `exclude` key, a module or workspace "
            "boundary, or a client-settings snippet.\n"
            f"- `{RuleID.LSP_SERVER_STALE}`: end the named process; the harness "
            "respawns a fresh one on the next LSP use.\n"
            "\n"
            "A diagnostic that survives both is real: read it and fix the code, "
            "never with a suppression comment or a rule downgrade.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        tests: list[Any] = []
        for strategy in self._registry.strategies:
            tests.extend(strategy.get_acceptance_tests())
        return tests
