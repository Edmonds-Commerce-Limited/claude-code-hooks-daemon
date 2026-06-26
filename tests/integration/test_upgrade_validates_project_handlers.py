"""Contract: the upgrade flow validates project handlers (Plan 00143).

An upgrade can introduce a new required handler method that older project
handlers do not implement yet, silently disabling them. ``upgrade_version.sh``
must run ``validate-project-handlers`` post-upgrade and LOUDLY warn — but must
NOT fail the upgrade (the daemon is healthy; it skipped the broken handlers
safely). These tests pin that contract so the gate cannot silently regress.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"


def _script_text() -> str:
    return UPGRADE_SH.read_text(encoding="utf-8")


def _project_handler_validation_block() -> str:
    """Return the Step 16.5 project-handler validation block text."""
    text = _script_text()
    start = text.index("Step 16.5")
    end = text.index("Step 17", start)
    return text[start:end]


class TestUpgradeValidatesProjectHandlers:
    def test_upgrade_invokes_validate_project_handlers(self) -> None:
        assert "validate-project-handlers" in _script_text()

    def test_validation_is_in_a_dedicated_step(self) -> None:
        block = _project_handler_validation_block()
        assert "validate-project-handlers" in block

    def test_validation_warns_loudly_on_failure(self) -> None:
        block = _project_handler_validation_block()
        assert "print_warning" in block
        assert "PROJECT PROTECTION DEGRADED" in block

    def test_validation_does_not_fail_the_upgrade(self) -> None:
        """The gate is defence-in-depth — it warns, it must not abort."""
        block = _project_handler_validation_block()
        assert "exit 1" not in block
        assert "exit 2" not in block

    def test_validation_tells_user_to_restart(self) -> None:
        block = _project_handler_validation_block()
        assert "restart" in block
