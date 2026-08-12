"""Shared fixture helpers for the upgrade acceptance gates.

Three separate upgrade gates each need the same fixture: a local clone of this
repository that an installer can be pointed at, and a real tag to upgrade to.
Each carried its own copy of the clone helper, and each independently resolved
the target tag *after* installing. That duplication hid a defect, so the helper
now lives here once.

**Why the clone is pinned to a tag before anything is installed.**

These gates install a baseline and then upgrade it to the newest tag, asserting
the upgrade is idempotent — their docstrings say so explicitly. Cloning at HEAD
makes that premise true only *between* releases. During a release, HEAD is
already stamped with the new version while the newest tag is still the previous
one, so "upgrade to the newest tag" silently becomes a **downgrade**: the
version-specific upgrader sees a stamp mismatch, rebuilds the virtualenv, and
the run dies far from here with an opaque ``No interpreter found at path`` from
uv. The tests then fail for a reason that has nothing to do with what they
test.

That is guaranteed to happen at exactly the wrong moment. The release process
bumps the version (Step 3) long before it creates the tag (Step 14), and the
blocking QA gate runs in between — so these gates were structurally
unsatisfiable during every version-bumping release, which is the one time they
matter most.

Pinning the clone to the tag *before* the baseline install makes installed
version == target version in both conditions, with no synthesised state and no
invented tags. ``assert_clone_is_pinned`` then re-checks that premise so a
future drift fails here, named, instead of surfacing as a uv error deep inside
a subprocess.
"""

from __future__ import annotations

import subprocess  # nosec B404 - trusted system tool (git) for repo fixtures
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    result = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _git_allowing_failure(*args: str) -> str:
    """Run git, returning empty on a non-zero exit.

    Used only where a non-zero exit IS one of the expected answers rather than
    an error — ``describe --exact-match`` exits non-zero to say "HEAD is not at
    a tag", which is exactly the condition the caller wants to report on.
    """
    result = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else ""


def create_daemon_clone(daemon_dir: Path) -> str:
    """Clone this repo into ``daemon_dir``, pin it to its newest tag, return the tag.

    Layer 1 ``scripts/upgrade.sh`` requires ``$DAEMON_DIR/.git`` to be a real
    directory (not a worktree pointer), so this is a local ``--no-hardlinks``
    clone; it keeps the fixture isolated and brings tags along.

    The returned tag is the one callers must pass as the upgrade target. Read
    the module docstring before changing the pinning — it is load-bearing, not
    tidiness.
    """
    _git(
        "-c",
        "protocol.file.allow=always",
        "clone",
        "--no-hardlinks",
        "--local",
        "--quiet",
        str(REPO_ROOT),
        str(daemon_dir),
    )
    _git("-C", str(daemon_dir), "config", "protocol.file.allow", "always")

    tag = _git("-C", str(daemon_dir), "describe", "--tags", "--abbrev=0").strip()
    if not tag:
        raise AssertionError(f"No tag reachable from HEAD in the clone at {daemon_dir}")

    # Pin BEFORE the baseline install, so the install is stamped with the same
    # version the upgrade will target.
    _git("-C", str(daemon_dir), "checkout", "--quiet", tag)
    return tag


def assert_clone_is_pinned(daemon_dir: Path, tag: str) -> None:
    """Fail loudly, and by name, if the idempotency premise no longer holds.

    Cheap to run and worth running: without it the same drift reappears as an
    unrelated-looking uv failure inside a subprocess, which is how it cost a
    release cycle the first time.

    ``--exact-match`` exits NON-ZERO to report "HEAD is not at a tag", which is
    the single most likely way this premise breaks — so it must not be run under
    ``check=True``, or this guard would itself die with a subprocess traceback
    instead of printing the diagnosis below.
    """
    described = _git_allowing_failure(
        "-C", str(daemon_dir), "describe", "--tags", "--exact-match"
    ).strip()
    if described != tag:
        raise AssertionError(
            f"Upgrade fixture premise broken: the clone at {daemon_dir} must be "
            f"checked out at {tag} before the baseline install, so that upgrading "
            f"to {tag} is idempotent. It is at {described or 'an untagged commit'} "
            f"instead, which turns the upgrade into a downgrade and rebuilds the "
            f"venv. See this module's docstring."
        )
