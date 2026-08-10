r"""Layer 1 lands on the target tag even when the daemon dir is dirty.

Context: ``scripts/upgrade.sh`` moves a client's vendored daemon checkout onto a
release tag. It used a plain ``git checkout <tag>``, which **aborts** when the
working tree carries local modifications, or when an untracked file would be
overwritten by the checkout.

For a client install that abort is a dead end. ``.claude/hooks-daemon/`` is an
upstream dependency the project's own CLAUDE.md declares off-limits ("changes
will be overwritten on the next upgrade"), so drift there is never precious --
but a plain checkout treats it as precious anyway and refuses, leaving the
client stuck on an old daemon with no self-service recovery. The pre-existing
``uv.lock`` special-case at the top of Step 6 is a symptom: it hand-deletes ONE
known untracked file because that one file was observed blocking checkout.

``git reset --hard <tag>`` has no such failure mode: it writes the tag's tree
unconditionally, over both local modifications and colliding untracked files.

The force is scoped to CLIENT installs. In self-install mode ``$DAEMON_DIR`` is
the developer's own project root (``upgrade.sh`` line ~260), where discarding
uncommitted work would be catastrophic -- that path keeps the checkout that
refuses when dirty.

These tests pin all three claims:

1. ``test_plain_checkout_aborts_on_dirty_tree`` documents the git behaviour that
   makes the change necessary. If it ever starts passing, git changed and the
   rationale here should be revisited.
2. ``test_upgrade_sh_client_checkout_survives_*`` extract the REAL client-mode
   invocation from ``scripts/upgrade.sh`` and run it against dirty fixtures.
   Reverting the script to a plain checkout fails them.
3. ``test_self_install_path_is_not_forced`` pins the scoping, so a later
   simplification cannot quietly widen the force onto a developer's own repo.

Behavioural test -- builds real git repositories and runs real git commands.
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

_TARGET_VERSION_VAR = '"$TARGET_VERSION"'
_FIXTURE_TAG = "v1.0.0"

# The client-mode invocation that moves the daemon dir onto the target tag.
# Anchored on `git -C "$DAEMON_DIR" reset --hard` so an unrelated reset
# elsewhere in the script cannot satisfy it.
_CLIENT_RESET_LINE = re.compile(
    r'^\s*git\s+-C\s+"\$DAEMON_DIR"\s+(?P<args>reset\s+--hard[^\n]*)$',
    re.MULTILINE,
)

# The whole guarded construct, matched as ONE unit so the pairing itself is
# pinned: a non-forcing checkout under SELF_INSTALL, the forced reset only in
# the else branch. Asserting the two lines exist independently would still pass
# if someone hoisted the reset out of the conditional, which is precisely the
# regression this guards against.
_GUARDED_CHECKOUT_BLOCK = re.compile(
    r'if\s+\[\s*"?\$SELF_INSTALL"?\s*=\s*"true"\s*\]\s*;\s*then\s*\n'
    r'\s*git\s+-C\s+"\$DAEMON_DIR"\s+checkout\s+(?!--force|-f\b)[^\n]*\n'
    r"\s*else\s*\n"
    r'\s*git\s+-C\s+"\$DAEMON_DIR"\s+reset\s+--hard[^\n]*\n'
    r"\s*fi",
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


def _client_reset_args() -> list[str]:
    """Extract the real client-mode git arguments from ``scripts/upgrade.sh``.

    Extracted rather than hardcoded, so reverting the script to a plain
    ``git checkout`` fails the tests that use this instead of silently
    testing a command the script no longer runs.
    """
    script = LAYER1_UPGRADE_SH.read_text(encoding="utf-8")
    match = _CLIENT_RESET_LINE.search(script)
    assert match is not None, (
        'Could not find a `git -C "$DAEMON_DIR" reset --hard ...` line in '
        "scripts/upgrade.sh. A plain `git checkout <tag>` aborts on a dirty "
        "daemon dir and strands the client -- do not delete this test."
    )
    args = match.group("args").split()
    assert _TARGET_VERSION_VAR in args, (
        f"The reset line does not target {_TARGET_VERSION_VAR}: {args}. It must "
        "land on the resolved release tag, not on a branch or on HEAD."
    )
    return [_FIXTURE_TAG if arg == _TARGET_VERSION_VAR else arg for arg in args]


@pytest.fixture
def client_at_old_tag(tmp_path: Path) -> Path:
    """A client daemon checkout sitting one tag behind its remote.

    Mirrors a real install: shallow clone, tags fetched, then upstream ships a
    newer tag that changes a tracked file and adds a new one.
    """
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    client = tmp_path / "client"

    _require_ok(_git("init", "-q", "--bare", str(remote), cwd=tmp_path), "init bare")
    _require_ok(_git("clone", "-q", str(remote), str(work), cwd=tmp_path), "clone work")
    _require_ok(_git("config", "user.email", "test@example.com", cwd=work), "config email")
    _require_ok(_git("config", "user.name", "Test", cwd=work), "config name")

    (work / "tracked.txt").write_text("v0\n", encoding="utf-8")
    _require_ok(_git("add", "tracked.txt", cwd=work), "add v0")
    _require_ok(_git("commit", "-qm", "v0", cwd=work), "commit v0")
    _require_ok(_git("tag", "v0.9.0", cwd=work), "tag v0.9.0")

    # The newer release changes a tracked file AND adds a file that a client
    # may already be carrying as an untracked stray (the uv.lock shape).
    (work / "tracked.txt").write_text("v1\n", encoding="utf-8")
    (work / "uv.lock").write_text("locked-by-upstream\n", encoding="utf-8")
    _require_ok(_git("add", "tracked.txt", "uv.lock", cwd=work), "add v1")
    _require_ok(_git("commit", "-qm", "v1", cwd=work), "commit v1")
    _require_ok(_git("tag", _FIXTURE_TAG, cwd=work), "tag target")
    _require_ok(_git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=work), "push main")
    _require_ok(_git("push", "-q", "--tags", "origin", cwd=work), "push tags")

    _require_ok(
        _git(
            "clone",
            "-q",
            "--depth",
            "1",
            "--branch",
            "v0.9.0",
            str(remote),
            str(client),
            cwd=tmp_path,
        ),
        "shallow clone at old tag",
    )
    _require_ok(_git("fetch", "--tags", "--force", "--quiet", cwd=client), "client tag fetch")
    return client


def test_plain_checkout_aborts_on_dirty_tree(client_at_old_tag: Path) -> None:
    """A plain checkout refuses when a tracked file was modified locally.

    This is the abort that strands a client. It exists to document WHY the
    client path force-resets instead.
    """
    client = client_at_old_tag
    (client / "tracked.txt").write_text("locally modified\n", encoding="utf-8")

    result = _git("checkout", "--quiet", _FIXTURE_TAG, cwd=client)

    assert result.returncode != 0, (
        "Expected git to refuse checking out over a locally-modified tracked "
        "file. If git no longer does this, the reset --hard rationale in "
        "scripts/upgrade.sh needs revisiting."
    )


def test_plain_checkout_aborts_on_blocking_untracked_file(client_at_old_tag: Path) -> None:
    """A plain checkout refuses when an untracked file collides with the tag.

    This is the failure the hand-rolled ``uv.lock`` deletion in upgrade.sh was
    papering over -- one known filename, fixed by name. Any other stray file
    with the same shape still stranded the client.
    """
    client = client_at_old_tag
    (client / "uv.lock").write_text("stale-local-lock\n", encoding="utf-8")

    result = _git("checkout", "--quiet", _FIXTURE_TAG, cwd=client)

    assert result.returncode != 0, (
        "Expected git to refuse overwriting an untracked file. If git no "
        "longer does this, the uv.lock special-case in upgrade.sh is dead code."
    )


def test_upgrade_sh_client_checkout_survives_dirty_tracked_file(
    client_at_old_tag: Path,
) -> None:
    """upgrade.sh's real client invocation lands on the tag despite local edits."""
    client = client_at_old_tag
    (client / "tracked.txt").write_text("locally modified\n", encoding="utf-8")

    result = _git(*_client_reset_args(), cwd=client)

    assert result.returncode == 0, (
        f"upgrade.sh's client checkout failed on a dirty daemon dir: " f"{result.stderr.strip()}"
    )
    assert (client / "tracked.txt").read_text(encoding="utf-8") == "v1\n", (
        "Landed on the tag but kept the local modification -- the daemon dir "
        "must match the released tag exactly."
    )


