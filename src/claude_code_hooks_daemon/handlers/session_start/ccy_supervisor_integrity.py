"""CcySupervisorIntegrityHandler — warn on a brick-risk ccy supervisor setup.

Runs on SessionStart (new sessions only). When the ccy supervisor is ARMED — a
non-comment line in ``.claude/ccy/ccy.env`` exports ``CCY_CLAUDE_WRAPPER``
referencing ``claude-supervise.py`` — the ccy launcher will ``exec`` that script
to wrap every ``claude`` launch. If the script is then missing, not executable,
or git-ignored (so it never reaches teammates), the ccy launch breaks. This
advisory surfaces those states loudly so the project is set up properly; it
never blocks. Non-ccy projects and un-armed setups are silent no-ops.
"""

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

_CCY_DIR_PARTS: tuple[str, str] = (".claude", "ccy")
_SUPERVISOR_SCRIPT_NAME = "claude-supervise.py"
_CCY_ENV_NAME = "ccy.env"
_CONFIG_REL_PARTS: tuple[str, str] = (".claude", "hooks-daemon.yaml")
_WRAPPER_EXPORT_KEY = "CCY_CLAUDE_WRAPPER"
_COMMENT_PREFIX = "#"
_GIT_CHECK_IGNORE_TIMEOUT_SECONDS = 5
# git check-ignore exits 0 when the path IS ignored, 1 when it is NOT — both are
# valid answers. Anything else (git unavailable, a fatal error) is a genuine
# failure worth a debug log.
_GIT_IGNORED_RETURNCODE = 0
_GIT_NOT_IGNORED_RETURNCODE = 1

# Stale-supervisor detection (Plan 00164 Phase 3). The running supervisor writes
# its identity here; we compare it against the on-disk claude-supervise.py.
_SUPERVISE_SUBDIR = "supervise"
_SUPERVISOR_STATUS_FILENAME = "supervisor-status.json"
# Untracked runtime dir relative to the project root, per install mode. Mirrors
# ProjectContext.daemon_untracked_dir() / the supervisor's _daemon_untracked_dir.
_SELF_INSTALL_MARKER_PARTS: tuple[str, str] = ("src", "claude_code_hooks_daemon")
_SELF_INSTALL_UNTRACKED_PARTS: tuple[str, ...] = ("untracked",)
_NORMAL_UNTRACKED_PARTS: tuple[str, ...] = (".claude", "hooks-daemon", "untracked")
# Length of the sha256 hex prefix used as the source fingerprint. MUST match the
# supervisor's compute_source_hash (claude-supervise.py) or every launch reads
# as stale. Cross-process contract; the algorithm is trivial and stable.
_SOURCE_HASH_HEX_LEN = 12
_VERSION_RE = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")


