"""ccy PTY supervisor deploy + arm for the installer (Plan 00147/00148).

Deploys AND arms the standalone, stdlib-only PTY supervisor
(``claude-supervise.py``, Plan 00135) in a project's ``.claude/ccy/`` on
install/upgrade. Deploying alone is inert — the ccy launcher only wraps
``claude`` when ``ccy.env`` exports ``CCY_CLAUDE_WRAPPER`` — so this module also
arms (writes that export) and keeps the supervisor files trackable.

There is exactly ONE tracked copy of the script in the daemon repo, at
``<daemon_root>/.claude/ccy/claude-supervise.py`` (pure dogfooding — no ``src/``
or package-data duplicate). Because the daemon is installed by git-cloning this
repo, that file is present in every install, so the deploy sources it from the
daemon clone and copies it into the *target* project's ``.claude/ccy/``.

Gating (``config.ccy.deploy_supervisor`` — see :class:`CcyConfig`):

- ``True``  — deploy/refresh AND arm when the target ``.claude/ccy/`` dir exists.
- ``False`` — never deploy or arm (explicit opt-out).
- ``None``  — (key absent) deploy + arm anyway when the target ``.claude/ccy/``
  dir exists AND flag ``recommend_enable`` so callers promote setting it ``True``.

Each deploy also (a) arms ``ccy.env`` idempotently, respecting an existing
``CCY_CLAUDE_WRAPPER`` (set or commented out), and (b) appends whitelist
exceptions for our files to an EXISTING ``.claude/ccy/.gitignore`` so a blanket
``*`` ignore does not silently drop the supervisor from the repo.

Self-install is a no-op for the copy: when ``daemon_root`` and ``project_root``
resolve to the same path, the source and target are the same file (arming and
gitignore likewise detect the already-configured tracked files and skip).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.models import Config

logger = logging.getLogger(__name__)

SUPERVISOR_SCRIPT_NAME: Final[str] = "claude-supervise.py"
CCY_ENV_NAME: Final[str] = "ccy.env"
_DOCKERFILE_NAME: Final[str] = "Dockerfile"
_GITIGNORE_NAME: Final[str] = ".gitignore"
_CCY_DIR_PARTS: Final[tuple[str, str]] = (".claude", "ccy")

# Files the ccy supervisor system needs COMMITTED so teammates get it. The common
# ccy .gitignore is a blanket `*` (session data must not be committed); these
# whitelist exceptions keep OUR files trackable. We do NOT manage the rest of the
# project's ignore policy — we only ensure the stuff we care about is trackable.
# `.gitignore` itself is whitelisted so the exceptions are visible in the repo;
# the ccy `Dockerfile` (container image definition) is included as harmless.
_CCY_TRACKED_WHITELIST: Final[tuple[str, ...]] = (
    _GITIGNORE_NAME,
    _DOCKERFILE_NAME,
    CCY_ENV_NAME,
    SUPERVISOR_SCRIPT_NAME,
)
# Owner rwx, group/other rx — least-privilege executable (matches deploy_skills /
# mkplan deployment). The supervisor is exec'd directly by the ccy launcher.
_SUPERVISOR_MODE: Final[int] = 0o755

# The env var the ccy launcher sources from ccy.env and prepends to `claude`.
# Its mere presence (set OR commented out) means the user has a stance on
# arming, so we never overwrite it.
_WRAPPER_EXPORT_KEY: Final[str] = "CCY_CLAUDE_WRAPPER"

# Self-locating armed wrapper line. The `$(cd ... && pwd)` runs at *source* time
# (double-quoted assignment), resolving the supervisor's absolute path from
# ccy.env's own location — so one line serves BOTH the podman `/workspace` mount
# and an arbitrary LXC project dir (LXC-SUPPORT.md open question #2). `--arm`
# enables real /compact + continue injection (dry-run is the un-armed default).
_ARMED_WRAPPER_LINE: Final[str] = (
    'export CCY_CLAUDE_WRAPPER="${CCY_CLAUDE_WRAPPER:-'
    '$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/'
    f'{SUPERVISOR_SCRIPT_NAME} --arm --}}"'
)

# Comment block written immediately above the armed line (fresh file or append).
_ARMED_WRAPPER_COMMENT: Final[str] = (
    "# --- Plan 00135 PTY supervisor (armed by the hooks-daemon ccy deploy) ---\n"
    "# ARMED: the supervisor watches the daemon-written context sidecar and, when\n"
    "# the context goes RED and the session is idle, injects a REAL `/compact`; on\n"
    "# any compaction it injects `continue` to resume. Supervisor-injected prompts\n"
    "# are prefixed `\U0001f916 [ccy-supervisor]` so they are obviously bot messages.\n"
    "#\n"
    "# To DRY-RUN (harmless visible marker instead of a real /compact): drop the\n"
    "# `--arm` below. To DISABLE entirely: comment the next line. Relaunch ccy after\n"
    "# either change. This line is left untouched on future upgrades once present.\n"
)

# Header for a freshly-created ccy.env (no pre-existing file in the target).
_FRESH_ENV_HEADER: Final[str] = (
    "# ccy.env — per-project ccy environment.\n"
    "#\n"
    "# Sourced INSIDE the disposable ccy container by the ccy launcher, never on\n"
    "# the host. Created by the hooks-daemon ccy supervisor deploy (Plan 00147/00148).\n"
    "\n"
)


@dataclass
class CcySupervisorDeployResult:
    """Result of a ccy supervisor deploy attempt.

    Attributes:
        deployed: True when the supervisor file was (re)written into the target.
        armed: True when this run wrote/appended the ``CCY_CLAUDE_WRAPPER`` export
            into the target's ``ccy.env`` (i.e. actually enabled the supervisor).
            False when arming was skipped (flag off, no ccy dir, or the user
            already has a stance on ``CCY_CLAUDE_WRAPPER``).
        gitignore_updated: True when this run added whitelist exceptions to the
            target's ``.claude/ccy/.gitignore`` (or created it) so the supervisor
            files are trackable rather than silently git-ignored.
        recommend_enable: True when the flag was absent (None) while the target
            is a ccy project — callers should promote setting
            ``ccy.deploy_supervisor: true``.
        messages: Human-readable trace of what happened / why it was skipped.
    """

    deployed: bool = False
    armed: bool = False
    gitignore_updated: bool = False
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
        # Self-install: source and target are the same file — no copy needed. We
        # still fall through to arming so the env is enabled uniformly.
        result.messages.append(
            "Supervisor already in place (self-install; source == target); no copy"
        )
        logger.info("ccy supervisor source == target (%s); no copy needed", target)
    else:
        target.write_bytes(source.read_bytes())
        target.chmod(_SUPERVISOR_MODE)
        result.deployed = True
        result.messages.append(
            f"Deployed {SUPERVISOR_SCRIPT_NAME} to {target} (chmod {_SUPERVISOR_MODE:o})"
        )
        logger.info("Deployed %s to %s (mode %o)", SUPERVISOR_SCRIPT_NAME, target, _SUPERVISOR_MODE)

    # Arming is the whole point: a deployed-but-unarmed supervisor is inert
    # because the launcher only wraps `claude` when ccy.env exports the wrapper.
    result.armed, arm_message = _arm_ccy_supervisor(target_ccy_dir)
    result.messages.append(arm_message)

    # Ensure the supervisor files are TRACKABLE — a blanket-ignore ccy dir would
    # otherwise leave them git-ignored, uncommitted, and absent for teammates.
    result.gitignore_updated, gitignore_message = _ensure_ccy_gitignore_allows(target_ccy_dir)
    result.messages.append(gitignore_message)
    result.messages.append(
        "Commit .claude/ccy/{"
        f"{_GITIGNORE_NAME},{CCY_ENV_NAME},{SUPERVISOR_SCRIPT_NAME}"
        "} so teammates get the supervisor system"
    )
    return result


def _arm_ccy_supervisor(target_ccy_dir: Path) -> tuple[bool, str]:
    """Ensure ``ccy.env`` exports an armed ``CCY_CLAUDE_WRAPPER``, idempotently.

    Behaviour:

    - ``ccy.env`` absent → create it with a header + the armed wrapper block.
    - ``ccy.env`` present WITHOUT the wrapper key → append the armed block.
    - ``ccy.env`` present WITH the wrapper key (set OR commented out) → leave it
      untouched; the user has a stance on arming and we never override it.

    Args:
        target_ccy_dir: The target project's ``.claude/ccy/`` directory.

    Returns:
        ``(armed, message)`` where ``armed`` is True only when this call wrote
        the wrapper export.
    """
    env_path = target_ccy_dir / CCY_ENV_NAME
    armed_block = f"{_ARMED_WRAPPER_COMMENT}{_ARMED_WRAPPER_LINE}\n"

    if env_path.is_file():
        content = env_path.read_text(encoding="utf-8")
        if _WRAPPER_EXPORT_KEY in content:
            logger.info(
                "ccy.env already references %s at %s; left untouched", _WRAPPER_EXPORT_KEY, env_path
            )
            return False, f"ccy.env already configures {_WRAPPER_EXPORT_KEY}; left untouched"
        new_content = f"{content.rstrip(chr(10))}\n\n{armed_block}"
        env_path.write_text(new_content, encoding="utf-8")
        logger.info("Appended armed %s to existing %s", _WRAPPER_EXPORT_KEY, env_path)
        return True, f"Armed supervisor: appended {_WRAPPER_EXPORT_KEY} to {env_path}"

    env_path.write_text(f"{_FRESH_ENV_HEADER}{armed_block}", encoding="utf-8")
    logger.info("Created armed %s at %s", CCY_ENV_NAME, env_path)
    return True, f"Armed supervisor: created {env_path}"


def _ensure_ccy_gitignore_allows(target_ccy_dir: Path) -> tuple[bool, str]:
    """Ensure an EXISTING ``.claude/ccy/.gitignore`` whitelists our files.

    The reported failure mode: a ccy ``.gitignore`` with a blanket ``*`` ignores
    session data AND silently ignores the deployed ``claude-supervise.py`` /
    armed ``ccy.env``, so they are never committed and teammates never receive
    the supervisor. This appends any missing ``!<file>`` exceptions (git honours
    the last matching pattern, so an appended exception wins over an earlier
    ``*``) for OUR files only.

    Scope is deliberately narrow — we do NOT own the project's ignore policy:

    - ``.gitignore`` ABSENT → no-op. Our files are not locally ignored, and
      fabricating a blanket-ignore policy file is not this repo's job.
    - ``.gitignore`` present but missing some of our exceptions → append only the
      missing ``!<file>`` lines (never duplicates, never rewrites user content).
    - all our exceptions already present → leave it byte-identical.

    Note: this cannot re-include files when a *parent* ``.gitignore`` excludes the
    whole ``.claude/ccy/`` directory (git cannot re-include under an excluded
    dir). The SessionStart integrity check surfaces that rarer brick risk.

    Args:
        target_ccy_dir: The target project's ``.claude/ccy/`` directory.

    Returns:
        ``(gitignore_updated, message)`` — ``gitignore_updated`` is True only when
        this call appended exceptions.
    """
    gitignore_path = target_ccy_dir / _GITIGNORE_NAME

    if not gitignore_path.is_file():
        logger.info(
            "No %s in %s; our files are not locally ignored", _GITIGNORE_NAME, target_ccy_dir
        )
        return False, f"No {_GITIGNORE_NAME} in .claude/ccy/; supervisor files not locally ignored"

    content = gitignore_path.read_text(encoding="utf-8")
    existing_lines = {line.strip() for line in content.splitlines()}
    missing = [f"!{name}" for name in _CCY_TRACKED_WHITELIST if f"!{name}" not in existing_lines]
    if not missing:
        logger.info("%s already whitelists supervisor files at %s", _GITIGNORE_NAME, gitignore_path)
        return False, f"{gitignore_path} already whitelists the supervisor files"

    appended = "\n".join(missing)
    new_content = f"{content.rstrip(chr(10))}\n{appended}\n"
    gitignore_path.write_text(new_content, encoding="utf-8")
    logger.info("Appended %s to %s", missing, gitignore_path)
    return True, f"Whitelisted supervisor files in {gitignore_path}: {', '.join(missing)}"
