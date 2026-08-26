"""Contract-staleness advisory for SessionStart events (Plan 00271 Task 1.7).

Sibling of ``version_check``. The vendored Claude Code hooks contract under
``contracts/claude-code-hooks/`` records the Claude Code version it was last
audited against (``META.json.last_audited_claude_code_version``). When the
INSTALLED Claude Code is newer, the vendored copy may be stale — this handler
advises running the refresh procedure (``docs/guides/HOOK-CONTRACT-REFRESH.md``).

Advisory by design, never an auto-refresh: extraction from prose docs must be
verified, not trusted (a summarising fetch layer once fabricated a
``permissionDecision: "escalate"`` value — Plan 00271 Decision 3).
"""

import json
import logging
import re
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, trusted binary lookup
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    Timeout,
)
from claude_code_hooks_daemon.core import AdvisoryResult, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

#: The vendored contract's provenance file, resolved relative to the daemon
#: source tree (this file lives at src/claude_code_hooks_daemon/handlers/
#: session_start/, four levels below the repository root — true in
#: self-install mode AND in a client's .claude/hooks-daemon/ clone).
_DEFAULT_META_PATH: Final[Path] = (
    Path(__file__).resolve().parents[4] / "contracts" / "claude-code-hooks" / "META.json"
)

#: The Claude Code CLI binary probed for the installed version.
_CLAUDE_BINARY: Final[str] = "claude"
_CLAUDE_VERSION_FLAG: Final[str] = "--version"

#: Leading semantic version in ``claude --version`` output ("2.1.246 (Claude Code)").
_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"(\d+\.\d+\.\d+)")

#: META.json keys read by this handler.
#: SessionStart input's documented session-origin field and its new-session value.
_SOURCE_FIELD: Final[str] = "source"
_SOURCE_STARTUP: Final[str] = "startup"

_META_VERSION_KEY: Final[str] = "last_audited_claude_code_version"
_META_REFRESH_KEY: Final[str] = "refresh_procedure"
_FALLBACK_REFRESH_DOC: Final[str] = "docs/guides/HOOK-CONTRACT-REFRESH.md"

#: Cache of the probed installed version, so ``claude --version`` (a Node
#: process start) is not paid on every new session.
_CACHE_FILENAME: Final[str] = "contract_staleness_cache.json"
_CACHE_TTL_SECONDS: Final[int] = 86400
_CACHE_TIME_KEY: Final[str] = "cached_at"
_CACHE_VERSION_KEY: Final[str] = "installed_version"


class ContractStalenessHandler(SessionStartHandlerBase):
    """Advise a vendored-contract refresh when Claude Code has moved on."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.CONTRACT_STALENESS,
            priority=Priority.CONTRACT_STALENESS,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self.config: dict[str, Any] = {"enabled": True}
        self.meta_path: Path = _DEFAULT_META_PATH
        # Injection point for tests; production reads `claude --version`.
        self.installed_version_reader: Callable[[], str | None] = self._read_installed_version

    def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration."""
        self.config.update(config)

    def matches(self, hook_input: dict[str, Any] | None) -> bool:
        """Run on NEW SessionStart events only (never on resume)."""
        if not hook_input or not isinstance(hook_input, dict):
            return False
        if not self.config.get("enabled", True):
            return False
        if hook_input.get(HookInputField.HOOK_EVENT_NAME) != "SessionStart":
            return False
        # The documented `source` field is authoritative when present
        # ("startup" = genuinely new session); the transcript heuristic covers
        # payloads without one.
        source = hook_input.get(_SOURCE_FIELD)
        if isinstance(source, str):
            return source == _SOURCE_STARTUP
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Compare installed Claude Code with the last-audited version."""
        meta = self._read_meta()
        if meta is None:
            return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=[])
        audited = meta.get(_META_VERSION_KEY)
        installed = self.installed_version_reader()
        if not isinstance(audited, str) or installed is None:
            return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=[])
        if not self._is_newer(installed, audited):
            return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=[])

        refresh_doc = str(meta.get(_META_REFRESH_KEY) or _FALLBACK_REFRESH_DOC)
        context = [
            (
                f"📜 Hooks contract audit is stale: installed Claude Code is "
                f"v{installed}, but the vendored hooks contract "
                f"(contracts/claude-code-hooks/) was last audited against "
                f"v{audited}."
            ),
            "",
            (
                f"The hooks output contract may have changed. Run the refresh "
                f"procedure in {refresh_doc}: fetch the RAW hooks.md (never a "
                f"summarising fetch layer), verify each claim verbatim, update "
                f"the vendored JSON + META.json, and re-run the hook_contract "
                f"QA check."
            ),
        ]
        return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=context)

    def _read_meta(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # An install without the vendored contract (or with a corrupt one)
            # must not fail session start — the QA guard owns that failure.
            logger.debug("contract META unreadable (%s): %s", self.meta_path, exc)
            return None
        return data if isinstance(data, dict) else None

    def parse_version_output(self, output: str) -> str | None:
        """Extract the leading semantic version from ``claude --version`` output."""
        match = _VERSION_PATTERN.search(output)
        return match.group(1) if match else None

    def _cache_file(self) -> Path:
        try:
            return ProjectContext.daemon_untracked_dir() / _CACHE_FILENAME
        except (OSError, RuntimeError):
            fallback = Path.cwd() / "untracked"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback / _CACHE_FILENAME

    def _read_installed_version(self) -> str | None:
        cache_file = self._cache_file()
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if time.time() - float(cached.get(_CACHE_TIME_KEY, 0)) < _CACHE_TTL_SECONDS:
                version = cached.get(_CACHE_VERSION_KEY)
                if isinstance(version, str):
                    return version
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.debug("contract staleness cache unreadable: %s", exc)

        binary = shutil.which(_CLAUDE_BINARY)
        if binary is None:
            return None
        # SECURITY: fixed argv, no shell, binary resolved via PATH lookup.
        try:
            result = subprocess.run(  # nosec B603
                [binary, _CLAUDE_VERSION_FLAG],
                capture_output=True,
                text=True,
                timeout=Timeout.VERSION_CHECK,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("claude --version probe failed: %s", exc)
            return None
        if result.returncode != 0:
            return None
        version = self.parse_version_output(result.stdout)
        if version is not None:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(
                    json.dumps({_CACHE_TIME_KEY: time.time(), _CACHE_VERSION_KEY: version})
                )
            except OSError as exc:
                logger.debug("contract staleness cache unwritable: %s", exc)
        return version

    def _is_newer(self, installed: str, audited: str) -> bool:
        """True when ``installed`` > ``audited`` (semantic compare)."""
        try:
            installed_parts = [int(x) for x in installed.split(".")]
            audited_parts = [int(x) for x in audited.split(".")]
        except ValueError:
            return False
        while len(installed_parts) < len(audited_parts):
            installed_parts.append(0)
        while len(audited_parts) < len(installed_parts):
            audited_parts.append(0)
        return installed_parts > audited_parts

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests rendered into the release playbook."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="contract staleness advisory",
                command='echo "test"',
                description=(
                    "On a new session with Claude Code newer than the vendored "
                    "contract's last-audited version, an advisory recommends the "
                    "refresh procedure; otherwise silent"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                safety_notes="Advisory handler - read-only version comparison",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session, not resume)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
