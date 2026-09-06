"""Plan workflow bootstrapping for installer.

Creates the CLAUDE/Plan/ directory structure with a starter README.md
and lifecycle CLAUDE.md so new projects can use structured plan-based
development immediately after install.
"""

import difflib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.install.agent_assets import (
    AGENTS_DIR_PARTS as _AGENTS_DIR_PARTS,
)
from claude_code_hooks_daemon.install.agent_assets import (
    DEDUPE_AGENT_NAME as _DEDUPE_AGENT_NAME,
)
from claude_code_hooks_daemon.install.agent_assets import (
    AgentAction,
    deploy_agent,
    spec_by_name,
    spec_source_path,
)

logger = logging.getLogger(__name__)

_DEFAULT_PLAN_DIR_NAME: Final[str] = "CLAUDE/Plan"

_COMPLETED_DIR_NAME: Final[str] = "Completed"

_TEMPLATES_DIR_NAME: Final[str] = "templates"
MKPLAN_SCRIPT_NAME: Final[str] = "mkplan.bash"
# Owner rwx, group/other rx — least-privilege executable (matches deploy_skills).
_MKPLAN_MODE: Final[int] = 0o755

# planlib operator-script safety library (Plan 00213 Phase 2): a SOURCED bash
# library, never executed directly, so it gets a SEPARATE, less-privileged
# mode constant rather than reusing _MKPLAN_MODE — an execute bit on a file
# nobody should run invites exactly that.
PLANLIB_SCRIPT_NAME: Final[str] = "_planlib.inc.bash"
# Owner+group+other read/write, no execute — matches CLAUDE.md's "regular
# files: chmod 644" guidance.
_PLANLIB_MODE: Final[int] = 0o644

# Tracked, client-owned plan template consumed by mkplan.bash (Plan 00144
# Phase 5). Seeded from the bundled default when absent; NEVER overwritten.
PLAN_TEMPLATE_NAME: Final[str] = "_TEMPLATE_.md"
# Daemon-owned snapshot of the default template as of the last deploy —
# diffing it against the new bundled default surfaces upstream template
# changes on upgrade so projects can adopt them into their own template.
TEMPLATE_SNAPSHOT_NAME: Final[str] = ".plan-template-default.md"

# Cap the surfaced diff so a heavily-reworked default cannot flood messages.
_TEMPLATE_DIFF_MAX_LINES: Final[int] = 40

# Journal assets (Plan 00163 Phase 4). Both are CLIENT-owned — seeded from the
# bundle when absent, NEVER overwritten. The presence of ``_JOURNAL_TEMPLATE_.md``
# is the "this project journals" marker that gates mkplan.bash's JOURNAL/
# scaffolding; ``PlanJournalling.md`` is the copy-and-customise reference doc.
JOURNAL_TEMPLATE_NAME: Final[str] = "_JOURNAL_TEMPLATE_.md"
PLAN_JOURNALLING_DOC_NAME: Final[str] = "PlanJournalling.md"

# Plan-dedupe scout agent (Plan 00216). A specialist sub-agent that reads the
# titles and overviews of still-live plans and reports ones already covering
# proposed work.
#
# Why an agent rather than a `plan_qa` rule: Plan 00216 Phase 1 measured the
# deterministic alternative against this repository's own 215 plans and it
# does not exist. The reliable GitHub-issue spelling finds ZERO shared pairs
# and would have missed the duplication that motivated the work; the loose
# `#N` spelling is 34/35 false positives ("resolver #1", "Bug #3", "the #1
# correctness risk"); the supporting-document signal is dominated by
# project-wide filenames and by CORRECT prior-art citations. Duplicates share
# SUBJECT, not citations, which needs a reader.
#
# DAEMON-owned and, since Plan 00279, deployed through the generic
# agent-asset subsystem (`install/agent_assets.py`), which refreshes pristine
# copies on every deploy like `mkplan.bash` and the skills but never clobbers
# a customised file. The name/location constants are re-exported here for
# back-compat; the subsystem is their single source of truth.
DEDUPE_AGENT_NAME: Final[str] = _DEDUPE_AGENT_NAME
AGENTS_DIR_PARTS: Final[tuple[str, str]] = _AGENTS_DIR_PARTS


