"""Plan workflow bootstrapping for installer.

Creates the CLAUDE/Plan/ directory structure with a starter README.md
and lifecycle CLAUDE.md so new projects can use structured plan-based
development immediately after install.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

_DEFAULT_PLAN_DIR_NAME: Final[str] = "CLAUDE/Plan"
_COMPLETED_DIR_NAME: Final[str] = "Completed"

_TEMPLATES_DIR_NAME: Final[str] = "templates"
MKPLAN_SCRIPT_NAME: Final[str] = "mkplan.bash"
# Owner rwx, group/other rx — least-privilege executable (matches deploy_skills).
_MKPLAN_MODE: Final[int] = 0o755


def mkplan_template_path() -> Path:
    """Absolute path to the canonical bundled ``mkplan.bash`` template.

    This is the single source of truth for the plan-scaffolding script; the
    installer copies it into each project's plan directory on install/upgrade.
    """
    return Path(__file__).resolve().parent / _TEMPLATES_DIR_NAME / MKPLAN_SCRIPT_NAME


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

1. Update plan status to `Complete` with date
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
    messages: list[str] = field(default_factory=list)


def bootstrap_plan_workflow(
    project_root: Path,
    plan_dir_name: str = _DEFAULT_PLAN_DIR_NAME,
) -> BootstrapResult:
    """Bootstrap the plan directory structure for a project.

    Creates (under ``plan_dir_name``, default ``CLAUDE/Plan``):
    - the plan directory
    - the ``Completed/`` subdirectory
    - ``README.md`` (plan index template) — skipped if it already exists
    - ``CLAUDE.md`` (lifecycle instructions) — skipped if it already exists
    - ``mkplan.bash`` (the next-plan scaffolding script) — daemon-owned tooling,
      always (re)deployed so audit fixes reach existing installs on upgrade

    Client content (README/CLAUDE.md) is never overwritten; the daemon-owned
    ``mkplan.bash`` is overwritten on every run, matching how skill scripts and
    hook wrappers are re-deployed.

    Args:
        project_root: Absolute path to the project root
        plan_dir_name: Plan directory relative to project root. Defaults to
            ``CLAUDE/Plan`` but MUST be passed the configured
            ``track_plans_in_project`` value so the bootstrap honours a project
            that tracks plans elsewhere (single source of truth).

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

    return result


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
