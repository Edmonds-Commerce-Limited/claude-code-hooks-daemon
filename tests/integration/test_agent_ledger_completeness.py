"""Every revision a shipped agent template ever had must be ledgered.

Plan 00378 Task 2.1. ``classify_agent`` calls a deployed file CUSTOMISED — and
so refuses to touch it, for ever — whenever its digest is neither the current
bundled content nor a recorded historic revision. That makes ledger
completeness the difference between "your edits are protected" and "your
pristine install is frozen and told it was hand-edited".

Four revisions had shipped unrecorded when this check was written, across all
three agents, because the test that was supposed to catch it compared
``content_md5(file)`` with ``content_md5(file)``. Counting entries does not
help either: the previous ``len(historic_md5s) >= 5`` stayed true while
revisions went missing.

This check FAILS rather than skips when git history is unavailable. A
history-walking check that silently no-ops on a shallow clone is the same
defect one layer out — green, cited as coverage, verifying nothing. CI checks
out with ``fetch-depth: 0``, so the capability is there to rely on.
"""

import hashlib
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.agent_assets import (
    SHIPPED_AGENTS,
    AgentAssetSpec,
    AgentAssetState,
    classify_agent,
    deployed_agent_path,
    spec_source_path,
)

#: Repository root, derived from a tracked source file rather than the CWD so
#: the check cannot silently target some other checkout.
_REPO_ROOT = spec_source_path(SHIPPED_AGENTS[0]).resolve().parents[5]


def _git(*args: str) -> bytes:
    """Run git with a fixed argv (no shell) and return raw stdout."""
    completed = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), *args],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed in {_REPO_ROOT}: "
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return completed.stdout


def _relative_template_path(spec: AgentAssetSpec) -> str:
    return str(spec_source_path(spec).resolve().relative_to(_REPO_ROOT))


def _revision_digests(rel_path: str) -> dict[str, str]:
    """Every digest ``rel_path`` has ever had, keyed by the commit shipping it."""
    log = _git("log", "--format=%H", "--", rel_path).decode().split()
    if not log:
        raise AssertionError(
            f"No git history for {rel_path}. This check cannot verify ledger "
            "completeness without it, and passing regardless would recreate "
            "the defect it exists to prevent."
        )
    return {
        sha: hashlib.md5(_git("show", f"{sha}:{rel_path}"), usedforsecurity=False).hexdigest()
        for sha in log
    }


class TestGitHistoryIsAvailable:
    def test_the_checkout_is_not_shallow(self) -> None:
        """A shallow clone hides older revisions, so absence proves nothing."""
        shallow = _git("rev-parse", "--is-shallow-repository").decode().strip()
        assert shallow == "false", (
            "Shallow checkout: ledger completeness cannot be verified. "
            "Fetch full history (actions/checkout fetch-depth: 0) rather than "
            "skipping this check."
        )


class TestAShippedRevisionIsUpgradeable:
    """Completeness is a means; THIS is the property that matters.

    A ledgered revision must classify ``OUTDATED`` — refreshable — rather than
    ``CUSTOMISED``, which is permanent. Asserting the digest is merely present
    would not catch a classifier that stopped consulting the ledger.
    """

    @pytest.mark.parametrize("spec", SHIPPED_AGENTS, ids=lambda s: s.name)
    def test_every_past_revision_classifies_as_refreshable(
        self, spec: AgentAssetSpec, tmp_path: Path
    ) -> None:
        rel_path = _relative_template_path(spec)
        for sha, digest in _revision_digests(rel_path).items():
            if digest == spec.md5:
                continue  # the current content is CURRENT, not OUTDATED
            project_root = tmp_path / sha
            target = deployed_agent_path(spec, project_root)
            target.parent.mkdir(parents=True)
            target.write_bytes(_git("show", f"{sha}:{rel_path}"))
            assert classify_agent(spec, project_root) is AgentAssetState.OUTDATED, (
                f"{spec.name}: a deployment of revision {sha[:9]} is frozen — "
                "it would be refused by every future upgrade and told it was "
                "hand-edited."
            )


class TestEveryShippedRevisionIsLedgered:
    @pytest.mark.parametrize("spec", SHIPPED_AGENTS, ids=lambda s: s.name)
    def test_no_revision_is_unledgered(self, spec: AgentAssetSpec) -> None:
        known = {spec.md5, *spec.historic_md5s}
        rel_path = _relative_template_path(spec)
        unledgered = {
            sha: digest
            for sha, digest in _revision_digests(rel_path).items()
            if digest not in known
        }
        assert not unledgered, (
            f"{spec.name}: {len(unledgered)} shipped revision(s) are absent from "
            f"the ledger, so any deployment made from one classifies CUSTOMISED "
            f"and can never be upgraded again. Add each digest to that agent's "
            f"historic_versions: "
            + ", ".join(f"{sha[:9]}={digest}" for sha, digest in unledgered.items())
        )
