"""A step added in release vN+1 must actually run during the upgrade TO vN+1.

Field defect from the v3.62.0 upgrade. ``RELEASES/v3.62.0.md`` says the
upgrade deploys ``CLAUDE/core/``; after a clean, successful upgrade the
directory did not exist. The transcript's step list matched v3.61.0's script
exactly — Step 14 straight to Step 14b, with no 14a — so the new step was
never skipped by a gate, it was never in the running program.

The cause is structural, not a typo. ``upgrade_version.sh`` (Layer 2) checks
out the target version at its OWN Step 6, half way through its own execution.
Bash has already read the script it is running, so every step after the
checkout still comes from the version being REPLACED. Any step the new
release adds is invisible on the one upgrade that installs it, and appears
only if the operator happens to run the script a second time.

Two things close it, and this module pins both:

1. **Layer 1 already does it right.** ``upgrade.sh`` checks out the target and
   THEN invokes Layer 2 as a fresh process, so Layer 2 is the new version's
   script from line one. The documentation, however, told users to invoke
   Layer 2 directly — the exact path that reproduces the defect. The docs must
   lead with Layer 1.

2. **Direct Layer 2 invocation must not fail silently.** Layer 2 is a public
   entry point that people and older scripts still call, so when it detects
   that its own file changed underneath it, it must say so and run a second,
   idempotent pass from the new code rather than exiting as if complete.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
LAYER1 = SCRIPTS / "upgrade.sh"
LAYER2 = SCRIPTS / "upgrade_version.sh"

# The documents that hand a reader a copy-pasteable upgrade command. Version
# specific upgrade guides under CLAUDE/UPGRADES/v3/ are deliberately NOT here:
# they are a historical record of what a past upgrade looked like, and
# rewriting them would falsify it.
_DOCS_THAT_TEACH_THE_UPGRADE = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "BUG_REPORTING.md",
    REPO_ROOT / "CLAUDE" / "LLM-UPDATE.md",
    REPO_ROOT / "CLAUDE" / "UPGRADES" / "README.md",
    REPO_ROOT / "CLAUDE" / "UPGRADES" / "upgrade-template" / "README.md",
)

# `bash .../upgrade_version.sh` used as a command the reader is told to run.
_BARE_LAYER2_INVOCATION = re.compile(r"^\s*bash\s+\S*upgrade_version\.sh\b", re.MULTILINE)


class TestLayerOneChecksOutBeforeDelegating:
    """The architecture that makes an added step run is Layer 1's ordering."""

    def test_layer1_checks_out_the_target_before_invoking_layer2(self) -> None:
        """Checkout must precede the Layer 2 call, or Layer 2 is the old code."""
        content = LAYER1.read_text()

        checkout = re.search(r'git -C "\$DAEMON_DIR" checkout "\$TARGET_VERSION"', content)
        delegate = re.search(r'bash "\$LAYER2_SCRIPT"', content)

        assert checkout is not None, "Layer 1 no longer checks out the target version"
        assert delegate is not None, "Layer 1 no longer delegates to Layer 2"
        assert checkout.start() < delegate.start(), (
            "Layer 1 must check out the target BEFORE invoking Layer 2. Invoking "
            "first means Layer 2 runs the OLD version's step list, and any step "
            "the new release adds never executes."
        )


class TestTheDocumentedUpgradeCommandUsesLayerOne:
    """Docs must not hand the reader the entry point with the known hazard."""

    def test_no_document_tells_the_reader_to_run_layer2_directly(self) -> None:
        """``bash .../upgrade_version.sh`` must not be the taught command.

        Layer 2 self-checks-out mid-run, so a reader following that command
        gets the previous release's step list. Every one of these documents
        described it as the manual upgrade path.
        """
        offenders: list[str] = []
        for doc in _DOCS_THAT_TEACH_THE_UPGRADE:
            if not doc.exists():
                continue
            for match in _BARE_LAYER2_INVOCATION.finditer(doc.read_text()):
                line_number = doc.read_text()[: match.start()].count("\n") + 1
                offenders.append(f"{doc.relative_to(REPO_ROOT)}:{line_number}")

        assert not offenders, (
            "These documents tell the reader to invoke Layer 2 directly, which "
            "runs the pre-upgrade step list. Use Layer 1 instead:\n  "
            'bash .claude/hooks-daemon/scripts/upgrade.sh --project-root "$PWD" '
            '"$TARGET"\nOffending lines:\n  ' + "\n  ".join(offenders)
        )

    def test_layer1_is_actually_named_in_the_upgrade_docs(self) -> None:
        """Removing the bad command is only half the fix — name the good one."""
        missing = [
            doc.relative_to(REPO_ROOT)
            for doc in _DOCS_THAT_TEACH_THE_UPGRADE
            if doc.exists() and "upgrade.sh" not in doc.read_text()
        ]

        assert not missing, f"These upgrade documents never name Layer 1: {missing}"


