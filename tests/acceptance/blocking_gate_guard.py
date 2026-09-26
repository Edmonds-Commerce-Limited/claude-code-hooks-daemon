"""Turn a skip of a declared-blocking acceptance gate into a failure.

`RELEASING.md` Step 12.0 names the acceptance files a release blocks on, and
states the expectation on the line below the command: *0 failed, 0 skipped*.
About one of them it is explicit:

    The test skips cleanly when no daemon is running locally; under H-1 the
    daemon is always started before this step, **so a skip there is itself an
    abort condition.**

Outside a release nothing enforced that, and pytest counts a skip as neither a
pass nor a failure — so CI ran every one of those files against no daemon and
reported the run green. The gate was wired in but not load-bearing (Plan 00250).

**The blocking set is READ from that command line, not copied here.** Adding a
file to the declaration extends this guard with no second edit, so the guard
cannot drift from what a release actually gates on. The failure mode that
replaces drift is a parser that stops finding the declaration and silently
guards nothing — which is why `parse_declared_blocking_gate_files` raises on a
missing, duplicated or argument-less declaration rather than returning an empty
set.

The consequence is deliberate wherever it applies: any skip in a declared file
escalates to a failure, including an environment skip such as "uv not
installed". RELEASING.md declares *0 skipped*, and a gate that did not run is
not a gate. The failure message carries the original reason so the fix is
obvious.

**Escalation also requires ``HOOKS_DAEMON_RELEASE_GATE=1`` (Plan 00466 N39
widened).** File identity alone used to be sufficient, which made ANY whole-
suite run that happens to collect these files -- not only RELEASING.md's own
Step 12.0 invocation and CI's daemon-backed run, both of which mean to be the
release gate -- hard-ERROR on the ordinary "no daemon running" skip every
other daemon-dependent test in the suite gets cleanly. The env var is the
explicit signal that THIS invocation means to be held to *0 skipped*;
RELEASING.md's own command block and the CI workflow's daemon-start step both
set it, so neither loses today's coverage. Anything else -- an ad hoc
``pytest tests/`` with no daemon running -- now gets the ordinary skip.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

#: Set by RELEASING.md Step 12.0's own command block, and by the CI workflow's
#: daemon-start step -- the explicit signal that THIS pytest invocation means
#: to be held to the release gate's "0 failed, 0 skipped" expectation. Its
#: absence is what lets an ordinary ad hoc whole-suite run collect these same
#: files without hard-erroring on a plain "no daemon running" skip.
_RELEASE_GATE_ENV_VAR = "HOOKS_DAEMON_RELEASE_GATE"

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASING_MD = REPO_ROOT / "CLAUDE" / "development" / "RELEASING.md"

_DECLARED_PATH = re.compile(r"tests/acceptance/[A-Za-z0-9_]+\.py")

_SKIP_PREFIX = "Skipped: "


def _declaration_lines(releasing_md_text: str) -> list[str]:
    return [
        line
        for line in releasing_md_text.splitlines()
        if "pytest" in line and "tests/acceptance/" in line
    ]


def parse_declared_blocking_gate_files(releasing_md_text: str) -> tuple[str, ...]:
    """Read the blocking set off RELEASING.md's Step 12.0 command line.

    Returns bare file names. The acceptance directory is flat, so a name
    identifies a file uniquely — and matching on the name rather than the
    repo-relative path lets the guard recognise a gate however pytest happens
    to have spelled its path.
    """
    lines = _declaration_lines(releasing_md_text)
    if len(lines) != 1:
        raise AssertionError(
            f"Expected exactly one line invoking pytest on tests/acceptance/ in "
            f"{RELEASING_MD.name} (Step 12.0), found {len(lines)}. That command "
            f"line is the sole declaration of the blocking release gates; "
            f"without it this guard would silently protect nothing. Restore it, "
            f"or update this parser to match its new shape."
        )

    names = tuple(sorted({Path(match).name for match in _DECLARED_PATH.findall(lines[0])}))
    if not names:
        raise AssertionError(
            f"The Step 12.0 command line in {RELEASING_MD.name} names no test "
            f"files, so there is nothing to gate a release on: {lines[0]!r}"
        )
    return names


@lru_cache(maxsize=1)
def declared_blocking_gate_files() -> tuple[str, ...]:
    """The blocking set as this repo currently declares it.

    Cached: the hook below consults it once per acceptance test report.
    """
    return parse_declared_blocking_gate_files(RELEASING_MD.read_text(encoding="utf-8"))


def skip_is_an_abort_condition(test_file: Path | str) -> bool:
    return Path(test_file).name in declared_blocking_gate_files()


def release_gate_invocation() -> bool:
    """True when THIS pytest invocation declares itself the release gate.

    Checked against the EXACT declared value, not any truthy string -- a
    stray ``true``/``yes`` set for an unrelated purpose must not silently
    opt a run in to the release gate's stricter contract.
    """
    return os.environ.get(_RELEASE_GATE_ENV_VAR) == "1"


def should_escalate_skip(test_file: Path | str) -> bool:
    """Whether a skip of ``test_file`` should become a failure right now.

    Both conditions are required: the file must be one of the declared
    blocking gates (otherwise every skip anywhere would fail), AND this
    invocation must have declared itself the release gate (otherwise an
    ordinary ad hoc run gets the same harmless skip every other
    daemon-dependent test in the suite gets).
    """
    return skip_is_an_abort_condition(test_file) and release_gate_invocation()


def _skip_reason(longrepr: Any) -> str:
    """Recover the reason from a skipped report's `(path, lineno, reason)`."""
    reason = str(longrepr[2]) if isinstance(longrepr, tuple) else str(longrepr)
    return reason[len(_SKIP_PREFIX) :] if reason.startswith(_SKIP_PREFIX) else reason


def blocking_gate_skip_failure_message(test_file: Path | str, skip_reason: str) -> str:
    name = Path(test_file).name
    return (
        f"{name} is a BLOCKING release gate, declared by RELEASING.md Step 12.0, "
        f"which expects '0 failed, 0 skipped'. A skip here is an abort "
        f"condition, not a pass — the gate did not run.\n\n"
        f"Original skip reason: {skip_reason}\n\n"
        f"Satisfy the gate's precondition instead of accepting the skip — for a "
        f"daemon skip that is './bin/hooks-daemon restart'. To stop guarding "
        f"this file, remove it from the pytest command line in RELEASING.md "
        f"Step 12.0; that command line is the only declaration there is."
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
    report = yield
    if report.skipped and should_escalate_skip(item.path):
        report.outcome = "failed"
        report.longrepr = blocking_gate_skip_failure_message(
            item.path, _skip_reason(report.longrepr)
        )
    return report
