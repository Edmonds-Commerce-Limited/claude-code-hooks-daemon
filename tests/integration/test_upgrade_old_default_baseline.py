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

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1 = REPO_ROOT / "scripts" / "upgrade.sh"
CONFIG_PRESERVE_SH = REPO_ROOT / "scripts" / "install" / "config_preserve.sh"
BASH = shutil.which("bash") or "/bin/bash"

#: The env var Layer 1 uses to hand the pre-checkout baseline to Layer 2.
HANDOVER_VAR = "HOOKS_DAEMON_OLD_DEFAULT_CONFIG"


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


def _resolve(tmp_path: Path, example: Path | None, handover: str | None) -> tuple[int, str]:
    """Call ``resolve_old_default_config`` and capture ONLY its stdout value."""
    env_line = f'export {HANDOVER_VAR}="{handover}"' if handover is not None else ""
    example_arg = str(example) if example is not None else ""
    script = textwrap.dedent(f"""
        set -uo pipefail
        {env_line}
        source "{CONFIG_PRESERVE_SH}"
        resolve_old_default_config "{example_arg}"
        """)
    result = subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, cwd=tmp_path, check=False
    )
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
