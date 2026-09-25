"""Fixture for the ``freshness-verdict-read-piecemeal`` semgrep rule (Plan 00415).

DELIBERATELY DEFECTIVE CODE. Nothing here is imported or executed. Each hit
reconstructs a real spelling of the defect this project shipped: a consumer
that pulls ONE fingerprint out of a daemon's health payload and judges
freshness on it alone, so the half it did not read can drift unseen.

Markers drive the assertions in
``tests/unit/qa/test_semgrep_freshness_verdict.py``:

* ``# EXPECT-HIT``   — the rule MUST report this line
* ``# EXPECT-CLEAN`` — the rule MUST NOT report this line
"""

from typing import Any

from claude_code_hooks_daemon.daemon.source_fingerprint import (
    HEALTH_KEY_CONFIG_FINGERPRINT,
    HEALTH_KEY_SOURCE_FINGERPRINT,
    compute_current_project_fingerprints,
    describe_daemon_staleness,
)


def check_source_fresh_as_shipped(response: dict[str, Any]) -> str | None:
    """The originating instance: ``cli.cmd_check_source_fresh`` read code only."""
    return response["result"].get("source_fingerprint")  # EXPECT-HIT


def subscript_read(health: dict[str, Any]) -> str:
    return health["source_fingerprint"]  # EXPECT-HIT


def config_half_only(health: dict[str, Any]) -> str:
    return health.get("config_fingerprint", "")  # EXPECT-HIT


def via_the_named_constant(health: dict[str, Any]) -> str:
    return health[HEALTH_KEY_SOURCE_FINGERPRINT]  # EXPECT-HIT


def via_the_other_named_constant(health: dict[str, Any]) -> str | None:
    return health.get(HEALTH_KEY_CONFIG_FINGERPRINT)  # EXPECT-HIT


def the_supported_route(project_root: str, response: dict[str, Any]) -> str | None:
    """Hand the whole payload to the one combined verdict."""
    health = response.get("result")  # EXPECT-CLEAN
    current = compute_current_project_fingerprints(project_root)  # EXPECT-CLEAN
    return describe_daemon_staleness(health, current)  # EXPECT-CLEAN


def an_unrelated_fingerprint(worker: dict[str, Any]) -> str:
    return worker["venv_fingerprint"]  # EXPECT-CLEAN