def mkplan_template_path() -> Path:
    """Absolute path to the canonical bundled ``mkplan.bash`` template.

    This is the single source of truth for the plan-scaffolding script; the
    installer copies it into each project's plan directory on install/upgrade.
    """
    return Path(__file__).resolve().parent / _TEMPLATES_DIR_NAME / MKPLAN_SCRIPT_NAME


def planlib_template_path() -> Path:
    """Absolute path to the canonical bundled ``_planlib.inc.bash`` library.

    Single source of truth for the planlib operator-script safety library
    (Plan 00213 Phase 2); the installer copies it into each project's plan
    directory when ``plan_workflow.scripts.enabled`` is true.
    """
    return Path(__file__).resolve().parent / _TEMPLATES_DIR_NAME / PLANLIB_SCRIPT_NAME


def plan_template_default_path() -> Path:
    """Absolute path to the bundled default plan template (``_TEMPLATE_.md``)."""
    return Path(__file__).resolve().parent / _TEMPLATES_DIR_NAME / PLAN_TEMPLATE_NAME


def journal_template_path() -> Path:
    """Absolute path to the bundled ``_JOURNAL_TEMPLATE_.md`` (Plan 00163)."""
    return Path(__file__).resolve().parent / _TEMPLATES_DIR_NAME / JOURNAL_TEMPLATE_NAME


def plan_journalling_doc_path() -> Path:
    """Absolute path to the bundled ``PlanJournalling.md`` reference (Plan 00163)."""
    return Path(__file__).resolve().parent / _TEMPLATES_DIR_NAME / PLAN_JOURNALLING_DOC_NAME


def dedupe_agent_template_path() -> Path:
    """Absolute path to the bundled plan-dedupe scout agent (Plan 00216).

    Since Plan 00279 the bundled file lives in the agent-asset subsystem's
    source directory; this helper delegates so the path has one owner.
    """
    return spec_source_path(spec_by_name(DEDUPE_AGENT_NAME))


_README_TEMPLATE: Final[str] = """\
# Plans Index

Structured plan-based development tracking. Each plan lives in a numbered
folder (e.g. `00001-feature-name/`) with a `PLAN.md` file.

## Plan Numbering

- Plans use 5-digit zero-padded sequential numbers: `00001-`, `00002-`, etc.
- Use kebab-case for folder names: `00001-add-authentication/`

## Active Plans

_No active plans yet._

## Completed Plans

_No completed plans yet._

## Statistics

- **Total**: 0
- **Active**: 0
- **Completed**: 0
"""

_CLAUDE_MD_TEMPLATE: Final[str] = """\
# Plan Lifecycle

## Directory Structure

```
CLAUDE/Plan/
  README.md              # Index of all plans (this file's parent)
  CLAUDE.md              # This file - lifecycle instructions
  NNNNN-description/     # Active plans (5-digit zero-padded)
    PLAN.md              # Plan document with tasks and status
  Completed/
    NNNNN-description/   # Completed plans (moved here when done)
```

## Plan Lifecycle

### 1. Create

- Create folder: `CLAUDE/Plan/NNNNN-description/`
- Write `PLAN.md` with tasks, goals, and status
- Add entry to `README.md` under **Active Plans**

### 2. Execute

- Work through tasks
- Update task status in `PLAN.md` as you go
- Reference plan in commits: `Plan NNNNN: Description`

### 3. Complete

When all tasks are done:

1. Update plan status to `Complete` (cite the delivery commit hash, not a date)
2. Move folder to `CLAUDE/Plan/Completed/NNNNN-description/`
3. Update `README.md`: remove from Active, add to Completed, update stats
4. Commit the move

```bash
git mv CLAUDE/Plan/NNNNN-desc CLAUDE/Plan/Completed/NNNNN-desc
```
"""


