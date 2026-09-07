"""An upgrade must leave a project's generated guidance matching what shipped.

Plan 00336 Phase 3. A project carries two pieces of generated agent guidance:

* ``.claude/HOOKS-DAEMON.md`` — written by ``generate-docs`` from the live
  config plus handler metadata.
* the ``<hooksdaemon>`` block inside the project ``CLAUDE.md`` — written by the
  ``ClaudeMdInjector``, which ``DaemonController.initialise()`` runs, so every
  daemon start refreshes it.

Only the second one survives an upgrade today. ``install_version.sh`` runs
``generate-docs`` (twice — Step 13, and again after a handler profile is
applied), but ``upgrade_version.sh`` never runs it on EITHER of its two paths.
So ``HOOKS-DAEMON.md`` keeps describing the version the project was INSTALLED
at, however many upgrades later it is read.

That is not cosmetic. v3.62.0 shipped a deny handler enabled by default: an
agent reading the stale document is denied by a rule its own guidance does not
document, and the document gives it no way to find out why.

The framing this file corrects: Phase 3 was filed against both artifacts. The
CLAUDE.md block is in fact already handled, because both upgrade paths call
``restart_daemon_verified`` and daemon startup runs the injector. Pinning that
here keeps the mechanism from being quietly removed and keeps the next agent
from "fixing" it a second time.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_VERSION_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"
INSTALL_VERSION_SH = REPO_ROOT / "scripts" / "install_version.sh"

#: The CLI subcommand that writes ``.claude/HOOKS-DAEMON.md``.
GENERATE_DOCS = "generate-docs"

#: Start of the idempotent fast path — the branch every Layer 1 upgrade takes,
#: because Layer 1 checks the target out before invoking this script.
FAST_PATH_GUARD = 'if [ "$ROLLBACK_REF" = "$TARGET_VERSION" ]; then'


def _split_paths(content: str) -> tuple[str, str]:
    """Split the script into (fast path body, slow path body).

    The fast path is the ``ROLLBACK_REF == TARGET_VERSION`` branch, which ends
    in its own ``exit 0``. Everything after that branch closes is the slow path.
    """
    start = content.index(FAST_PATH_GUARD)
    end = content.index("\n    exit 0\nfi\n", start)
    return content[start:end], content[end:]


class TestBothUpgradePathsRegenerateHandlerDocs:
    """``HOOKS-DAEMON.md`` must be rewritten by the upgrade that changes it."""

    def test_the_fast_path_regenerates_handler_docs(self) -> None:
        """This is the branch a normal client upgrade actually takes.

        Layer 1 (``upgrade.sh``) checks out the target tag and only then calls
        this script, so ``ROLLBACK_REF`` always equals ``$TARGET_VERSION`` and
        the fast path is the effective single deployment path. Missing the
        regeneration here misses it for essentially every client.
        """
        fast_path, _ = _split_paths(UPGRADE_VERSION_SH.read_text())

        assert GENERATE_DOCS in fast_path, (
            "The idempotent fast path deploys hooks, skills, slash commands, "
            "core docs and the ccy supervisor, then restarts — but never "
            "regenerates .claude/HOOKS-DAEMON.md, so it still describes the "
            "version the project was installed at."
        )

    def test_the_slow_path_regenerates_handler_docs(self) -> None:
        """Direct Layer 2 invocation must not leave the doc behind either."""
        _, slow_path = _split_paths(UPGRADE_VERSION_SH.read_text())

        assert GENERATE_DOCS in slow_path, (
            "The full upgrade path checks out, rebuilds the venv, merges config "
            "and restarts — but never regenerates .claude/HOOKS-DAEMON.md."
        )

    def test_generation_runs_the_upgraded_interpreter(self) -> None:
        """The doc is generated from the handler registry that is IMPORTED.

        Running it under anything but the freshly rebuilt ``$VENV_PYTHON``
        would document the handler set of the version being replaced — the
        exact staleness this phase exists to remove.
        """
        content = UPGRADE_VERSION_SH.read_text()

        for line in content.splitlines():
            if GENERATE_DOCS in line and "claude_code_hooks_daemon.daemon.cli" in line:
                assert "$VENV_PYTHON" in line, (
                    f"generate-docs must run under the rebuilt venv, not a bare "
                    f"interpreter: {line.strip()}"
                )

    def test_generation_is_reported_but_never_fatal(self) -> None:
        """A doc-generation failure must not fail an otherwise good upgrade.

        The daemon is already restarted and verified by the time this runs; the
        generated document is guidance, not machinery. ``install_version.sh``
        Step 13 sets the precedent — ``print_warning`` on failure, not exit.
        """
        content = UPGRADE_VERSION_SH.read_text()
        lines = content.splitlines()

        invocations = [
            index
            for index, line in enumerate(lines)
            if GENERATE_DOCS in line and "claude_code_hooks_daemon.daemon.cli" in line
        ]
        assert invocations, "no generate-docs invocation found to check"

        for index in invocations:
            following = "\n".join(lines[index : index + 6])
            assert "print_warning" in following, (
                "generate-docs must degrade to a warning; a stale guidance doc "
                f"is not worth aborting a completed upgrade:\n{following}"
            )
            assert (
                "fail_fast" not in following
            ), f"generate-docs must not abort the upgrade:\n{following}"


class TestTheClaudeMdBlockIsAlreadyCovered:
    """The other artifact is refreshed by the restart — keep it that way."""

    def test_both_paths_restart_the_daemon(self) -> None:
        """The restart IS the CLAUDE.md regeneration mechanism.

        ``DaemonController.initialise()`` runs the ``ClaudeMdInjector`` as a
        side effect, so a verified restart rewrites the ``<hooksdaemon>`` block
        against the newly installed handler set. Remove the restart and that
        block silently goes stale with no other signal.
        """
        fast_path, slow_path = _split_paths(UPGRADE_VERSION_SH.read_text())

        assert "restart_daemon_verified" in fast_path
        assert "restart_daemon_verified" in slow_path

    def test_docs_are_generated_after_the_restart(self) -> None:
        """Order matters: document the handler set the daemon actually loaded.

        If generation ran before the restart it could describe a config the
        daemon then fails to load, leaving the doc confidently wrong rather
        than merely stale.
        """
        for body in _split_paths(UPGRADE_VERSION_SH.read_text()):
            if GENERATE_DOCS not in body:
                continue
            assert body.index("restart_daemon_verified") < body.index(GENERATE_DOCS), (
                "generate-docs must run AFTER the daemon restart so it reflects "
                "the handler set that actually loaded."
            )


class TestInstallStillDoesWhatUpgradeWasMissing:
    """Guard the reference implementation this phase copies."""

    def test_install_generates_handler_docs(self) -> None:
        """A fresh install has always done this; that is why the gap was invisible."""
        assert GENERATE_DOCS in INSTALL_VERSION_SH.read_text(), (
            "install_version.sh no longer generates HOOKS-DAEMON.md — then no "
            "path does, and every project's guidance is stale from day one."
        )