class CcySupervisorIntegrityHandler(Handler):
    """Advisory: warn when the ccy supervisor is armed but its files are unsafe."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.CCY_SUPERVISOR_INTEGRITY,
            priority=Priority.CCY_SUPERVISOR_INTEGRITY,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.GIT,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )

    # ------------------------------------------------------------------
    # Project root / session helpers
    # ------------------------------------------------------------------

    def _get_project_root(self) -> Path | None:
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; using cwd for ccy integrity check")
            return Path.cwd()

    # ------------------------------------------------------------------
    # Integrity checks
    # ------------------------------------------------------------------

    def _is_armed(self, ccy_env: Path) -> bool:
        """Armed = a non-comment line exports the wrapper referencing the script."""
        if not ccy_env.is_file():
            return False
        try:
            content = ccy_env.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.debug("Could not read %s: %s", ccy_env, exc)
            return False
        for raw in content.splitlines():
            stripped = raw.strip()
            if stripped.startswith(_COMMENT_PREFIX):
                continue
            if _WRAPPER_EXPORT_KEY in stripped and _SUPERVISOR_SCRIPT_NAME in stripped:
                return True
        return False

    def _git_ignored(self, project_root: Path, rel_path: str) -> bool:
        """Return True only when git positively reports ``rel_path`` as ignored.

        Skipped (returns False) when the project is not a git repo or git cannot
        be run — an undetermined state must never raise a false alarm.
        """
        if not (project_root / ".git").exists():
            return False
        result = run_git(
            project_root,
            "check-ignore",
            "-q",
            rel_path,
            timeout=_GIT_CHECK_IGNORE_TIMEOUT_SECONDS,
        )
        if result.returncode not in (_GIT_IGNORED_RETURNCODE, _GIT_NOT_IGNORED_RETURNCODE):
            logger.debug("git check-ignore failed for %s: %s", rel_path, result.stderr)
        return result.returncode == _GIT_IGNORED_RETURNCODE

    def _deploy_explicitly_disabled(self, project_root: Path) -> bool:
        """True only when ``ccy.deploy_supervisor`` is explicitly ``false`` in config.

        An absent key (``None``) still deploys+arms on upgrade, so it is NOT an
        inconsistency. Only an explicit ``false`` contradicts an armed, present
        supervisor: the installer returns early on ``false`` and will never
        refresh ``claude-supervise.py`` again, leaving the project on a stale
        supervisor. A missing/unparseable config never raises a false alarm.
        """
        config_path = project_root.joinpath(*_CONFIG_REL_PARTS)
        try:
            config = Config.load_or_default(config_path)
        except (OSError, ValueError) as exc:
            logger.debug("Could not load config for ccy deploy check: %s", exc)
            return False
        return config.ccy.deploy_supervisor is False

    # ------------------------------------------------------------------
    # Stale-supervisor detection (Plan 00164 Phase 3)
    # ------------------------------------------------------------------

    def _daemon_untracked_dir(self, project_root: Path) -> Path:
        """Resolve the daemon untracked dir (install-mode-aware) from the root.

        Mirrors the supervisor's ``_daemon_untracked_dir`` so both agree on where
        the status file lives, without importing ProjectContext (this handler is
        often invoked with a fallback cwd root).
        """
        if project_root.joinpath(*_SELF_INSTALL_MARKER_PARTS).exists():
            return project_root.joinpath(*_SELF_INSTALL_UNTRACKED_PARTS)
        return project_root.joinpath(*_NORMAL_UNTRACKED_PARTS)

    def _hash_supervisor_source(self, path: Path) -> str:
        """Short sha256 fingerprint of ``path`` — MUST match the supervisor's."""
        digest = hashlib.sha256(path.read_bytes(), usedforsecurity=False)
        return digest.hexdigest()[:_SOURCE_HASH_HEX_LEN]

    def _pid_alive(self, pid: object) -> bool:
        """Return True iff ``pid`` is a live process we can see.

        ``os.kill(pid, 0)`` raises ESRCH when the process is gone and EPERM when
        it exists but is owned by another user (still alive). Non-int / invalid
        pids are treated as not-alive.
        """
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            logger.debug("pid liveness check failed for %s: %s", pid, exc)
            return False
        return True

    def _read_supervisor_status(self, project_root: Path) -> dict[str, Any]:
        """Read the running supervisor's status file.

        Returns an EMPTY dict when the file is absent or unreadable/invalid — a
        typed default the caller treats as "no supervisor advertised" (an empty
        dict is falsy), rather than conflating absence with an error via None.
        """
        status_path = (
            self._daemon_untracked_dir(project_root)
            / _SUPERVISE_SUBDIR
            / _SUPERVISOR_STATUS_FILENAME
        )
        if not status_path.is_file():
            return {}
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.debug("Could not read supervisor status %s: %s", status_path, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _parse_ondisk_version(self, script: Path) -> str:
        """Extract ``__version__`` from the on-disk supervisor (``?`` if absent)."""
        try:
            match = _VERSION_RE.search(script.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.debug("Could not read supervisor for version parse: %s", exc)
            return "?"
        return match.group(1) if match else "?"

    def _check_supervisor_staleness(self, project_root: Path, ccy_dir: Path) -> list[str]:
        """Return advisory lines when the RUNNING supervisor is behind on-disk.

        Silent (empty list) unless: the script exists, a status file names a
        LIVE supervisor process, and that process's recorded source fingerprint
        differs from the on-disk script. Using a content fingerprint (not just
        the version string) means a dev edit between releases is caught too.
        """
        script = ccy_dir / _SUPERVISOR_SCRIPT_NAME
        if not script.is_file():
            return []  # missing script is handled by _find_problems

        status = self._read_supervisor_status(project_root)
        if not status:
            return []  # no supervisor has advertised itself

        if not self._pid_alive(status.get("pid")):
            return []  # advertised supervisor is not running — not a staleness concern

        running_hash = status.get("source_hash")
        if not isinstance(running_hash, str) or not running_hash:
            return []  # pre-Phase-3 supervisor with no fingerprint; nothing to compare

        ondisk_hash = self._hash_supervisor_source(script)
        if running_hash == ondisk_hash:
            return []  # up to date

        running_version = status.get("version", "?")
        ondisk_version = self._parse_ondisk_version(script)
        return [
            "🔄 CCY SUPERVISOR OUTDATED — restart ccy to load the new supervisor",
            "",
            f"The running ccy supervisor is v{running_version} (source {running_hash}), but a "
            f"NEWER supervisor is on disk: v{ondisk_version} (source {ondisk_hash}). A daemon "
            "upgrade replaced claude-supervise.py, but the live process keeps running the old "
            "code until ccy is relaunched.",
            "",
            "Fix: exit this ccy session and start a new one so the wrapper re-execs the updated "
            "supervisor. (Nothing is broken meanwhile — the old supervisor keeps working.)",
        ]

    def _find_problems(self, project_root: Path, ccy_dir: Path) -> list[str]:
        """Return a list of brick-risk problem descriptions (empty when healthy)."""
        problems: list[str] = []
        script = ccy_dir / _SUPERVISOR_SCRIPT_NAME
        script_rel = f"{_CCY_DIR_PARTS[0]}/{_CCY_DIR_PARTS[1]}/{_SUPERVISOR_SCRIPT_NAME}"
        env_rel = f"{_CCY_DIR_PARTS[0]}/{_CCY_DIR_PARTS[1]}/{_CCY_ENV_NAME}"
        config_rel = f"{_CONFIG_REL_PARTS[0]}/{_CONFIG_REL_PARTS[1]}"

        if self._deploy_explicitly_disabled(project_root):
            problems.append(
                f"ccy.deploy_supervisor is FALSE in {config_rel}, but the supervisor is "
                "armed and present — the installer skips deploy on `false`, so daemon "
                "upgrades will NEVER refresh claude-supervise.py and this project will "
                "run an increasingly stale supervisor. Fix: set ccy.deploy_supervisor: "
                "true (or, if you truly want it off, disarm CCY_CLAUDE_WRAPPER in ccy.env)."
            )

        if not script.is_file():
            problems.append(
                f"{script_rel} is MISSING — the ccy launcher will fail to exec the "
                "supervisor. Redeploy it (daemon upgrade) or restore it from git."
            )
        elif not os.access(script, os.X_OK):
            problems.append(
                f"{script_rel} is not executable — the launcher's `exec` will fail. "
                f"Fix: chmod +x {script_rel}"
            )

        for rel in (script_rel, env_rel):
            if self._git_ignored(project_root, rel):
                problems.append(
                    f"{rel} is GIT-IGNORED — it will not be committed, so teammates "
                    "cloning the repo get a broken/half-configured supervisor. Fix: add "
                    f"a `!{Path(rel).name}` whitelist line in .claude/ccy/.gitignore and "
                    "commit the file (or `git add -f` it)."
                )
        return problems

    # ------------------------------------------------------------------
    # Handler protocol
    # ------------------------------------------------------------------

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        project_root = self._get_project_root()
        if project_root is None:
            return HookResult(decision=Decision.ALLOW, context=[])

        ccy_dir = project_root.joinpath(*_CCY_DIR_PARTS)
        if not ccy_dir.is_dir():
            return HookResult(decision=Decision.ALLOW, context=[])

        if not self._is_armed(ccy_dir / _CCY_ENV_NAME):
            # Not armed → supervisor is inert; nothing to enforce.
            return HookResult(decision=Decision.ALLOW, context=[])

        problems = self._find_problems(project_root, ccy_dir)
        stale_lines = self._check_supervisor_staleness(project_root, ccy_dir)

        context: list[str] = []
        if problems:
            context += [
                "🚨 CCY SUPERVISOR MISCONFIGURED — armed but not properly set up",
                "",
                "The ccy supervisor is ARMED (ccy.env exports CCY_CLAUDE_WRAPPER), but:",
                "",
            ]
            context += [f"  ❌ {problem}" for problem in problems]
            context += [
                "",
                "An armed-but-broken supervisor can brick ccy launches for this project "
                "and for teammates. Fix the above, then commit the ccy files.",
            ]

        if stale_lines:
            if context:
                context.append("")
            context += stale_lines

        if not context:
            return HookResult(decision=Decision.ALLOW, context=[])
        return HookResult(decision=Decision.ALLOW, context=context)

    def get_claude_md(self) -> str | None:
        return (
            "## ccy_supervisor_integrity — keep the ccy supervisor properly set up\n\n"
            "At session start this handler checks a ccy project (`.claude/ccy/`) whose "
            "supervisor is **armed** (`ccy.env` exports `CCY_CLAUDE_WRAPPER` referencing "
            "`claude-supervise.py`). It warns — never blocks — when the setup is "
            "brick-risky:\n\n"
            "- **`claude-supervise.py` missing** → the launcher's `exec` fails. Redeploy "
            "via a daemon upgrade or restore from git.\n"
            "- **not executable** → `chmod +x .claude/ccy/claude-supervise.py`.\n"
            "- **git-ignored** → it won't be committed; teammates get a broken supervisor. "
            "Add a `!claude-supervise.py` / `!ccy.env` whitelist line to "
            "`.claude/ccy/.gitignore` and commit the files.\n"
            "- **`ccy.deploy_supervisor: false` while armed+present** → the installer "
            "skips deploy on `false`, so upgrades never refresh `claude-supervise.py` and "
            "the project runs an increasingly stale supervisor. Set it to `true` (or "
            "disarm `CCY_CLAUDE_WRAPPER` if you truly want it off).\n\n"
            "It also detects a **stale running supervisor** (Plan 00164): when a daemon "
            "upgrade has put a NEWER `claude-supervise.py` on disk than the live process "
            "(compared by source fingerprint, not just version), it advises restarting ccy "
            "so the wrapper re-execs the updated supervisor. Nothing is broken meanwhile — "
            "the old supervisor keeps working until the session is relaunched.\n\n"
            "When you see this alert, fix the listed item(s) and commit the ccy files so "
            "the supervisor works for everyone."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="ccy supervisor integrity - silent when not a ccy project",
                command='echo "test"',
                description=(
                    "Verifies the ccy supervisor integrity check runs on new sessions "
                    "and stays silent in a non-ccy project (no .claude/ccy/ directory)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Advisory handler - warns but does not block",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
