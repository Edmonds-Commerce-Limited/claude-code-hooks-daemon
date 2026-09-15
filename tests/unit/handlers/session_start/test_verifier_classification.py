"""Task 2.2: the first two shipped handlers to earn a real verifier.

Plan 00416's admission test for `ACTION_REQUIRED` is narrow on purpose — a
verifier is NECESSARY but not sufficient. The condition must also be
*objectively required*: the session is mis-configured, not merely improvable.
Both handlers here clear that bar for the same reason, and it is the reason
they were named as candidates rather than chosen for convenience — each means
**this session is not protected the way its own config says it is**.

- `project_handler_load_checker`: one or more project handlers failed to load,
  so guards the project declared are simply OFF.
- `hook_registration_checker`: the hook wiring in `settings.json` does not
  match what the daemon needs, so events never arrive.

Neither is a suggestion. An agent that reads past either is working without
protections it has every reason to assume are in force.

**A verifier must be READ-ONLY.** `hook_registration_checker.handle()`
deliberately self-heals (settings migration, then registration repair) before
it reports. A verifier that took that path would MUTATE `settings.json` every
time a tier was computed — including from `bin/hooks-daemon session-actions`,
which a human runs precisely to inspect without changing anything. So the
verifier runs the validators alone, and this file pins that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core.session_start_tiers import (
    SessionTier,
    compute_tier,
    has_verifier,
)
from claude_code_hooks_daemon.handlers.session_start.hook_registration_checker import (
    HookRegistrationCheckerHandler,
)
from claude_code_hooks_daemon.handlers.session_start.project_handler_load_checker import (
    ProjectHandlerLoadCheckerHandler,
)


class _FakeFailure:
    def __init__(self) -> None:
        self.event_dir = "pre_tool_use"
        self.filename = "broken.py"
        self.reason = "SyntaxError"


class _FakeState:
    def __init__(self, *, degraded: bool) -> None:
        self.is_degraded = degraded
        self.failed_count = 1 if degraded else 0
        self.failures = [_FakeFailure()] if degraded else []


class TestProjectHandlerLoadCheckerIsVerifiable:
    def test_it_has_a_real_verifier(self) -> None:
        assert has_verifier(ProjectHandlerLoadCheckerHandler())

    def test_degraded_protection_computes_action_required(self, monkeypatch: Any) -> None:
        handler = ProjectHandlerLoadCheckerHandler()
        monkeypatch.setattr(handler, "_read_state", lambda: _FakeState(degraded=True))

        assert handler.verify_still_needed() is True
        assert compute_tier(handler) is SessionTier.ACTION_REQUIRED

    def test_healthy_protection_does_not(self, monkeypatch: Any) -> None:
        handler = ProjectHandlerLoadCheckerHandler()
        monkeypatch.setattr(handler, "_read_state", lambda: _FakeState(degraded=False))

        assert handler.verify_still_needed() is False
        assert compute_tier(handler) is not SessionTier.ACTION_REQUIRED

    def test_a_raising_verifier_never_reaches_action_required(self, monkeypatch: Any) -> None:
        # The state file can be missing or unreadable. A verifier that blows up
        # must degrade to the declared tier, never to a false alarm.
        def _boom() -> Any:
            raise OSError("state unreadable")

        handler = ProjectHandlerLoadCheckerHandler()
        monkeypatch.setattr(handler, "_read_state", _boom)

        assert compute_tier(handler) is not SessionTier.ACTION_REQUIRED


class TestHookRegistrationCheckerIsVerifiable:
    def test_it_has_a_real_verifier(self) -> None:
        assert has_verifier(HookRegistrationCheckerHandler())

    def test_no_project_root_is_not_action_required(self, monkeypatch: Any) -> None:
        handler = HookRegistrationCheckerHandler()
        monkeypatch.setattr(handler, "_get_project_root", lambda: None)

        assert handler.verify_still_needed() is False
        assert compute_tier(handler) is not SessionTier.ACTION_REQUIRED

    def test_absent_settings_is_not_action_required(self, tmp_path: Path, monkeypatch: Any) -> None:
        # No settings.json at all means "not a hooks-daemon project", which the
        # handler already treats as nothing to say. It must not become an alarm.
        (tmp_path / ".claude").mkdir()
        handler = HookRegistrationCheckerHandler()
        monkeypatch.setattr(handler, "_get_project_root", lambda: tmp_path)

        assert handler.verify_still_needed() is False

    def test_broken_registrations_compute_action_required(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        claude = tmp_path / ".claude"
        claude.mkdir()
        # A hooks block whose command is a bare path is the legacy shape the
        # validators flag; enough to make the audit non-empty.
        (claude / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "hooks": [
                                    {"type": "command", "command": ".claude/hooks/pre-tool-use"}
                                ]
                            }
                        ]
                    }
                }
            )
        )
        handler = HookRegistrationCheckerHandler()
        monkeypatch.setattr(handler, "_get_project_root", lambda: tmp_path)

        assert handler.verify_still_needed() is True
        assert compute_tier(handler) is SessionTier.ACTION_REQUIRED


class TestTheVerifierNeverMutates:
    """The property that makes the verifier safe to call from a CLI report."""

    def test_verifying_does_not_rewrite_settings(self, tmp_path: Path, monkeypatch: Any) -> None:
        claude = tmp_path / ".claude"
        claude.mkdir()
        settings = claude / "settings.json"
        original = json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"hooks": [{"type": "command", "command": ".claude/hooks/pre-tool-use"}]}
                    ]
                }
            }
        )
        settings.write_text(original)
        handler = HookRegistrationCheckerHandler()
        monkeypatch.setattr(handler, "_get_project_root", lambda: tmp_path)

        handler.verify_still_needed()

        assert settings.read_text() == original, (
            "verify_still_needed() ran the self-heal path — a tier computation, "
            "including one from `hooks-daemon session-actions`, must never "
            "rewrite a user's settings.json"
        )
