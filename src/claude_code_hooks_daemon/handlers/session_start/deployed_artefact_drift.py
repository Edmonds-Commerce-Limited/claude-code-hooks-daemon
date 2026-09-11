"""DeployedArtefactDriftHandler — report a deployed artefact that no longer
matches the template it came from (Plan 00377 N6).

Daemon-owned files deployed into a project — the agents under
``.claude/agents/``, the core documents under ``<docs>/core/``, and the plan
tooling (``mkplan.bash``, ``_planlib.inc.bash``) — are refreshed by install and
upgrade. Between those events a template can move on while the deployed copy
stays behind, and nothing said so: Plan 00377 N4 and N5 made such a copy
REPAIRABLE (``agents install --force``, ``deploy-core-docs``) without making it
VISIBLE. Measured while fixing N5 — the same stale header sentence was sitting
in `mkplan.bash` AND in a deployed agent, unreported.

**Presence is the signal.** Only artefacts actually on disk are compared, which
is what keeps this handler quiet where it should be:

* A core document whose gating config is off is never deployed, so it is absent
  rather than drifted. Asking the config instead would re-derive a fact the
  filesystem already states, and getting that backwards is exactly what the N5
  test fixture did.
* An ABSENT ``mkplan.bash`` is ``plan_workflow_asset_checker``'s report. Two
  handlers shouting about one project teaches the reader to skim both.

Ownership is what makes the comparison meaningful, and it differs by surface:

* Core docs and the plan tooling are overwritten UNCONDITIONALLY on every
  deploy ("overwritten on every upgrade … to guarantee audit fixes reach the
  field"), so nothing protects a local edit and ``deployed != template`` IS
  drift, with no version ledger needed.
* Agents are different: a customised copy is deliberately never clobbered, so
  the question "did the user edit this, or did the template move on?" is real.
  ``classify_agent`` answers it from the revision ledger, and the two answers
  get different remediations — a plain install for a pristine-but-old copy, and
  the explicit ``--force`` escape for a customised one, because naming the
  refusing command alone is the circular remediation N4 fixed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.install.agent_assets import (
    AGENTS_DIR_PARTS,
    SHIPPED_AGENTS,
    AgentAssetSpec,
    AgentAssetState,
    classify_agent,
)
from claude_code_hooks_daemon.install.core_docs import (
    CORE_DOCS,
    CORE_DOCS_DIR,
    CORE_SUFFIX,
    core_template_path,
)
from claude_code_hooks_daemon.install.plan_workflow import (
    MKPLAN_SCRIPT_NAME,
    PLANLIB_SCRIPT_NAME,
    mkplan_template_path,
    planlib_template_path,
)
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
)
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

#: Where the plan tooling lands. Both files are daemon-owned and rewritten on
#: every deploy, so a difference is drift rather than a protected local edit.
_PLAN_DIR_PARTS: Final[tuple[str, ...]] = ("CLAUDE", "Plan")


class DeployedArtefactDriftHandler(SessionStartHandlerBase):
    """Advise when a deployed daemon-owned file differs from its template."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DEPLOYED_ARTEFACT_DRIFT,
            priority=Priority.DEPLOYED_ARTEFACT_DRIFT,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        try:
            project_root = ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; skipping drift check")
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        drifted = [
            *self._drifted_agents(project_root),
            *self._drifted_core_docs(project_root),
            *self._drifted_plan_tooling(project_root),
        ]
        if not drifted:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        context = [
            "⚠️  DEPLOYED ARTEFACT DRIFT: a daemon-owned file no longer matches "
            "the template it was deployed from.",
            "",
            "These files are refreshed by install and upgrade. Until then the "
            "deployed copy is what your tools actually read, so it is worth "
            "knowing it is not the shipped one.",
            "",
        ]
        context.extend(f"  ⚠️  {entry}" for entry in drifted)
        return AdvisoryResult(decision=Decision.ALLOW, context=context)

    @staticmethod
    def _drifted_agents(project_root: Path) -> list[str]:
        """Agents, classified against the revision ledger rather than compared.

        The ledger is what separates "pristine but old" from "you edited this",
        and the two need different remediations. A plain install REFUSES a
        customised copy, so offering only that command would send the reader
        round the loop N4 closed.
        """
        entries: list[str] = []
        for spec in SHIPPED_AGENTS:
            state = classify_agent(spec, project_root)
            if state is AgentAssetState.OUTDATED:
                entries.append(
                    f"{DeployedArtefactDriftHandler._agent_rel(spec)} — a previously "
                    f"shipped revision, safe to refresh: "
                    f"`{daemon_cli_command(f'agents install {spec.name}')}`"
                )
            elif state is AgentAssetState.CUSTOMISED:
                entries.append(
                    f"{DeployedArtefactDriftHandler._agent_rel(spec)} — does not match "
                    f"any shipped revision, so it is either your edit or an "
                    f"unrecorded one. A plain install REFUSES it; to discard it: "
                    f"`{daemon_cli_command(f'agents install {spec.name} --force')}`"
                )
        return entries

    @staticmethod
    def _agent_rel(spec: AgentAssetSpec) -> str:
        return f"{'/'.join(AGENTS_DIR_PARTS)}/{spec.name}.md"

    @staticmethod
    def _drifted_core_docs(project_root: Path) -> list[str]:
        entries: list[str] = []
        for doc in CORE_DOCS:
            filename = f"{doc.name}{CORE_SUFFIX}"
            deployed = project_root / CORE_DOCS_DIR / filename
            template = core_template_path(doc.name)
            if not deployed.is_file() or not template.is_file():
                continue
            if deployed.read_text() != template.read_text():
                entries.append(
                    f"{CORE_DOCS_DIR}/{filename} — daemon-owned, rewritten on every "
                    f"deploy: `{daemon_cli_command('deploy-core-docs')}`"
                )
        return entries

    @staticmethod
    def _drifted_plan_tooling(project_root: Path) -> list[str]:
        entries: list[str] = []
        plan_dir = project_root.joinpath(*_PLAN_DIR_PARTS)
        pairs = (
            (MKPLAN_SCRIPT_NAME, mkplan_template_path()),
            (PLANLIB_SCRIPT_NAME, planlib_template_path()),
        )
        for filename, template in pairs:
            deployed = plan_dir / filename
            if not deployed.is_file() or not template.is_file():
                continue
            if deployed.read_text() != template.read_text():
                entries.append(
                    f"{'/'.join(_PLAN_DIR_PARTS)}/{filename} — daemon-owned, rewritten "
                    f"on every deploy: `{daemon_cli_command('deploy-plan-workflow')}`"
                )
        return entries

    def get_claude_md(self) -> str | None:
        return (
            "## deployed_artefact_drift — a deployed file has moved away from its template\n"
            "\n"
            "At session start, every daemon-owned file this project has deployed is "
            "compared with the template it came from, and any difference is reported "
            "(it never blocks). This closes the gap where a stale deployed copy was "
            "repairable but invisible.\n"
            "\n"
            "**Only files that are PRESENT are compared.** A core document whose "
            "gating config is off was never deployed, so it is absent by design and "
            "is never reported; an absent `mkplan.bash` is "
            "`plan_workflow_asset_checker`'s report, not this one's.\n"
            "\n"
            "**Fix** — each entry names its own repair, because they differ:\n"
            "\n"
            "```\n"
            f"{daemon_cli_command_for_docs('deploy-core-docs')}\n"
            f"{daemon_cli_command_for_docs('deploy-plan-workflow')}\n"
            f"{daemon_cli_command_for_docs('agents install <name>')}\n"
            "```\n"
            "\n"
            "Core documents and the plan tooling are rewritten unconditionally, so a "
            "difference there is always drift. A drifted AGENT is reported differently "
            "depending on what the revision ledger says: a previously shipped revision "
            "is safe to refresh with a plain install, while a copy matching no shipped "
            "revision is either your edit or an unrecorded one — a plain install "
            "refuses it, and `--force` is named explicitly so the advice is not the "
            "command that just refused."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="deployed artefact drift - silent when nothing has drifted",
                command='echo "test"',
                description=(
                    "In a project whose deployed daemon-owned files match their "
                    "templates, SessionStart carries no drift block. Verified via "
                    "the session, like the other SessionStart advisories."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only comparison of deployed files against templates",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
            ),
        ]