@dataclass
class BootstrapResult:
    """Result of plan workflow bootstrapping."""

    success: bool = True
    skipped_readme: bool = False
    skipped_claude_md: bool = False
    deployed_mkplan: bool = False
    deployed_planlib: bool = False
    created_template: bool = False
    template_default_changed: bool = False
    created_journal_template: bool = False
    created_journalling_doc: bool = False
    deployed_dedupe_agent: bool = False
    messages: list[str] = field(default_factory=list)


def bootstrap_plan_workflow(
    project_root: Path,
    plan_dir_name: str = _DEFAULT_PLAN_DIR_NAME,
    deploy_scripts_library: bool = False,
) -> BootstrapResult:
    """Bootstrap the plan directory structure for a project.

    Creates (under ``plan_dir_name``, default ``CLAUDE/Plan``):
    - the plan directory
    - the ``Completed/`` subdirectory
    - ``README.md`` (plan index template) — skipped if it already exists
    - ``CLAUDE.md`` (lifecycle instructions) — skipped if it already exists
    - ``mkplan.bash`` (the next-plan scaffolding script) — daemon-owned tooling,
      overwritten on every run so audit fixes reach existing installs
    - ``_planlib.inc.bash`` (Plan 00213 Phase 2) — ONLY when
      ``deploy_scripts_library`` is true, since it is a separate opt-in on top
      of the plan workflow itself (``plan_workflow.scripts.enabled``)

    Client content (README/CLAUDE.md) is never overwritten; the daemon-owned
    ``mkplan.bash`` and ``_planlib.inc.bash`` are overwritten on every run,
    matching how skill scripts and hook wrappers are re-deployed.

    Deployment on install/upgrade is gated by config and driven through
    :func:`deploy_plan_workflow_if_enabled` (the single decision site wired into
    ``install_version.sh`` and both ``upgrade_version.sh`` paths). This function
    performs the unconditional bootstrap once that gate has decided to run.

    Args:
        project_root: Absolute path to the project root
        plan_dir_name: Plan directory relative to project root. Defaults to
            ``CLAUDE/Plan`` but MUST be passed the configured
            ``track_plans_in_project`` value so the bootstrap honours a project
            that tracks plans elsewhere (single source of truth).
        deploy_scripts_library: Whether to also deploy ``_planlib.inc.bash``
            (Plan 00213 Phase 2). Callers MUST pass the configured
            ``plan_workflow.scripts.enabled`` value — defaults to False so a
            direct caller (e.g. a test, or a caller unaware of the option)
            never deploys it by accident.
    Note:
        Core documents are NOT deployed from here. They are gated per document
        on the subsystem whose guidance names each one (``install/core_docs.py``
        and its own ``deploy_core_docs_if_enabled`` decision site), because
        ``plan_workflow.enabled`` is opt-in and defaults to False — hanging
        them off this bootstrap left a stock install with no
        ``CLAUDE/Worktree.md`` while ``worktree_file_copy`` went on naming it.

    Returns:
        BootstrapResult with success status and messages
    """
    result = BootstrapResult()
    plan_dir = project_root / plan_dir_name
    completed_dir = plan_dir / _COMPLETED_DIR_NAME

    # Create directories
    plan_dir.mkdir(parents=True, exist_ok=True)
    result.messages.append(f"Created {plan_dir_name}/")

    completed_dir.mkdir(exist_ok=True)
    result.messages.append(f"Created {plan_dir_name}/{_COMPLETED_DIR_NAME}/")

    # Create README.md (skip if exists)
    readme_path = plan_dir / "README.md"
    if readme_path.exists():
        result.skipped_readme = True
        result.messages.append("README.md already exists (skipped)")
        logger.info("Skipping existing %s", readme_path)
    else:
        readme_path.write_text(_README_TEMPLATE)
        result.messages.append("Created README.md (plan index)")
        logger.info("Created %s", readme_path)

    # Create CLAUDE.md (skip if exists)
    claude_md_path = plan_dir / "CLAUDE.md"
    if claude_md_path.exists():
        result.skipped_claude_md = True
        result.messages.append("CLAUDE.md already exists (skipped)")
        logger.info("Skipping existing %s", claude_md_path)
    else:
        claude_md_path.write_text(_CLAUDE_MD_TEMPLATE)
        result.messages.append("Created CLAUDE.md (lifecycle instructions)")
        logger.info("Created %s", claude_md_path)

    # Deploy mkplan.bash (daemon-owned: overwrite on every run + exec bit)
    _deploy_mkplan(plan_dir, result)

    # Deploy _planlib.inc.bash (Plan 00213 Phase 2) -- opt-in on top of the
    # plan workflow itself, so only when the caller (deploy_plan_workflow_if_
    # enabled, reading plan_workflow.scripts.enabled) asks for it.
    if deploy_scripts_library:
        _deploy_planlib(plan_dir, result)

    # Seed the client-owned plan template + refresh the daemon-owned snapshot
    _deploy_plan_template(plan_dir, result)

    # Seed the client-owned journal assets (enabled-by-default rollout)
    _deploy_journal_assets(plan_dir, result)

    # Deploy the plan-dedupe scout agent (Plan 00216). Relative to the PROJECT
    # ROOT, not the plan dir — Claude Code resolves agents at .claude/agents/.
    _deploy_dedupe_agent(project_root, result)

    return result


