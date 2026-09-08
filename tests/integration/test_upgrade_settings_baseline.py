"""The settings merge needs a baseline, and only Layer 1 can still see it.

Plan 00176 Q2b. The merge has to tell a default the client merely ACCEPTED from
one they deliberately chose, and those two are IDENTICAL at the data level —
the only thing that separates them is the file the previous version shipped.

`settings.json` differs from the config baseline in one way that makes it
simpler rather than harder: the daemon's own `.claude/settings.json` IS its
shipped default, so there is no `.example` to resolve. Copying that one file
before Layer 1's checkout is the entire mechanism.

The deadline is the same as `FROM_VERSION`'s and the config example's: Layer 1
checks the target out and only THEN invokes Layer 2, so a capture after the
checkout captures the new file and the baseline silently becomes useless. There
is deliberately no fallback that infers one — without a baseline the merge
preserves every client value and upgrades none, which delivers no new
recommendation but destroys nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1 = REPO_ROOT / "scripts" / "upgrade.sh"
LAYER2 = REPO_ROOT / "scripts" / "upgrade_version.sh"

#: The env var Layer 1 uses to hand the pre-checkout settings baseline to Layer 2.
HANDOVER_VAR = "HOOKS_DAEMON_OLD_DEFAULT_SETTINGS"


class TestLayerOneCapturesItBeforeTheCheckout:
    def test_the_capture_precedes_the_checkout(self) -> None:
        content = LAYER1.read_text(encoding="utf-8")

        capture = re.search(r"OLD_DEFAULT_SETTINGS_SOURCE=", content)
        checkout = re.search(
            r'git -C "\$DAEMON_DIR" (?:checkout|reset --hard --quiet) "\$TARGET_VERSION"',
            content,
        )

        assert capture is not None, (
            "Layer 1 never copies the daemon's settings.json, so the old default "
            "is gone by the time the merge looks for it."
        )
        assert checkout is not None, "Layer 1 no longer checks out the target version"
        assert capture.start() < checkout.start(), (
            "The settings capture must happen BEFORE the checkout — after it, the "
            "file on disk is the NEW default."
        )

    def test_it_is_exported_for_layer_two(self) -> None:
        """Capturing is useless unless the child process can see the path."""
        content = LAYER1.read_text(encoding="utf-8")
        assert f"export {HANDOVER_VAR}" in content

    def test_the_temp_copy_is_cleaned_up_on_exit(self) -> None:
        """An upgrade that aborts after the capture must not litter the temp dir."""
        content = LAYER1.read_text(encoding="utf-8")
        trap = re.search(r"^trap '(.*)' EXIT", content, re.MULTILINE)
        assert trap is not None
        assert "_PRESERVED_OLD_DEFAULT_SETTINGS_TMP" in trap.group(1)

    def test_the_tracked_temp_var_is_not_the_exported_one(self) -> None:
        """Deleting the exported path would remove a file the CALLER owns."""
        content = LAYER1.read_text(encoding="utf-8")
        trap = re.search(r"^trap '(.*)' EXIT", content, re.MULTILINE)
        assert trap is not None
        assert HANDOVER_VAR not in trap.group(1)


class TestLayerTwoActuallyUsesIt:
    def test_both_deploy_sites_pass_the_baseline_through(self) -> None:
        content = LAYER2.read_text(encoding="utf-8")
        assert content.count(f"${{{HANDOVER_VAR}:-}}") >= 2, (
            "both the idempotent fast path and Step 9 must hand the baseline to "
            "the merge — a site that omits it silently upgrades nothing"
        )

    def test_it_degrades_rather_than_failing_when_absent(self) -> None:
        """`:-` matters: an unset baseline is the normal case, not an error."""
        content = LAYER2.read_text(encoding="utf-8")
        assert f'${HANDOVER_VAR}"' not in content, (
            "an unbraced, undefaulted expansion aborts the run under `set -u` "
            "when no handover was captured"
        )
