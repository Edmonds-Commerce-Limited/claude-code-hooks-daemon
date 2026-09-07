"""The config-preservation diff baseline must be the version upgraded FROM.

Plan 00336 Phase 1. ``config_preserve.sh`` Step 5 copies ``$EXAMPLE_CONFIG``
into ``$OLD_DEFAULT_CONFIG`` under the comment "Save the old example config
before checkout (for diff baseline)". On the DOCUMENTED upgrade path that
comment is false: Layer 1 (``upgrade.sh``) checks the target out at its Step 7
and only then invokes Layer 2, and Layer 1 never preserves the pre-checkout
example. So the "old" default is the NEW default, and the diff compares the
user's config against the wrong side of the version boundary.

The consequence was measured, not assumed (Plan 00336 Task 1.2). With the new
default as baseline, a user value that merely EQUALS the old default differs
from the new one, is therefore classified as a customisation, and is preserved
— so a changed default never reaches a user who had accepted the previous one.

That failure is invisible: it looks exactly like honouring a customisation,
and the direction is the safe one, which is why it has gone unnoticed. The
trap for anyone tempted to fix this at merge time: "accepted the old default"
and "deliberately chose this value" are IDENTICAL at the data level. The
baseline is the only thing that separates them, which is why the fix is to
supply a true old-version baseline rather than any heuristic.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import yaml

from claude_code_hooks_daemon.constants import Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1 = REPO_ROOT / "scripts" / "upgrade.sh"
LAYER2 = REPO_ROOT / "scripts" / "upgrade_version.sh"
CONFIG_PRESERVE_SH = REPO_ROOT / "scripts" / "install" / "config_preserve.sh"
BASH = shutil.which("bash") or "/bin/bash"

#: The env var Layer 1 uses to hand the pre-checkout baseline to Layer 2.
HANDOVER_VAR = "HOOKS_DAEMON_OLD_DEFAULT_CONFIG"

#: The env var naming the upgrade process that made the handover. A stale
#: export from an earlier run names a process that has since exited, which is
#: the only signal available to tell "my caller preserved this" from "this was
#: left lying around in someone's shell".
OWNER_VAR = "HOOKS_DAEMON_OLD_DEFAULT_PID"


class TestLayerOnePreservesTheBaselineBeforeCheckout:
    """Layer 1 is the only place that can still see the old default."""

    def test_layer1_captures_the_example_config_before_it_checks_out(self) -> None:
        """The capture must precede the checkout, or it captures the new file.

        Layer 1 already has this exact pattern for ``FROM_VERSION`` at Step 3b
        ("Capture FROM_VERSION before checkout overwrites pyproject.toml") —
        the example config needs the same treatment for the same reason.
        """
        content = LAYER1.read_text()

        capture = re.search(r"hooks-daemon\.yaml\.example", content)
        checkout = re.search(
            r'git -C "\$DAEMON_DIR" (?:checkout|reset --hard --quiet) "\$TARGET_VERSION"',
            content,
        )

        assert capture is not None, (
            "Layer 1 never touches hooks-daemon.yaml.example, so the old default "
            "is gone by the time Layer 2 looks for it."
        )
        assert checkout is not None, "Layer 1 no longer checks out the target version"
        assert capture.start() < checkout.start(), (
            "The example-config capture must happen BEFORE the checkout — after "
            "it, the file on disk is the NEW default."
        )

    def test_layer1_exports_the_baseline_for_layer2(self) -> None:
        """Capturing is useless unless the child process can see the path."""
        content = LAYER1.read_text()

        assert f"export {HANDOVER_VAR}" in content, (
            f"Layer 1 must export {HANDOVER_VAR} so Layer 2 — a separate bash "
            "process — can use the preserved baseline."
        )


def _resolve_streams(
    tmp_path: Path,
    example: Path | None,
    handover: str | None,
    *,
    owner_line: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run ``resolve_old_default_config`` and return both streams."""
    env_line = f'export {HANDOVER_VAR}="{handover}"' if handover is not None else ""
    example_arg = str(example) if example is not None else ""
    script = textwrap.dedent(f"""
        set -uo pipefail
        {env_line}
        {owner_line}
        source "{CONFIG_PRESERVE_SH}"
        resolve_old_default_config "{example_arg}"
        """)
    return subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, cwd=tmp_path, check=False
    )