def _deploy_dedupe_agent(project_root: Path, result: BootstrapResult) -> None:
    """Deploy the plan-dedupe scout via the agent-asset subsystem (Plan 00279).

    Behaviour-preserving migration of the pre-subsystem deploy: same deployed
    path and name, still gated on plan_workflow enablement (this function is
    only reached when the workflow is on). The one deliberate change is the
    subsystem's ownership rule — a pristine copy (current or any previously
    shipped revision) is refreshed exactly as before, while a CUSTOMISED copy
    is never clobbered and draws a loud warning instead.
    """
    action_result = deploy_agent(spec_by_name(DEDUPE_AGENT_NAME), project_root)
    result.messages.append(action_result.message)
    if action_result.action in (
        AgentAction.DEPLOYED,
        AgentAction.UPDATED,
        AgentAction.KEPT_CURRENT,
    ):
        result.deployed_dedupe_agent = True


def _deploy_journal_assets(plan_dir: Path, result: BootstrapResult) -> None:
    """Seed the client-owned journal template + reference doc (Plan 00163 P4).

    Both are CLIENT-owned — created from the bundle when absent, never
    overwritten. ``_JOURNAL_TEMPLATE_.md``'s presence is the marker that gates
    ``mkplan.bash``'s ``JOURNAL/`` scaffolding, so seeding it turns journalling
    on for new plans by default (Decision 11); ``PlanJournalling.md`` gives the
    copy-and-customise entry-grammar reference. A project that removes either
    file keeps it removed across upgrades — the seed only ever fills a gap.
    """
    template_src = journal_template_path()
    if not template_src.is_file():
        raise FileNotFoundError(f"Bundled journal template not found: {template_src}")
    template_target = plan_dir / JOURNAL_TEMPLATE_NAME
    if template_target.exists():
        result.messages.append(f"{JOURNAL_TEMPLATE_NAME} already exists (client-owned, kept)")
        logger.info("Keeping existing %s", template_target)
    else:
        template_target.write_text(template_src.read_text())
        result.created_journal_template = True
        result.messages.append(f"Created {JOURNAL_TEMPLATE_NAME} (journal day-file template)")
        logger.info("Created %s", template_target)

    doc_src = plan_journalling_doc_path()
    if not doc_src.is_file():
        raise FileNotFoundError(f"Bundled journalling reference not found: {doc_src}")
    # The reference doc is deployed to the plan dir's PARENT (e.g. CLAUDE/ for a
    # CLAUDE/Plan/ layout), NOT the plan root — the plan root only accepts a
    # fixed set of files (``_EXPECTED_ROOT_FILES``) and the SessionStart sweep
    # would otherwise flag this reference as a stray file every session. This
    # mirrors this repo's own dogfood layout (CLAUDE/PlanJournalling.md) and
    # keeps every doc reference to ``CLAUDE/PlanJournalling.md`` accurate.
    doc_target = plan_dir.parent / PLAN_JOURNALLING_DOC_NAME
    if doc_target.exists():
        result.messages.append(f"{PLAN_JOURNALLING_DOC_NAME} already exists (client-owned, kept)")
        logger.info("Keeping existing %s", doc_target)
    else:
        doc_target.write_text(doc_src.read_text())
        result.created_journalling_doc = True
        result.messages.append(
            f"Created {PLAN_JOURNALLING_DOC_NAME} (journalling reference — customise freely)"
        )
        logger.info("Created %s", doc_target)