class TestLayerTwoDetectsThatItsOwnFileChanged:
    """Direct Layer 2 invocation must recover instead of silently under-running.

    Layer 2 stays a supported entry point: older skill shims and existing
    runbooks still call it, and it cannot assume Layer 1 ran. So it has to
    notice that Step 6's checkout replaced its own source and complete the
    work from the new code.
    """

    def test_layer2_fingerprints_its_own_source_before_checkout(self) -> None:
        """It cannot detect the swap without a before-value to compare."""
        content = LAYER2.read_text()

        assert "LAYER2_SOURCE_FINGERPRINT_BEFORE" in content, (
            "Layer 2 must record a fingerprint of its own source before the "
            "checkout, so it can tell whether the target release changed it."
        )

    def test_layer2_compares_the_fingerprint_after_checkout(self) -> None:
        """The comparison must come after the checkout to mean anything."""
        content = LAYER2.read_text()

        checkout = re.search(r'git -C "\$DAEMON_DIR" checkout "\$TARGET_VERSION"', content)
        comparison = re.search(r"LAYER2_SOURCE_CHANGED=true", content)

        assert checkout is not None, "Layer 2 no longer checks out the target version"
        assert comparison is not None, "Layer 2 never records that its source changed"
        assert checkout.start() < comparison.start(), (
            "The fingerprint comparison must happen AFTER the checkout — before "
            "it, the file is by definition unchanged."
        )

    def test_layer2_runs_a_second_pass_from_the_new_code(self) -> None:
        """A detected swap must trigger a re-exec, not just a warning.

        Telling the operator to run it again leaves the install incomplete for
        anyone who does not read the scrollback — which is what happened in the
        field. The second pass is the same idempotent deployment a manual
        re-run performs, and the report confirmed that path works.
        """
        content = LAYER2.read_text()

        assert re.search(r"^\s*exec bash \"\$LAYER2_TARGET_SCRIPT\"", content, re.MULTILINE), (
            "Layer 2 must re-exec the target version's own script when it "
            "detects its source changed underneath it."
        )

    def test_the_second_pass_does_not_duplicate_the_positional_arguments(self) -> None:
        """Forward the trailing FLAGS, not the whole original argument list.

        The three positionals are already passed explicitly. A plain ``"$@"``
        appends them a second time, so the child receives each one twice — it
        still reads ``$1``-``$3`` correctly, but the flag detection in this
        script matches against ``$*``, and feeding it duplicated paths is a
        trap waiting for the first path that contains a flag-like substring.
        """
        content = LAYER2.read_text()

        reexec_line = next(
            line for line in content.splitlines() if 'exec bash "$LAYER2_TARGET_SCRIPT"' in line
        )

        assert '"${@:4}"' in reexec_line, (
            'Forward only the trailing flags with "${@:4}"; got:\n' + reexec_line
        )
        assert not reexec_line.rstrip().endswith('"$@"'), (
            'plain "$@" re-appends the three positionals that are already ' "passed explicitly"
        )

    def test_the_second_pass_cannot_loop(self) -> None:
        """The re-exec must be guarded by a sentinel the child inherits."""
        content = LAYER2.read_text()

        assert "HOOKS_DAEMON_UPGRADE_SECOND_PASS" in content, (
            "The re-exec needs an exported sentinel, or a script that keeps "
            "changing (or a mis-detection) would re-exec forever."
        )
        assert (
            "export HOOKS_DAEMON_UPGRADE_SECOND_PASS" in content
        ), "The sentinel must be EXPORTED, or the child process never sees it."

    def test_the_second_pass_happens_after_the_upgrade_steps_complete(self) -> None:
        """Re-exec at the END, so no pre-checkout state has to be handed over.

        Re-exec'ing at the checkout itself would abandon Steps 7-17 mid-flight
        and require rebuilding the snapshot id, the config backup and the
        old-default baseline in the child. Running the full first pass and then
        repeating it idempotently keeps the rollback contract intact.
        """
        content = LAYER2.read_text()

        last_step = content.rfind('log_step "17"')
        reexec = content.find('exec bash "$LAYER2_TARGET_SCRIPT"')

        assert last_step != -1, "Step 17 marker not found"
        assert reexec != -1, "no re-exec found"
        assert reexec > last_step, (
            "The second pass must run after the final upgrade step, not in "
            "place of the remaining steps."
        )