def _resolve(tmp_path: Path, example: Path | None, handover: str | None) -> tuple[int, str]:
    """Call ``resolve_old_default_config`` and capture ONLY its stdout value."""
    result = _resolve_streams(tmp_path, example, handover, owner_line=f"export {OWNER_VAR}=$$")
    return result.returncode, result.stdout.strip()


class TestBaselineResolutionPrefersTheHandedOverPath:
    """Layer 2 must use the preserved baseline when one was handed to it."""

    def test_the_handed_over_baseline_wins_over_the_on_disk_example(self, tmp_path: Path) -> None:
        """This is the whole point: on disk, the example is already the NEW one."""
        old_default = tmp_path / "old-default.yaml"
        old_default.write_text(yaml.dump({"daemon": {"log_level": "INFO"}}))
        on_disk_example = tmp_path / "hooks-daemon.yaml.example"
        on_disk_example.write_text(yaml.dump({"daemon": {"log_level": "WARNING"}}))

        exit_code, resolved = _resolve(tmp_path, on_disk_example, str(old_default))

        assert exit_code == 0, resolved
        assert resolved, "resolver returned nothing"
        loaded = yaml.safe_load(Path(resolved).read_text())
        assert (
            loaded["daemon"]["log_level"] == "INFO"
        ), "the resolver returned the NEW default; the preserved baseline was ignored"

    def test_it_falls_back_to_the_example_when_nothing_was_handed_over(
        self, tmp_path: Path
    ) -> None:
        """Direct Layer 2 invocation still pre-dates its own checkout.

        Called without Layer 1, Step 5 genuinely does run before Step 6, so
        the on-disk example IS the old default. That path must keep working.
        """
        on_disk_example = tmp_path / "hooks-daemon.yaml.example"
        on_disk_example.write_text(yaml.dump({"daemon": {"log_level": "INFO"}}))

        exit_code, resolved = _resolve(tmp_path, on_disk_example, handover=None)

        assert exit_code == 0, resolved
        assert resolved, "resolver returned nothing on the fallback path"
        loaded = yaml.safe_load(Path(resolved).read_text())
        assert loaded["daemon"]["log_level"] == "INFO"

    def test_a_handed_over_path_that_does_not_exist_falls_back(self, tmp_path: Path) -> None:
        """Fail open. A stale or unreadable handover must not lose the baseline."""
        on_disk_example = tmp_path / "hooks-daemon.yaml.example"
        on_disk_example.write_text(yaml.dump({"daemon": {"log_level": "INFO"}}))

        exit_code, resolved = _resolve(tmp_path, on_disk_example, str(tmp_path / "gone.yaml"))

        assert exit_code == 0, resolved
        assert resolved, "a missing handover must fall back, not return nothing"
        loaded = yaml.safe_load(Path(resolved).read_text())
        assert loaded["daemon"]["log_level"] == "INFO"

    def test_it_returns_nothing_when_there_is_no_baseline_at_all(self, tmp_path: Path) -> None:
        """A fresh install has no previous example; that is not an error."""
        exit_code, resolved = _resolve(tmp_path, tmp_path / "absent.yaml", handover=None)

        assert exit_code == 0, resolved
        assert resolved == "", f"expected an empty result, got {resolved!r}"

    def test_the_resolver_emits_only_the_path_on_stdout(self, tmp_path: Path) -> None:
        """It is a CAPTURED function, so progress output would corrupt the value.

        The v3.10.0 SEV-1 in this project was a single missing ``>&2`` in a
        captured helper; the repo carries a QA gate for exactly this shape.
        """
        on_disk_example = tmp_path / "hooks-daemon.yaml.example"
        on_disk_example.write_text(yaml.dump({"daemon": {"log_level": "INFO"}}))

        resolved = _resolve(tmp_path, on_disk_example, handover=None)[1]

        assert "\n" not in resolved, f"resolver leaked extra stdout lines: {resolved!r}"
        assert Path(
            resolved
        ).is_file(), f"stdout was not a usable path — something leaked into it: {resolved!r}"


def _dead_pid() -> int:
    """A PID that is certainly not running: a child, started and reaped."""
    finished = subprocess.Popen(["true"])
    finished.wait(timeout=Timeout.PROCESS_KILL_WAIT)
    return finished.pid