def _deploy_mkplan(plan_dir: Path, result: BootstrapResult) -> None:
    """Copy the canonical mkplan.bash into ``plan_dir`` with the execute bit.

    Daemon-owned tooling, so it is overwritten on every upgrade (unlike the
    skip-if-exists README/CLAUDE.md) to guarantee audit fixes reach the field.
    """
    template = mkplan_template_path()
    if not template.is_file():
        raise FileNotFoundError(f"Bundled plan-scaffolding script not found: {template}")

    target = plan_dir / MKPLAN_SCRIPT_NAME
    target.write_text(template.read_text())
    target.chmod(_MKPLAN_MODE)
    result.deployed_mkplan = True
    result.messages.append(f"Deployed {MKPLAN_SCRIPT_NAME} (chmod {_MKPLAN_MODE:o})")
    logger.info("Deployed %s to %s (mode %o)", MKPLAN_SCRIPT_NAME, target, _MKPLAN_MODE)


def _deploy_planlib(plan_dir: Path, result: BootstrapResult) -> None:
    """Copy the canonical `_planlib.inc.bash` into ``plan_dir`` (Plan 00213 Phase 2).

    Daemon-owned tooling, like `mkplan.bash`: overwritten on every run so
    fixes reach the field, never left for a project to fork silently. Unlike
    `mkplan.bash` it is SOURCED, not executed, so it gets `_PLANLIB_MODE`
    (0o644) rather than the executable `_MKPLAN_MODE` -- a deliberately
    separate constant, not a reuse, because the two files encode different
    intentions (run me vs. source me).
    """
    template = planlib_template_path()
    if not template.is_file():
        raise FileNotFoundError(f"Bundled planlib library not found: {template}")

    target = plan_dir / PLANLIB_SCRIPT_NAME
    target.write_text(template.read_text())
    target.chmod(_PLANLIB_MODE)
    result.deployed_planlib = True
    result.messages.append(f"Deployed {PLANLIB_SCRIPT_NAME} (chmod {_PLANLIB_MODE:o})")
    logger.info("Deployed %s to %s (mode %o)", PLANLIB_SCRIPT_NAME, target, _PLANLIB_MODE)


