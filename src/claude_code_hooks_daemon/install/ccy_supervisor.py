"""ccy PTY supervisor deployment for the installer (Plan 00147).

Deploys the standalone, stdlib-only PTY supervisor (``claude-supervise.py``,
Plan 00135) into a project's ``.claude/ccy/`` directory on install/upgrade.

There is exactly ONE tracked copy of the script in the daemon repo, at
``<daemon_root>/.claude/ccy/claude-supervise.py`` (pure dogfooding — no ``src/``
or package-data duplicate). Because the daemon is installed by git-cloning this
repo, that file is present in every install, so the deploy sources it from the
daemon clone and copies it into the *target* project's ``.claude/ccy/``.

Gating (``config.ccy.deploy_supervisor`` — see :class:`CcyConfig`):

- ``True``  — deploy/refresh when the target ``.claude/ccy/`` dir exists.
- ``False`` — never deploy (explicit opt-out).
- ``None``  — (key absent) deploy anyway when the target ``.claude/ccy/`` dir
  exists AND flag ``recommend_enable`` so callers can promote setting it ``True``.

Self-install is a no-op: when ``daemon_root`` and ``project_root`` resolve to the
same path, the source and target are the same file and the copy is skipped.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import Config

logger = logging.getLogger(__name__)

SUPERVISOR_SCRIPT_NAME: Final[str] = "claude-supervise.py"
_CCY_DIR_PARTS: Final[tuple[str, str]] = (".claude", "ccy")
# Owner rwx, group/other rx — least-privilege executable (matches deploy_skills /
# mkplan deployment). The supervisor is exec'd directly by the ccy launcher.
_SUPERVISOR_MODE: Final[int] = 0o755


@dataclass
class CcySupervisorDeployResult:
    """Result of a ccy supervisor deploy attempt.

    Attributes:
        deployed: True when the supervisor file was (re)written into the target.
        recommend_enable: True when the flag was absent (None) while the target
            is a ccy project — callers should promote setting
            ``ccy.deploy_supervisor: true``.
        messages: Human-readable trace of what happened / why it was skipped.
    """

    deployed: bool = False
    recommend_enable: bool = False
    messages: list[str] = field(default_factory=list)


def ccy_supervisor_source_path(daemon_root: Path) -> Path:
    """Absolute path to the canonical bundled supervisor within the daemon clone."""
    return daemon_root.joinpath(*_CCY_DIR_PARTS, SUPERVISOR_SCRIPT_NAME)


def deploy_ccy_supervisor_if_enabled(
    daemon_root: Path,
    project_root: Path,
    config_path: Path,
) -> CcySupervisorDeployResult:
    """Deploy the ccy supervisor into ``project_root`` iff config + layout allow.

    Args:
        daemon_root: Root of the installed daemon clone (contains the canonical
            ``.claude/ccy/claude-supervise.py``). In self-install this equals
            ``project_root``.
        project_root: Root of the target project to deploy into.
        config_path: Path to the project's ``hooks-daemon.yaml``. A missing file
            yields model defaults (``deploy_supervisor`` = None → deploy +
            recommend when the target is a ccy project).

    Returns:
        CcySupervisorDeployResult describing the outcome.
    """
    result = CcySupervisorDeployResult()
    config = Config.load_or_default(config_path)
    flag = config.ccy.deploy_supervisor

    if flag is False:
        result.messages.append("ccy.deploy_supervisor is false (deployment skipped)")
        logger.info("ccy supervisor deploy disabled in config; skipping")
        return result

    target_ccy_dir = project_root.joinpath(*_CCY_DIR_PARTS)
    if not target_ccy_dir.is_dir():
        result.messages.append(
            "No .claude/ccy/ directory in target project (not a ccy project); skipped"
        )
        logger.info("Target %s has no .claude/ccy/; skipping supervisor deploy", project_root)
        return result

    source = ccy_supervisor_source_path(daemon_root)
    if not source.is_file():
        result.messages.append(f"Supervisor source not found at {source} (skipped)")
        logger.warning("ccy supervisor source missing at %s; skipping deploy", source)
        return result

    # Absent flag + ccy project = we should promote enabling it, whether or not a
    # copy is physically needed (covers the self-install no-op below too).
    result.recommend_enable = flag is None

    target = target_ccy_dir / SUPERVISOR_SCRIPT_NAME
    if target.exists() and source.resolve() == target.resolve():
        result.messages.append(
            "Supervisor already in place (self-install; source == target); skipped"
        )
        logger.info("ccy supervisor source == target (%s); no copy needed", target)
        return result

    target.write_bytes(source.read_bytes())
    target.chmod(_SUPERVISOR_MODE)
    result.deployed = True
    result.messages.append(
        f"Deployed {SUPERVISOR_SCRIPT_NAME} to {target} (chmod {_SUPERVISOR_MODE:o})"
    )
    logger.info("Deployed %s to %s (mode %o)", SUPERVISOR_SCRIPT_NAME, target, _SUPERVISOR_MODE)
    return result