class TestAStaleHandoverIsNeverUsedSilently:
    """The handover is trusted whenever the file merely EXISTS.

    An export survives for the life of a shell, so re-running the upgrade in
    the same terminal — or invoking Layer 2 directly after a Layer 1 run —
    hands over a baseline from the PREVIOUS upgrade. It is a real config file,
    so every check passes, and the wrong baseline is used without a word. The
    resulting misclassification (an accepted old default read as a deliberate
    customisation) is invisible by construction, which is why saying something
    is the whole fix.

    Behaviour is deliberately unchanged: the resolver still uses the handover.
    Refusing it would break the documented Layer 1 path on any false negative
    — ``ps`` missing, a PID recycled — and the resolver's contract is to fail
    open. The requirement is that it cannot be used SILENTLY.
    """

    def _example(self, tmp_path: Path) -> Path:
        example = tmp_path / "hooks-daemon.yaml.example"
        example.write_text(yaml.dump({"daemon": {"log_level": "WARNING"}}))
        return example

    def _handover(self, tmp_path: Path) -> Path:
        handover = tmp_path / "old-default.yaml"
        handover.write_text(yaml.dump({"daemon": {"log_level": "INFO"}}))
        return handover

    def test_a_handover_whose_upgrade_process_has_exited_is_reported(self, tmp_path: Path) -> None:
        handover = self._handover(tmp_path)

        result = _resolve_streams(
            tmp_path,
            self._example(tmp_path),
            str(handover),
            owner_line=f"export {OWNER_VAR}={_dead_pid()}",
        )

        assert result.returncode == 0, result.stderr
        assert str(handover) in result.stdout, "the resolver must still fail open"
        assert "exited" in result.stderr, f"a stale handover was used silently: {result.stderr!r}"

    def test_a_handover_with_no_recorded_owner_is_reported(self, tmp_path: Path) -> None:
        """An export from a hand-rolled invocation, or from an older Layer 1.

        No owner recorded means nothing can vouch for the baseline, which is
        exactly the case that needs saying out loud rather than assuming.
        """
        handover = self._handover(tmp_path)

        result = _resolve_streams(tmp_path, self._example(tmp_path), str(handover))

        assert result.returncode == 0, result.stderr
        assert str(handover) in result.stdout
        assert "no owning upgrade process" in result.stderr

    def test_a_non_numeric_owner_is_reported_rather_than_probed(self, tmp_path: Path) -> None:
        """``ps -p not-a-pid`` would error; the value is validated first."""
        handover = self._handover(tmp_path)

        result = _resolve_streams(
            tmp_path,
            self._example(tmp_path),
            str(handover),
            owner_line=f'export {OWNER_VAR}="not-a-pid"',
        )

        assert result.returncode == 0, result.stderr
        assert "no owning upgrade process" in result.stderr

    def test_a_live_upgrade_process_says_nothing(self, tmp_path: Path) -> None:
        """The documented path must stay quiet, or the warning becomes noise."""
        handover = self._handover(tmp_path)

        result = _resolve_streams(
            tmp_path,
            self._example(tmp_path),
            str(handover),
            owner_line=f"export {OWNER_VAR}=$$",
        )

        assert result.returncode == 0, result.stderr
        assert str(handover) in result.stdout
        assert "stale" not in result.stderr.lower()
        assert "no owning upgrade process" not in result.stderr


def _cleanup(tmp_path: Path, baseline: str, handover: str | None = None) -> int:
    """Run ``cleanup_old_default_config`` against ``baseline``."""
    env_line = f'export {HANDOVER_VAR}="{handover}"' if handover is not None else ""
    script = textwrap.dedent(f"""
        set -uo pipefail
        {env_line}
        source "{CONFIG_PRESERVE_SH}"
        cleanup_old_default_config "{baseline}"
        """)
    return subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, cwd=tmp_path, check=False
    ).returncode