def test_upgrade_sh_client_checkout_survives_blocking_untracked_file(
    client_at_old_tag: Path,
) -> None:
    """upgrade.sh's real client invocation overwrites a colliding stray file.

    This is what makes the ``uv.lock`` special-case redundant rather than
    load-bearing: the fix generalises to every stray file, not one filename.
    """
    client = client_at_old_tag
    (client / "uv.lock").write_text("stale-local-lock\n", encoding="utf-8")

    result = _git(*_client_reset_args(), cwd=client)

    assert result.returncode == 0, (
        f"upgrade.sh's client checkout failed on a colliding untracked file: "
        f"{result.stderr.strip()}"
    )
    assert (client / "uv.lock").read_text(
        encoding="utf-8"
    ) == "locked-by-upstream\n", "Landed on the tag but kept the stray untracked file."


def test_upgrade_sh_client_checkout_lands_on_target_commit(
    client_at_old_tag: Path,
) -> None:
    """The resulting HEAD is the tag's commit, not merely a clean tree."""
    client = client_at_old_tag
    expected = _git("rev-parse", f"{_FIXTURE_TAG}^{{commit}}", cwd=client).stdout.strip()

    result = _git(*_client_reset_args(), cwd=client)
    _require_ok(result, "client checkout")

    landed = _git("rev-parse", "HEAD", cwd=client).stdout.strip()
    assert landed == expected, "client checkout did not land HEAD on the target tag"


def test_self_install_path_is_not_forced() -> None:
    """Self-install mode must keep the checkout that REFUSES on a dirty tree.

    In self-install mode ``$DAEMON_DIR`` is the developer's own project root.
    Widening the client-mode force onto that path would silently discard
    uncommitted work in a real repository, so the two paths must stay distinct.
    """
    script = LAYER1_UPGRADE_SH.read_text(encoding="utf-8")

    assert _GUARDED_CHECKOUT_BLOCK.search(script) is not None, (
        "scripts/upgrade.sh no longer pairs a non-forcing `git checkout` under "
        '`if [ "$SELF_INSTALL" = "true" ]` with the forced reset in its else '
        "branch. In self-install mode $DAEMON_DIR is the developer's own "
        "project root -- forcing it would discard their uncommitted work."
    )