def _deploy_plan_template(plan_dir: Path, result: BootstrapResult) -> None:
    """Seed ``_TEMPLATE_.md`` and manage the default-template snapshot.

    Ownership contract (Plan 00144 Phase 5):

    - ``_TEMPLATE_.md`` is CLIENT-owned: created from the bundled default
      when absent, never overwritten — projects customise their plan
      template freely and ``mkplan.bash`` renders it.
    - ``.plan-template-default.md`` is DAEMON-owned: always refreshed to the
      current bundled default. Before refreshing, a stale snapshot is diffed
      against the new default and the change is surfaced in the result
      messages, so a project with a customised template can adopt upstream
      template improvements deliberately instead of silently missing them.
    """
    default_path = plan_template_default_path()
    if not default_path.is_file():
        raise FileNotFoundError(f"Bundled plan template not found: {default_path}")
    default_text = default_path.read_text()

    template_path = plan_dir / PLAN_TEMPLATE_NAME
    if template_path.exists():
        result.messages.append(f"{PLAN_TEMPLATE_NAME} already exists (client-owned, kept)")
        logger.info("Keeping existing %s", template_path)
    else:
        template_path.write_text(default_text)
        result.created_template = True
        result.messages.append(f"Created {PLAN_TEMPLATE_NAME} (plan template — customise freely)")
        logger.info("Created %s", template_path)

    snapshot_path = plan_dir / TEMPLATE_SNAPSHOT_NAME
    if snapshot_path.exists():
        old_default = snapshot_path.read_text()
        if old_default != default_text:
            result.template_default_changed = True
            diff_lines = list(
                difflib.unified_diff(
                    old_default.splitlines(),
                    default_text.splitlines(),
                    fromfile="previous daemon default",
                    tofile="new daemon default",
                    lineterm="",
                )
            )[:_TEMPLATE_DIFF_MAX_LINES]
            result.messages.append(
                f"The daemon's default plan template changed since the last deploy. "
                f"Your {PLAN_TEMPLATE_NAME} is untouched — review the change and adopt "
                f"what you want:\n" + "\n".join(diff_lines)
            )
            logger.info("Default plan template changed; surfaced diff to result messages")

    snapshot_path.write_text(default_text)


def deploy_plan_workflow_if_enabled(
    project_root: Path,
    config_path: Path,
) -> BootstrapResult:
    """Deploy plan-workflow artifacts iff the config enables the workflow (SSoT).

    The runtime config is the single source of truth for whether the plan
    workflow is "on": when ``config.plan_workflow.enabled`` is true, the scaffold
    and the daemon-owned ``mkplan.bash`` are (re)deployed into
    ``config.plan_workflow.directory``; when false, this is a no-op.
    ``_planlib.inc.bash`` (Plan 00213 Phase 2) is a further, INDEPENDENT opt-in
    gated on ``config.plan_workflow.scripts.enabled`` -- a project can run the
    plan workflow without the library, but never the library without the
    workflow (the library deploys INTO the plan directory).

    This is the single deployment decision site, called identically by
    ``install_version.sh`` and BOTH ``upgrade_version.sh`` paths (full + the
    already-at-target fast path), so artifact deployment can never drift from the
    config the daemon actually reads. It replaces the legacy ``PLAN_WORKFLOW=yes``
    env-var gate, which was orthogonal to the config and never ran on upgrade —
    the v3.24.0 field bug where ``plan_number_helper`` guidance referenced a
    ``mkplan.bash`` that the upgrade path never deployed (Plan 00136).

    Args:
        project_root: Absolute path to the project root.
        config_path: Path to the project's ``hooks-daemon.yaml``. A missing file
            yields the model defaults — ``plan_workflow.enabled`` defaults to
            ``False`` (opt-in), so an absent config is a clean no-op rather than
            an accidental deploy.

    Returns:
        BootstrapResult — ``deployed_mkplan``/``deployed_planlib`` are False
        with an explanatory message when the workflow is disabled in config.
    """
    config = Config.load_or_default(config_path)
    plan_cfg = config.plan_workflow

    if not plan_cfg.enabled:
        result = BootstrapResult()
        result.messages.append("Plan workflow disabled in config (deployment skipped)")
        logger.info("Plan workflow disabled in config; skipping mkplan deployment")
        return result

    return bootstrap_plan_workflow(
        project_root,
        plan_cfg.directory,
        deploy_scripts_library=plan_cfg.scripts.enabled,
    )