class TestTheBaselineCopyIsCleanedUpByWhoeverMadeIt:
    """The fallback path copies the example to a temp file and returns its path.

    Nothing could safely delete it: the caller cannot tell a temp copy from a
    handover it does not own, so Step 10's positional ``rm`` deleted BOTH —
    reaching into Layer 1's state on the documented path — while every early
    exit between Step 5 and Step 10 deleted neither.
    """

    def test_it_removes_the_temp_copy_the_resolver_made(self, tmp_path: Path) -> None:
        example = tmp_path / "hooks-daemon.yaml.example"
        example.write_text(yaml.dump({"daemon": {"log_level": "INFO"}}))

        resolved = _resolve(tmp_path, example, handover=None)[1]
        assert Path(resolved).is_file(), "nothing to clean up — the resolver returned no copy"

        assert _cleanup(tmp_path, resolved) == 0
        assert not Path(resolved).exists(), f"the temp baseline leaked: {resolved}"

    def test_it_never_removes_the_handed_over_baseline(self, tmp_path: Path) -> None:
        """Layer 1 owns that file and cleans it up in its own EXIT trap."""
        handover = tmp_path / "old-default.yaml"
        handover.write_text(yaml.dump({"daemon": {"log_level": "INFO"}}))

        assert _cleanup(tmp_path, str(handover), handover=str(handover)) == 0
        assert handover.exists(), "Layer 2 deleted a file belonging to Layer 1"

    def test_it_leaves_an_unrelated_path_alone(self, tmp_path: Path) -> None:
        """A caller passing something else must not lose a real file."""
        ordinary = tmp_path / "hooks-daemon.yaml.example"
        ordinary.write_text(yaml.dump({"daemon": {"log_level": "INFO"}}))

        assert _cleanup(tmp_path, str(ordinary)) == 0
        assert ordinary.exists(), "cleanup deleted a path it did not create"

    def test_it_tolerates_an_empty_baseline(self, tmp_path: Path) -> None:
        """A fresh install resolves to nothing at all; cleanup still runs."""
        assert _cleanup(tmp_path, "") == 0


class TestBothLayersCleanUpOnEveryExit:
    """Positional cleanup only runs when the script reaches that line."""

    def test_layer1_removes_its_preserved_baseline_in_an_exit_trap(self) -> None:
        content = LAYER1.read_text()

        trap_line = re.search(r"^trap '(?P<body>.*)' EXIT$", content, re.MULTILINE)

        assert trap_line is not None, "Layer 1 no longer has an EXIT trap"
        assert "_PRESERVED_OLD_DEFAULT_TMP" in trap_line.group("body"), (
            "Layer 1 preserves a baseline in a temp file but does not remove it "
            "on exit — an aborted upgrade leaves it behind."
        )

    def test_layer2_cleans_the_baseline_from_inside_its_trap(self) -> None:
        """Not from Step 10, which an early exit never reaches."""
        content = LAYER2.read_text()

        trap_body = content.split("cleanup_on_failure() {", 1)[-1].split(
            "trap cleanup_on_failure EXIT", 1
        )[0]

        assert "cleanup_old_default_config" in trap_body, (
            "Layer 2's baseline cleanup must run from the EXIT trap; anywhere "
            "else and an early exit leaks the temp copy."
        )


class TestTheConsequenceThisPrevents:
    """Why the baseline matters, pinned end-to-end through differ + merger."""

    def test_a_changed_default_reaches_a_user_who_accepted_the_old_one(self) -> None:
        """With the TRUE old default as baseline, the new default propagates."""
        from claude_code_hooks_daemon.install.config_differ import ConfigDiffer
        from claude_code_hooks_daemon.install.config_merger import ConfigMerger

        old_default = {"version": "1.0", "daemon": {"log_level": "INFO"}}
        new_default = {"version": "2.0", "daemon": {"log_level": "WARNING"}}
        user = {"version": "1.0", "daemon": {"log_level": "INFO"}}

        diff = ConfigDiffer().diff(user, old_default)
        merged = ConfigMerger().merge(new_default, diff).merged_config

        assert (
            diff.custom_daemon_settings == {}
        ), "a value equal to the old default is not a customisation"
        assert merged["daemon"]["log_level"] == "WARNING"

    def test_a_deliberate_choice_still_survives(self) -> None:
        """The fix must not start discarding real customisations.

        A user who genuinely set DEBUG differs from the old default too, so
        they are correctly classified as customised and preserved. This is the
        regression guard on the other side of the change.
        """
        from claude_code_hooks_daemon.install.config_differ import ConfigDiffer
        from claude_code_hooks_daemon.install.config_merger import ConfigMerger

        old_default = {"version": "1.0", "daemon": {"log_level": "INFO"}}
        new_default = {"version": "2.0", "daemon": {"log_level": "WARNING"}}
        user = {"version": "1.0", "daemon": {"log_level": "DEBUG"}}

        diff = ConfigDiffer().diff(user, old_default)
        merged = ConfigMerger().merge(new_default, diff).merged_config

        assert diff.custom_daemon_settings == {"log_level": "DEBUG"}
        assert merged["daemon"]["log_level"] == "DEBUG"
