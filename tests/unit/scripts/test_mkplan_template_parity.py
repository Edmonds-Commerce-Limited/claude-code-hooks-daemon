"""The deployed ``mkplan.bash`` and the bundled template must not drift (N371).

A one-sided edit is otherwise caught only by the session-start
``deployed_artefact_drift`` advisory, after the fact.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATE = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates" / "mkplan.bash"
)
_DEPLOYED = _REPO_ROOT / "CLAUDE" / "Plan" / "mkplan.bash"


def test_deployed_mkplan_is_byte_identical_to_the_bundled_template() -> None:
    assert _DEPLOYED.read_bytes() == _TEMPLATE.read_bytes()
