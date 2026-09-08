"""Turn a relay-provisioning skip into a failure, but only where CI provisions.

Fourteen transport gates — 11 in `tests/acceptance/test_transport_toggle_cycle.py`
and 3 in `tests/integration/test_relay_guard_fail_open.py` — skip when the
compiled relay binary is missing. It lives under gitignored `untracked/`, so it
is absent from every fresh checkout, and pytest counts a skip as neither a pass
nor a failure: the gates were wired in, correct, and never load-bearing on a
runner (Plan 00350, and the same shape as Plan 00250's daemon gates).

`.github/workflows/qa.yml` now builds and deploys the binary before the suite
runs, which makes the skip condition unreachable there. So on CI a skip for
that reason no longer means "this machine cannot run it" — it means the
provisioning stopped working, and reporting that as a skip would hide exactly
what the build step was added to prevent.

**Keyed on the reason, not on a file list.** The two files spell their skip
differently and sit in different directories, and a third could be added
tomorrow; what they have in common is the artefact they need. Matching the
reason also keeps the guard narrow — an unrelated environment skip in the same
file is still a skip.

**Keyed on `CI`, so nothing changes locally.** A developer without a Rust
toolchain genuinely cannot run these and is not the defect this guards.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

#: The reasons the relay-dependent gates give when the binary is absent, as
#: they are spelled at the `pytest.skip` / `skipif` sites. Asserted against
#: those files in `test_relay_gate_skip_guard.py`, so a rewording that orphaned
#: a marker fails rather than silently disarming the guard.
RELAY_SKIP_MARKERS: tuple[str, ...] = (
    "relay binary not built",
    "no built relay binary",
)

_SKIP_PREFIX = "Skipped: "


def running_in_ci() -> bool:
    """GitHub Actions sets `CI=true`; so does essentially every other runner."""
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def skip_is_a_provisioning_failure(skip_reason: str, *, in_ci: bool) -> bool:
    return in_ci and any(marker in skip_reason for marker in RELAY_SKIP_MARKERS)


def relay_skip_failure_message(skip_reason: str) -> str:
    return (
        "A relay-dependent gate skipped in CI, where the workflow builds the "
        "relay before the suite runs — so this is the provisioning failing, "
        "not a machine that cannot run the test.\n\n"
        f"Original skip reason: {skip_reason}\n\n"
        "The 'Build the relay (for the transport gates)' step in "
        ".github/workflows/qa.yml runs `bash relay/build.sh` and installs the "
        "result at untracked/bin/hooks-relay. Check that step ran, and that the "
        "two paths it writes are still the two the gates read — they are "
        "hardcoded on both sides and nothing else couples them."
    )


def _skip_reason(longrepr: Any) -> str:
    """Recover the reason from a skipped report's `(path, lineno, reason)`."""
    reason = str(longrepr[2]) if isinstance(longrepr, tuple) else str(longrepr)
    return reason[len(_SKIP_PREFIX) :] if reason.startswith(_SKIP_PREFIX) else reason


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
    report = yield
    if report.skipped:
        reason = _skip_reason(report.longrepr)
        if skip_is_a_provisioning_failure(reason, in_ci=running_in_ci()):
            report.outcome = "failed"
            report.longrepr = relay_skip_failure_message(reason)
    return report


__all__ = [
    "RELAY_SKIP_MARKERS",
    "pytest_runtest_makereport",
    "relay_skip_failure_message",
    "running_in_ci",
    "skip_is_a_provisioning_failure",
]
