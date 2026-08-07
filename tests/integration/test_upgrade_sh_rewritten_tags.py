r"""Layer 1 tolerates an upstream history rewrite (rewritten tags).

Context: clients install the daemon with ``git clone --depth 1`` (``install.sh``)
and upgrade with ``git fetch --tags`` + ``git checkout <tag>``
(``scripts/upgrade.sh``). They never merge a branch, so a rewritten upstream
history is survivable — but only if the tag fetch is forced.

Git refuses to move a local tag that already exists and points at a different
object ("would clobber existing tag") and exits NON-ZERO. ``scripts/upgrade.sh``
runs under ``set -euo pipefail``, so an unforced fetch turns an upstream history
rewrite into a hard, permanent, self-unrecoverable upgrade failure for every
client that has upgraded even once (such a client holds every tag at its
pre-rewrite hash).

``--force`` is therefore load-bearing, not defensive. These tests pin it:

1. ``test_unforced_fetch_fails_against_rewritten_tag`` documents the underlying
   git behaviour that makes the flag necessary. If this ever starts passing,
   git changed and the rationale below should be revisited.
2. ``test_upgrade_sh_tag_fetch_survives_rewritten_tag`` extracts the REAL fetch
   invocation from ``scripts/upgrade.sh`` and runs it against a rewritten-tag
   fixture. Dropping ``--force`` from the script fails this test.

Behavioural test — builds real git repositories and runs real git commands.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
GIT = shutil.which("git") or "/usr/bin/git"
_TIMEOUT_SECONDS = 60

# Matches the tag-fetch line in scripts/upgrade.sh, capturing the flags that
# follow "fetch". Anchored on `git -C "$DAEMON_DIR" fetch --tags` so an
# unrelated `git fetch` elsewhere in the script cannot satisfy it.
_TAG_FETCH_LINE = re.compile(
    r'^git\s+-C\s+"\$DAEMON_DIR"\s+fetch\s+(?P<flags>--tags[^\n]*)$',
    re.MULTILINE,
)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run git, returning the completed process (never raises on non-zero)."""
    return subprocess.run(
        [GIT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _require_ok(result: subprocess.CompletedProcess[str], what: str) -> None:
    """FAIL FAST on fixture-construction errors so they cannot masquerade as
    the behaviour under test."""
    if result.returncode != 0:
        raise AssertionError(f"fixture setup failed ({what}): {result.stderr.strip()}")


@pytest.fixture
def rewritten_tag_remote(tmp_path: Path) -> tuple[Path, str]:
    """Build a client clone whose ``v1.0.0`` tag is stale w.r.t. its remote.

    Reproduces the exact post-history-rewrite state: same tag NAME upstream,
    different commit object. Returns ``(client_dir, expected_remote_sha)``.

    The remote tag is re-pointed with ``update-ref`` directly on the bare repo
    rather than a force-push, which both avoids needing a second working copy
    and keeps this fixture free of destructive push semantics.
    """
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    client = tmp_path / "client"

    _require_ok(_git("init", "-q", "--bare", str(remote), cwd=tmp_path), "init bare")
    _require_ok(_git("clone", "-q", str(remote), str(work), cwd=tmp_path), "clone work")
    _require_ok(_git("config", "user.email", "test@example.com", cwd=work), "config email")
    _require_ok(_git("config", "user.name", "Test", cwd=work), "config name")

    (work / "f.txt").write_text("one\n", encoding="utf-8")
    _require_ok(_git("add", "f.txt", cwd=work), "add")
    _require_ok(_git("commit", "-qm", "one", cwd=work), "commit one")
    _require_ok(_git("tag", "v1.0.0", cwd=work), "tag")
    _require_ok(_git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=work), "push main")
    _require_ok(_git("push", "-q", "origin", "v1.0.0", cwd=work), "push tag")

    # Client installs the way install.sh does: shallow, then pulls tags once.
    _require_ok(
        _git("clone", "-q", "--depth", "1", str(remote), str(client), cwd=tmp_path),
        "shallow clone",
    )
    _require_ok(_git("fetch", "--tags", "--quiet", cwd=client), "client initial tag fetch")

    # Upstream "history rewrite": v1.0.0 keeps its name, gains a new commit.
    (work / "f.txt").write_text("two\n", encoding="utf-8")
    _require_ok(_git("commit", "-qam", "two", cwd=work), "commit two")
    _require_ok(_git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=work), "push main 2")
    rewritten = _git("rev-parse", "HEAD", cwd=work).stdout.strip()
    _require_ok(
        _git("update-ref", "refs/tags/v1.0.0", rewritten, cwd=remote),
        "re-point remote tag",
    )

    stale = _git("rev-parse", "v1.0.0", cwd=client).stdout.strip()
    assert stale != rewritten, "fixture did not produce a stale client tag"
    return client, rewritten


def test_unforced_fetch_fails_against_rewritten_tag(
    rewritten_tag_remote: tuple[Path, str],
) -> None:
    """Without --force, git refuses to move the tag and exits non-zero.

    This is the failure that ``set -euo pipefail`` converts into an aborted
    upgrade. It exists to document WHY --force is required in upgrade.sh.
    """
    client, _ = rewritten_tag_remote

    result = _git("fetch", "--tags", "--quiet", cwd=client)

    assert result.returncode != 0, (
        "Expected git to refuse clobbering an existing tag. If git no longer "
        "does this, the --force rationale in scripts/upgrade.sh needs revisiting."
    )


def test_upgrade_sh_tag_fetch_survives_rewritten_tag(
    rewritten_tag_remote: tuple[Path, str],
) -> None:
    """The REAL fetch invocation from upgrade.sh must survive a rewritten tag.

    Extracts the flags from scripts/upgrade.sh rather than hardcoding them, so
    removing --force from the script fails this test.
    """
    client, rewritten = rewritten_tag_remote

    script = LAYER1_UPGRADE_SH.read_text(encoding="utf-8")
    match = _TAG_FETCH_LINE.search(script)
    assert match is not None, (
        "Could not locate the tag-fetch line in scripts/upgrade.sh. If it moved "
        "or was reworded, update _TAG_FETCH_LINE — do not delete this test."
    )
    flags = match.group("flags").split()

    result = _git("fetch", *flags, cwd=client)

    assert result.returncode == 0, (
        f"upgrade.sh's tag fetch ({' '.join(flags)}) failed against a rewritten "
        f"tag. It almost certainly lost --force. stderr: {result.stderr.strip()}"
    )
    updated = _git("rev-parse", "v1.0.0", cwd=client).stdout.strip()
    assert updated == rewritten, "tag fetched but did not move to the rewritten commit"

    # upgrade.sh checks out the tag immediately after fetching it.
    checkout = _git("checkout", "--quiet", "v1.0.0", cwd=client)
    assert checkout.returncode == 0, f"checkout failed: {checkout.stderr.strip()}"
    assert (client / "f.txt").read_text(encoding="utf-8") == "two\n"
