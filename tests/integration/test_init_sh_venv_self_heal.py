"""A clone with no venv for this path heals itself from the hook path (Plan 00456, #53).

Plan 00454 gave the "clone present, venv missing for this project path" state
its own message. This module pins what init.sh now DOES in that state. It
calls the clone's ``scripts/venv_bootstrap.sh hook``, which checks the five
``can_inline_bootstrap`` preconditions with no venv and, when they hold,
starts ONE detached build under the venv build lock. The message says which of
these happened:

- a build started, or is already running (with its log);
- the last build failed (with its log and ``repair``), and is not retried;
- the build was refused, with each failed condition and its fix, and
  nothing changed;
- the opt-out is set.

It never recommends install or ``--force``. Once the build finishes, the next
hook starts the daemon from the new venv. The sandbox is described in
``tests/venv_bootstrap_sandbox.py``.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.venv_bootstrap_sandbox import (
    BASH,
    CLONE_VERSION,
    TIMEOUT_SECONDS,
    Sandbox,
    assert_never_suggests_install_or_force,
    snapshot,
)


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    yield box
    box.cleanup()


def _context(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    return str(payload["hookSpecificOutput"]["additionalContext"])


class TestTheHookHealsTheVenv:
    def test_the_first_hook_starts_a_build_and_says_so(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        started = time.monotonic()
        context = _context(sandbox.hook())
        elapsed = time.monotonic() - started

        assert "build" in context.lower() and "started" in context.lower(), context
        log_lines = [ln for ln in context.splitlines() if ".venv-bootstrap-" in ln]
        assert log_lines, f"the message must name the build's log:\n{context}"
        assert str(sandbox.clone / "untracked") in log_lines[0]
        assert_never_suggests_install_or_force(context)
        assert elapsed < 20, f"the hook must return without waiting for the build ({elapsed:.1f}s)"
        sandbox.wait_for_build()
        assert len(sandbox.uv_calls()) == 1

    def test_concurrent_hooks_start_exactly_one_build(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(sleep=3)
        procs = [
            subprocess.Popen(  # nosec B603 - fixed argv, no shell
                sandbox.hook_argv(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=sandbox.env(),
            )
            for _ in range(5)
        ]
        contexts: list[str] = []
        for proc in procs:
            stdout, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
            assert proc.returncode == 0, stderr
            contexts.append(json.loads(stdout)["hookSpecificOutput"]["additionalContext"])

        sandbox.wait_for_build()
        assert len(sandbox.uv_calls()) == 1, sandbox.uv_calls()
        started = [c for c in contexts if "build has started" in c.lower()]
        assert len(started) == 1, contexts
        assert all("build" in c.lower() for c in contexts)

    def test_the_next_hook_after_the_build_starts_the_daemon(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        _context(sandbox.hook())
        sandbox.wait_for_build()

        result = sandbox.hook()

        assert "ENSURE_DAEMON_OK" in result.stdout, result.stdout + result.stderr
        starts = sandbox.start_log.read_text().splitlines()
        assert len(starts) == 1, starts
        built = Path(starts[0])
        assert built.parent.parent.parent == sandbox.clone / "untracked"
        assert built.parent.parent.name.startswith("venv-")

    def test_another_environments_venv_is_byte_for_byte_untouched(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        other = sandbox.other_view_venv()
        before = snapshot(other)

        _context(sandbox.hook())
        sandbox.wait_for_build()
        assert "ENSURE_DAEMON_OK" in sandbox.hook().stdout

        assert snapshot(other) == before

    def test_a_hook_during_the_build_says_it_is_running(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(sleep=3)
        _context(sandbox.hook())
        context = _context(sandbox.hook())
        assert "already running" in context.lower(), context
        assert ".venv-bootstrap-" in context
        assert_never_suggests_install_or_force(context)
        sandbox.wait_for_build()


class TestAFailedBuild:
    def test_is_reported_with_its_log_and_repair_and_is_not_respawned(
        self, sandbox: Sandbox
    ) -> None:
        sandbox.stub_uv(fail=True)
        _context(sandbox.hook())
        sandbox.wait_for_build()

        contexts = [_context(sandbox.hook()) for _ in range(3)]

        assert len(sandbox.uv_calls()) == 1, "a failed build must not respawn on every hook"
        for context in contexts:
            assert "failed" in context.lower(), context
            assert ".venv-bootstrap-" in context
            assert f"{sandbox.clone}/bin/hooks-daemon repair" in context
            assert_never_suggests_install_or_force(context)


class TestARefusedBuildChangesNothing:
    def test_uv_missing_names_the_condition_and_its_fix(self, sandbox: Sandbox) -> None:
        other = sandbox.other_view_venv()
        before = snapshot(sandbox.clone)
        other_before = snapshot(other)

        context = _context(sandbox.hook())

        assert snapshot(sandbox.clone) == before, "a refused build must change nothing"
        assert snapshot(other) == other_before
        assert "uv:" in context, context
        assert "docs.astral.sh/uv" in context
        assert "nothing was changed" in context.lower()
        assert_never_suggests_install_or_force(context)

    def test_the_opt_out_is_named_and_nothing_changes(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        before = snapshot(sandbox.clone)

        context = _context(sandbox.hook(extra_env={"HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP": "1"}))

        assert "HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP" in context
        assert snapshot(sandbox.clone) == before
        assert sandbox.uv_calls() == []

    def test_ci_true_is_named_never_reported_as_a_failed_build(self, sandbox: Sandbox) -> None:
        """Review B1: CI=true makes ensure_venv skip, so the hook must not start
        a "build" that runs no uv and then report it FAILED on every hook."""
        sandbox.stub_uv()
        before = snapshot(sandbox.clone)

        contexts = [_context(sandbox.hook(extra_env={"CI": "true"})) for _ in range(2)]

        for context in contexts:
            assert "CI=true" in context, context
            assert "failed" not in context.lower(), context
            assert f"{sandbox.clone}/bin/hooks-daemon repair" in context
            assert_never_suggests_install_or_force(context)
        assert snapshot(sandbox.clone) == before
        assert sandbox.uv_calls() == []


class TestNoBuildIsAttemptedWhereThe00454CasesSayDoNotTouch:
    def test_an_unreadable_clone_version_never_builds(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        (sandbox.clone / "src" / "claude_code_hooks_daemon" / "version.py").write_text("# cut\n")
        context = _context(sandbox.hook())
        assert sandbox.uv_calls() == []
        assert "damaged" in context.lower()
        assert "args=install" not in context.lower()

    def test_an_orphan_venv_without_a_clone_never_builds(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv()
        sandbox.other_view_venv()
        (sandbox.clone / "scripts" / "lib" / "resolve_venv.sh").unlink()
        context = _context(sandbox.hook())
        assert sandbox.uv_calls() == []
        assert "install/force" in context.lower()

    def test_a_clone_without_the_driver_keeps_the_00454_message(self, sandbox: Sandbox) -> None:
        """A newer init.sh over an older clone: no crash, the upgrade advice."""
        sandbox.stub_uv()
        (sandbox.clone / "scripts" / "venv_bootstrap.sh").unlink()
        context = _context(sandbox.hook())
        assert f"args=upgrade {CLONE_VERSION}" in context
        assert sandbox.uv_calls() == []


class TestTheStopFamilyAndTheFallbackEncoder:
    def test_stop_blocks_and_says_a_build_is_running(self, sandbox: Sandbox) -> None:
        sandbox.stub_uv(sleep=3)
        _context(sandbox.hook())
        result = sandbox.hook(event="Stop")
        parsed = json.loads(result.stdout)
        assert parsed["decision"] == "block"
        reason = str(parsed["reason"]).lower()
        assert "venv" in reason and "build" in reason
        assert "not installed" not in reason
        sandbox.wait_for_build()

    def test_the_jq_less_encoder_carries_the_same_context(self, sandbox: Sandbox) -> None:
        with_jq = _context(sandbox.hook())
        (sandbox.root / "tools" / "jq").unlink()
        without_jq = _context(sandbox.hook())
        assert with_jq == without_jq
        assert "uv:" in without_jq


class TestTheHealthyPathIsUntouched:
    """Evaluated ONLY in the venv-missing branch: no added cost elsewhere."""

    def _plant_recording_driver(self, sandbox: Sandbox) -> Path:
        calls = sandbox.root / "driver-calls.log"
        driver = sandbox.clone / "scripts" / "venv_bootstrap.sh"
        driver.write_text(f'#!/bin/bash\necho "$*" >> "{calls}"\necho state=disabled\n')
        return calls

    def _source_and_run(self, sandbox: Sandbox, script: str) -> subprocess.CompletedProcess[str]:
        init_sh = sandbox.project / ".claude" / "init.sh"
        return sandbox.run([BASH, "-c", f'source "{init_sh}"\n{script}'])

    def test_a_running_daemon_never_reaches_the_driver(self, sandbox: Sandbox) -> None:
        calls = self._plant_recording_driver(sandbox)
        result = self._source_and_run(
            sandbox, "is_daemon_running() { return 0; }\nensure_daemon && echo OK"
        )
        assert "OK" in result.stdout, result.stderr
        assert not calls.exists()

    def test_a_resolvable_venv_whose_daemon_fails_never_reaches_the_driver(
        self, sandbox: Sandbox
    ) -> None:
        sandbox.stub_uv()
        _context(sandbox.hook())
        sandbox.wait_for_build()
        calls = self._plant_recording_driver(sandbox)
        result = self._source_and_run(
            sandbox,
            "_is_ci_environment() { return 1; }\n_is_ci_enforced() { return 1; }\n"
            "start_daemon() { validate_venv; return 1; }\n"
            'ensure_daemon || echo "missing=$_HOOKS_DAEMON_VENV_MISSING"',
        )
        assert "missing=false" in result.stdout, result.stdout + result.stderr
        assert not calls.exists()
