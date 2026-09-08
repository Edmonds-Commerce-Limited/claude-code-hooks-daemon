"""Execute the playbook's declared probes against the live daemon (Plan 00243).

RELEASING.md Step 12 asks a human to work through ~119 prose instructions by
hand. Every test that declares a `tool_payload` can instead be dispatched, and
this is what dispatches them: the payload goes into a hook event, the event
goes to the PRODUCTION bash wrapper as a subprocess, and the daemon answers
with the decision it would really have made. That exercises the whole
forwarder -> socket -> daemon -> handler-chain path, which is the path a
release actually depends on.

**The probes are inert.** A command payload is DATA. It is placed in
`tool_input` and handed to the wrapper, which returns a decision; no shell
ever runs it. That is what makes it safe to probe `git reset --hard` and
`rm -rf` at all.

**What this file must never do is invent a failure.** Plan 00241 Phase 2
discarded a 23-handler guard for exactly that, and Task 1.2's own ad-hoc
checker reported 29 failures of which all 29 were artefacts of the checker.
The judgement calls that prevent it are unit-tested in
`tests/unit/daemon/test_playbook_harness.py`; this file owns only the parts
that need a live daemon.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon.playbook_harness import (
    ExecutableProbe,
    FixtureAction,
    SkippedProbe,
    build_event,
    daemon_error,
    split_playbook,
    verdict,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOCKET_GLOB = "daemon-*.sock"
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
DAEMON_CLI = REPO_ROOT / "bin" / "hooks-daemon"

#: Generous next to a hook dispatch: this subprocess imports every handler
#: module and renders all ~287 blocks, so its cost tracks handler COUNT.
_GENERATE_TIMEOUT_SECONDS = 180

#: Fresh per run, so a once-per-session handler answers this run's probe
#: rather than remembering the last one. `lsp_enforcement` is `block_once` by
#: default and made the harness pass, then fail on re-run, with nothing about
#: the handler having changed.
_RUN_ID = uuid.uuid4().hex[:8]

#: The wrapper per dispatchable event. Named rather than derived from the
#: event string so an event the harness has no wrapper for fails loudly here
#: instead of silently running nothing.
_WRAPPERS = {
    "PreToolUse": HOOKS_DIR / "pre-tool-use",
    "PostToolUse": HOOKS_DIR / "post-tool-use",
}


def _socket_is_alive(sock_path: Path) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(Timeout.SOCKET_LIVENESS_PROBE_SEC)
            sock.connect(str(sock_path))
        return True
    except OSError:
        return False


def _discover_socket() -> Path | None:
    env_path = os.environ.get("CLAUDE_HOOKS_SOCKET_PATH")
    if env_path and Path(env_path).is_socket() and _socket_is_alive(Path(env_path)):
        return Path(env_path)
    for candidate in sorted((REPO_ROOT / "untracked").glob(SOCKET_GLOB)):
        if candidate.is_socket() and _socket_is_alive(candidate):
            return candidate
    return None


@pytest.fixture(scope="module")
def daemon_running() -> None:
    """Skip rather than fail when no daemon is up, matching the siblings here."""
    if _discover_socket() is None:
        pytest.skip("Daemon not running — start with: ./bin/hooks-daemon restart")


@pytest.fixture(scope="module")
def playbook(daemon_running: None) -> list[dict]:
    """Every block, from the production generator.

    Generated into memory rather than read from `untracked/playbook.md`: that
    file is an artefact nothing keeps current, so a harness reading it can
    silently test a playbook older than the handlers it is checking.
    """
    result = subprocess.run(
        [str(DAEMON_CLI), "generate-playbook", "--format", "json"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=_GENERATE_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"generate-playbook failed: {result.stderr[-600:]}")
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def partitioned(playbook: list[dict]) -> tuple[list[ExecutableProbe], list[SkippedProbe]]:
    return split_playbook(playbook, REPO_ROOT)


def _response_text(payload: dict) -> str:
    """Every place a handler's message can land, concatenated.

    A pattern is asserted against the response as a whole rather than against
    one named key: a deny reason, an advisory context and a system message are
    different keys, and pinning the key would make a correct message read as a
    missing one.
    """
    hook_specific = payload.get("hookSpecificOutput") or {}
    parts = [
        hook_specific.get("permissionDecisionReason"),
        hook_specific.get("additionalContext"),
        payload.get("reason"),
        payload.get("systemMessage"),
    ]
    return "\n".join(str(part) for part in parts if part)


def _response_decision(payload: dict) -> str:
    hook_specific = payload.get("hookSpecificOutput") or {}
    return str(hook_specific.get("permissionDecision") or payload.get("decision") or "")


def _dispatch(probe: ExecutableProbe) -> tuple[str, str, str | None]:
    """Send one probe to the production wrapper; return (decision, text, error).

    Both the SUBPROCESS and the EVENT are rooted at the repository: the wrapper
    needs it to find the daemon socket, and the event needs it because `cwd` is
    part of a Bash probe's input rather than framing around it.

    An isolated temp directory for the event `cwd` measured as changing
    nothing, but that measurement only ever covered WRITE payloads, whose
    `file_path` is absolute and so cannot notice. Extending payloads to the
    shell blocks is what exposed the cost — see `build_event`, which now owns
    the choice so this caller cannot make it wrongly.
    """
    wrapper = _WRAPPERS[probe.event_type]
    result = subprocess.run(
        ["bash", str(wrapper)],
        input=json.dumps(build_event(probe, _RUN_ID)),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=Timeout.DAEMON_RESTART_VERIFY_TIMEOUT_SEC,
        check=False,
    )
    raw = (result.stdout or "").strip()
    if not raw:
        # No output at all is the shape a handler chain takes when nothing
        # matched — an allow by silence, not a malfunction.
        return "", "", None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return "", raw, f"response was not JSON: {raw[:200]!r}"
    return _response_decision(payload), _response_text(payload), daemon_error(payload)


def _is_removable_probe_target(target: Path) -> bool:
    """Only ever clear a path the probe itself is entitled to own.

    The harness deletes a leftover target so a PreToolUse event is not
    describing a clobber, and a delete is the one thing here that could
    destroy work rather than merely misreport. So it is bounded to the two
    sanctioned probe locations — gitignored scratch inside the repo, and the
    system temp directory — rather than trusted to the playbook's own path.
    """
    scratch = REPO_ROOT / "untracked" / "scratch"
    temp_root = Path(tempfile.gettempdir())
    return target.is_relative_to(scratch) or target.is_relative_to(temp_root)


def _perform(actions: list[FixtureAction]) -> None:
    """Establish (or clear) a probe's fixtures, as plain filesystem calls.

    No shell. `vet_probe_commands` has already translated each declared command
    into one of three operations and proved its path resolves inside
    `untracked/scratch/`, so what arrives here is data rather than a string
    anything could interpret. That translation is the reason the permitted list
    is closed: a shape nobody has mapped to an operation is a shape nobody runs.
    """
    for action in actions:
        if not _is_removable_probe_target(action.path):
            raise AssertionError(f"vetting let through an out-of-bounds path: {action.path}")
        if action.kind == "mkdir":
            action.path.mkdir(parents=True, exist_ok=True)
        elif action.kind == "remove":
            if action.path.is_dir():
                shutil.rmtree(action.path, ignore_errors=True)
            elif action.path.exists():
                action.path.unlink()
        elif action.kind == "write":
            action.path.parent.mkdir(parents=True, exist_ok=True)
            action.path.write_text(action.content, encoding="utf-8")
        else:
            raise AssertionError(f"unknown fixture action kind: {action.kind!r}")


def _run_probe(probe: ExecutableProbe) -> str | None:
    """Dispatch one probe, making the world match what its event claims."""
    created: Path | None = None
    target = Path(probe.file_path) if probe.file_path else None

    _perform(probe.setup_actions)

    if target is not None and _is_removable_probe_target(target):
        if probe.requires_existing_file:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = probe.tool_input.get("content") or probe.tool_input.get("new_string") or ""
            target.write_text(str(content), encoding="utf-8")
            created = target
        elif probe.requires_absent_file and target.exists():
            # Residue from an earlier run, which would otherwise make this a
            # clobber rather than the new write the event claims.
            target.unlink()
    try:
        decision, text, error = _dispatch(probe)
        if error is not None:
            return f"the daemon rejected the event, so no handler ran: {error}"
        return verdict(probe, decision, text)
    finally:
        if created is not None and created.exists():
            created.unlink()
        # Cleanup matters more here than tidiness: a fixture left behind is a
        # file the NEXT run's probe can pass on without having established it.
        # Measured, not hypothetical — #148 passed on an `authored.py` a human
        # left in scratch two days earlier, because `lint_on_edit._is_lintable`
        # ends at `Path(file_path).exists()` and does not care who wrote it.
        _perform(probe.cleanup_actions)


class TestThePlaybookIsReachable:
    def test_the_generator_returns_a_populated_playbook(self, playbook: list[dict]) -> None:
        """Guards every assertion below from passing vacuously."""
        assert len(playbook) > 100

    def test_a_substantial_share_of_blocks_are_executable(
        self, partitioned: tuple[list[ExecutableProbe], list[SkippedProbe]]
    ) -> None:
        """The whole point is to shrink the manual gate, so measure it.

        A regression that quietly reclassified most probes as skips would
        otherwise leave every other test here green while the harness checked
        almost nothing.
        """
        executable, _ = partitioned
        assert len(executable) >= 185, (
            f"only {len(executable)} blocks are executable; Plan 00345 left 195 "
            "declaring a payload, so a large drop means the field stopped "
            "being read rather than that the tests changed"
        )


class TestEveryBlockIsAccountedFor:
    def test_the_partition_loses_nothing(
        self,
        playbook: list[dict],
        partitioned: tuple[list[ExecutableProbe], list[SkippedProbe]],
    ) -> None:
        """Success criterion 2: no test silently falls between the routes."""
        executable, skipped = partitioned
        assert len(executable) + len(skipped) == len(playbook)

    def test_every_skip_carries_a_reason(
        self, partitioned: tuple[list[ExecutableProbe], list[SkippedProbe]]
    ) -> None:
        """A skip nobody can explain is indistinguishable from a gap."""
        _, skipped = partitioned
        assert all(probe.reason.strip() for probe in skipped)


class TestTheDeclaredProbesBehaveAsDeclared:
    def test_every_executable_probe_matches_its_expected_decision_and_reason(
        self,
        partitioned: tuple[list[ExecutableProbe], list[SkippedProbe]],
    ) -> None:
        """The gate: dispatch all of them, report every mismatch at once.

        Reported together rather than one assertion per probe because the
        useful output is the SHAPE of a set of failures. Task 1.2's 29
        mismatches were diagnosable as two systematic artefacts precisely
        because they were visible side by side; the first of them alone would
        have read as a real defect.
        """
        executable, _ = partitioned
        failures = []
        for probe in executable:
            failure = _run_probe(probe)
            if failure is not None:
                failures.append(f"#{probe.test_number} {probe.handler_name}: {failure}")

        assert not failures, (
            f"{len(failures)} of {len(executable)} declared probes did not "
            "behave as the playbook says:\n" + "\n".join(failures)
        )
