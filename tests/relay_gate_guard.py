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

**A root-conditioned skip is a different defect, caught elsewhere.** This
guard's own tests exercise `skip_is_a_provisioning_failure("Running as
root", ...)` as the "unrelated skip, leave it alone" case, which stays
correct: converting a root skip into THIS guard's message would point at
`relay/build.sh`, which has nothing to do with it. Plan 00466 N56 bans a
root-conditioned skip outright, everywhere under `tests/`, regardless of CI —
enforced statically (not just when it fires) by
`tests/integration/test_no_root_conditioned_skips.py`. The two guards are
complementary: that one fails a `skipif`/`xfail`/hand-written root check at
collection time everywhere, this one turns a specific relay-provisioning
*reason string* into a hard failure only in CI.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
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


_REPO_ROOT = Path(__file__).resolve().parent.parent
_RELAY_SOURCE = _REPO_ROOT / "relay" / "hooks_relay.rs"
_RELAY_BUILD = _REPO_ROOT / "untracked" / "relay-build" / "hooks-relay-x86_64-unknown-linux-musl"


def relay_build_stamp_path(binary: Path) -> Path:
    """The sidecar `relay/build.sh` writes beside a build: the source's sha256."""
    return binary.with_name(binary.name + ".source-sha256")


def relay_build_staleness_message(binary: Path, source: Path) -> str | None:
    """Explain why a built relay is stale, or None when it is fresh or absent.

    Staleness is a content stamp, not an mtime: mtime moves on every git
    checkout. A binary with no sidecar predates the stamp and counts as stale.
    An absent binary is not stale; the consuming tests skip on that already.
    """
    if not binary.exists():
        return None
    stamp = relay_build_stamp_path(binary)
    current = hashlib.sha256(source.read_bytes()).hexdigest()
    if stamp.is_file() and stamp.read_text().strip() == current:
        return None
    return (
        f"the relay build at {binary} is older than relay/hooks_relay.rs; "
        "rebuild with `bash relay/build.sh`"
    )


@pytest.fixture(scope="session")
def fresh_relay_build() -> None:
    """Fail, with one clear message, when the local relay build is stale.

    Not a skip: a skip would hide a real relay regression.
    """
    message = relay_build_staleness_message(_RELAY_BUILD, _RELAY_SOURCE)
    if message is not None:
        pytest.fail(message, pytrace=False)


__all__ = [
    "RELAY_SKIP_MARKERS",
    "fresh_relay_build",
    "pytest_runtest_makereport",
    "relay_build_staleness_message",
    "relay_build_stamp_path",
    "relay_skip_failure_message",
    "running_in_ci",
    "skip_is_a_provisioning_failure",
]
