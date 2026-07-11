"""CcySupervisorIntegrityHandler — warn on a brick-risk ccy supervisor setup.

Runs on SessionStart (new sessions only). When the ccy supervisor is ARMED — a
non-comment line in ``.claude/ccy/ccy.env`` exports ``CCY_CLAUDE_WRAPPER``
referencing ``claude-supervise.py`` — the ccy launcher will ``exec`` that script
to wrap every ``claude`` launch. If the script is then missing, not executable,
or git-ignored (so it never reaches teammates), the ccy launch breaks. This
advisory surfaces those states loudly so the project is set up properly; it
never blocks. Non-ccy projects and un-armed setups are silent no-ops.
"""

import logging
import os
import subprocess  # nosec B404 - git invoked with a fixed, trusted argument list only
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext

logger = logging.getLogger(__name__)

_CCY_DIR_PARTS: tuple[str, str] = (".claude", "ccy")
_SUPERVISOR_SCRIPT_NAME = "claude-supervise.py"
_CCY_ENV_NAME = "ccy.env"
_CONFIG_REL_PARTS: tuple[str, str] = (".claude", "hooks-daemon.yaml")
_WRAPPER_EXPORT_KEY = "CCY_CLAUDE_WRAPPER"
_COMMENT_PREFIX = "#"
_GIT_CHECK_IGNORE_TIMEOUT_SECONDS = 5
_RESUME_TRANSCRIPT_MIN_BYTES = 100
# git check-ignore exits 0 when the path IS ignored, 1 when it is NOT.
_GIT_IGNORED_RETURNCODE = 0


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

    def _is_resume_session(self, hook_input: dict[str, Any]) -> bool:
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        if not transcript_path:
            return False
        try:
            path = Path(transcript_path)
            return path.exists() and path.stat().st_size > _RESUME_TRANSCRIPT_MIN_BYTES
        except (OSError, ValueError):
            return False

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
        try:
            # SECURITY: fixed, trusted git argv; no shell; rel_path is a repo-relative
            # constant path, never user input.
            result = subprocess.run(  # nosec B603 B607 - fixed trusted git argv, no shell
                ["git", "-C", str(project_root), "check-ignore", "-q", rel_path],
                capture_output=True,
                timeout=_GIT_CHECK_IGNORE_TIMEOUT_SECONDS,
                check=False,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            logger.debug("git check-ignore failed for %s: %s", rel_path, exc)
            return False
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
        return not self._is_resume_session(hook_input)

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
        if not problems:
            return HookResult(decision=Decision.ALLOW, context=[])

        context = [
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
