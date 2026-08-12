r"""upgrade.sh must only ever operate on the daemon dir's OWN repository.

This became safety-critical when Step 6 changed from ``git checkout <tag>`` to
``git reset --hard <tag>`` for client installs (see
``test_upgrade_sh_forced_checkout.py``). A checkout that lands in the wrong
repository aborts on the first dirty file; a hard reset does not.

The dangerous shape is ordinary: a client project is itself a git repo, and a
half-finished install leaves ``.claude/hooks-daemon/`` as a PLAIN directory
inside it. Ask git about that directory and it walks UP and cheerfully answers
about the parent — the user's own project. A forced reset there would discard
the user's uncommitted work and move their branch onto a daemon release tag.

``[ -d "$DAEMON_DIR/.git" ]`` never had that hole (a ``.git`` DIRECTORY means
the dir IS a clone root) but is too narrow: a git WORKTREE or SUBMODULE stores
``.git`` as a FILE and is a perfectly valid repository. That narrowness is not
theoretical — it is why ``scripts/dummy-client-repo.sh``, the project's own
client-mode test harness, cannot exercise upgrade.sh at all.

``git rev-parse --show-prefix`` answers the real question directly: it prints
the path of the queried directory RELATIVE to its repo toplevel, so it is empty
exactly when that directory IS the toplevel. It accepts clones, worktrees and
submodules, rejects a nested plain directory, and needs no path comparison —
which matters, because comparing ``--show-toplevel`` against ``$DAEMON_DIR``
would produce false aborts whenever symlinks make the two spellings differ.

Both upgrade layers are covered here. Layer 1 (``scripts/upgrade.sh``) was
fixed first; Layer 2 (``scripts/upgrade_version.sh``) — the orchestrator
``BUG_REPORTING.md`` and every upgrade guide tell clients to run directly —
kept the narrow test afterwards. Same defect, diagnosed once, corrected in one
script and left in its sibling. Asserting both here is what stops them drifting
apart again.

Behavioural test — builds real git repositories and runs the real invocation
extracted from each script.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
# Layer 2, the version orchestrator clients are told to run directly by
# BUG_REPORTING.md and every upgrade guide. It carried the narrow
# `[ -d "$DAEMON_DIR/.git" ]` test for as long as Layer 1 did, and kept it
# after Layer 1 was fixed — the same defect, diagnosed once, corrected in one
# script and left in its sibling. Both are asserted here so they cannot drift
# apart again.
LAYER2_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"
GIT = shutil.which("git") or "/usr/bin/git"
_TIMEOUT_SECONDS = 60

_DAEMON_DIR_VAR = '"$DAEMON_DIR"'

# The repo-root probe in scripts/upgrade.sh. Anchored on the rev-parse so an
# unrelated git call cannot satisfy it. Captures the git ARGUMENTS only —
# trailing shell redirects are part of the script, not of argv, and passing
# "2>/dev/null" to git as a literal argument makes every case fail.
_REPO_ROOT_PROBE = re.compile(
    r'git\s+-C\s+"\$DAEMON_DIR"\s+(?P<args>rev-parse\s+--show-prefix)\b',
)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [GIT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _require_ok(result: subprocess.CompletedProcess[str], what: str) -> None:
    if result.returncode != 0:
        raise AssertionError(f"fixture setup failed ({what}): {result.stderr.strip()}")


def _probe_args_for(script_path: Path) -> list[str]:
    """Extract the real repo-root probe from an upgrade script."""
    script = script_path.read_text(encoding="utf-8")
    match = _REPO_ROOT_PROBE.search(script)
    assert match is not None, (
        f"{script_path.name} no longer probes the daemon dir with "
        '`git -C "$DAEMON_DIR" rev-parse --show-prefix`. Step 6 force-resets that '
        "directory, so the check that it is the repo TOPLEVEL is what stands between "
        "a client upgrade and a hard reset of the user's own project. Do not delete "
        "this test."
    )
    return match.group("args").split()


def _probe_args() -> list[str]:
    """Extract the real repo-root probe from scripts/upgrade.sh."""
    return _probe_args_for(LAYER1_UPGRADE_SH)


def _is_repo_root(daemon_dir: Path) -> bool:
    """Run the script's own probe and apply the script's own verdict rule."""
    result = _git(*_probe_args(), cwd=daemon_dir)
    if result.returncode != 0:
        return False
    return result.stdout.strip() == ""


@pytest.fixture
def shapes(tmp_path: Path) -> dict[str, Path]:
    """Build the four daemon-dir shapes upgrade.sh can encounter."""
    # A source repo to clone / add worktrees from.
    src = tmp_path / "src"
    src.mkdir()
    _require_ok(_git("init", "-q", "-b", "main", ".", cwd=src), "init src")
    _require_ok(_git("config", "user.email", "test@example.com", cwd=src), "email")
    _require_ok(_git("config", "user.name", "Test", cwd=src), "name")
    (src / "f.txt").write_text("x\n", encoding="utf-8")
    _require_ok(_git("add", "f.txt", cwd=src), "add")
    _require_ok(_git("commit", "-qm", "seed", cwd=src), "commit")

    # 1. THE DANGEROUS ONE: a plain dir inside the user's own repo.
    parent = tmp_path / "parent"
    parent.mkdir()
    _require_ok(_git("init", "-q", ".", cwd=parent), "init parent")
    nested = parent / ".claude" / "hooks-daemon"
    nested.mkdir(parents=True)

    # 2. A normal client install (clone root, .git is a DIRECTORY).
    clone = tmp_path / "clone"
    _require_ok(_git("clone", "-q", str(src), str(clone), cwd=tmp_path), "clone")

    # 3. A worktree root (.git is a FILE) — valid, but rejected by [ -d .git ].
    worktree = tmp_path / "wt"
    _require_ok(_git("worktree", "add", "-q", "--detach", str(worktree), cwd=src), "worktree")

    # 4. Not a repo, and no parent repo either.
    orphan = tmp_path / "orphan"
    orphan.mkdir()

    return {"nested": nested, "clone": clone, "worktree": worktree, "orphan": orphan}


class TestDaemonDirMustBeItsOwnRepoRoot:
    def test_rejects_plain_dir_inside_the_users_own_repo(self, shapes: dict[str, Path]) -> None:
        """The catastrophic case: git would answer about the PARENT repo."""
        nested = shapes["nested"]

        # Precondition: git really does resolve this to the parent, which is
        # what makes a naive `rev-parse --git-dir` test unsafe.
        assert _git("rev-parse", "--git-dir", cwd=nested).returncode == 0, (
            "fixture is not exercising the hazard — git should resolve the "
            "nested dir to its parent repo"
        )

        assert _is_repo_root(nested) is False, (
            "upgrade.sh would treat the user's own project as the daemon repo "
            "and hard-reset it onto a daemon release tag."
        )

    def test_rejects_directory_that_is_not_in_any_repo(self, shapes: dict[str, Path]) -> None:
        assert _is_repo_root(shapes["orphan"]) is False

    def test_accepts_a_normal_clone(self, shapes: dict[str, Path]) -> None:
        assert _is_repo_root(shapes["clone"]) is True

    def test_accepts_a_worktree(self, shapes: dict[str, Path]) -> None:
        """A worktree stores .git as a FILE; it is still a real repository.

        This is the shape scripts/dummy-client-repo.sh builds, so the old
        `[ -d .git ]` test made the project's own client-mode harness unable
        to exercise upgrade.sh.
        """
        worktree = shapes["worktree"]
        assert (worktree / ".git").is_file(), "fixture did not produce a .git FILE"

        assert _is_repo_root(worktree) is True


class TestLayer2UsesTheSameProbe:
    """Layer 2 must accept every shape Layer 1 accepts.

    `upgrade_version.sh` is not an internal helper — `BUG_REPORTING.md` and
    every upgrade guide tell clients to invoke it directly. It kept the narrow
    `[ -d "$DAEMON_DIR/.git" ]` test after Layer 1 replaced it, so a daemon
    installed as a worktree or submodule was rejected by the Layer 2 upgrade
    path while Layer 1 accepted it.

    The narrow test was SAFE, not dangerous — a `.git` DIRECTORY does mean the
    dir is a clone root, so it never false-ACCEPTED the hazardous nested-plain-
    dir shape. What it did was false-REJECT valid repositories, which is why
    `scripts/dummy-client-repo.sh` could not exercise this script and the
    Layer 2 upgrade path went untested in client mode.
    """

    def _layer2_is_repo_root(self, daemon_dir: Path) -> bool:
        result = _git(*_probe_args_for(LAYER2_UPGRADE_SH), cwd=daemon_dir)
        if result.returncode != 0:
            return False
        return result.stdout.strip() == ""

    def test_layer2_accepts_a_worktree(self, shapes: dict[str, Path]) -> None:
        """The shape dummy-client-repo.sh builds, and the reason for this fix."""
        worktree = shapes["worktree"]
        assert (worktree / ".git").is_file(), "fixture did not produce a .git FILE"

        assert self._layer2_is_repo_root(worktree) is True

    def test_layer2_accepts_a_normal_clone(self, shapes: dict[str, Path]) -> None:
        """Control: the fix must not trade one shape for another."""
        assert self._layer2_is_repo_root(shapes["clone"]) is True

    def test_layer2_still_rejects_plain_dir_inside_the_users_own_repo(
        self, shapes: dict[str, Path]
    ) -> None:
        """Widening must not cost the safety property the narrow test had."""
        assert self._layer2_is_repo_root(shapes["nested"]) is False

    def test_layer2_still_rejects_a_directory_in_no_repo(self, shapes: dict[str, Path]) -> None:
        assert self._layer2_is_repo_root(shapes["orphan"]) is False

    def test_layer2_no_longer_uses_the_narrow_git_directory_test(self) -> None:
        """Guard against a revert to `[ -d "$DAEMON_DIR/.git" ]`.

        Without this, someone "simplifying" the check back would silently
        reintroduce the false-reject and re-break the client-mode harness.
        """
        # Comment lines are skipped deliberately. The replacement's own comment
        # NAMES the old test in order to explain why it was replaced, and a
        # detector that matched that would fire on the very documentation of the
        # fix — the same prose-vs-code false positive this repo just fixed in
        # pipe_blocker. Match executable lines only.
        code_lines = [
            line
            for line in LAYER2_UPGRADE_SH.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        ]

        narrow_test = [
            line for line in code_lines if re.search(r'\[\s*!?\s*-d\s+"\$DAEMON_DIR/\.git"', line)
        ]

        assert not narrow_test, (
            "scripts/upgrade_version.sh is back to testing for a .git DIRECTORY: "
            f"{narrow_test}. That false-rejects worktrees and submodules, which "
            "store .git as a FILE, and re-breaks scripts/dummy-client-repo.sh. Use "
            '`git -C "$DAEMON_DIR" rev-parse --show-prefix` as Layer 1 does.'
        )

    def test_the_narrow_test_detector_can_actually_see_it(self) -> None:
        """Positive control for the assertion above.

        Skipping comments is what makes that check usable, but it is also how
        it could go blind — one over-broad skip rule and it would report clean
        forever. Plant the pattern as executable text and require a hit.
        """
        planted = 'if [ ! -d "$DAEMON_DIR/.git" ]; then'

        assert re.search(r'\[\s*!?\s*-d\s+"\$DAEMON_DIR/\.git"', planted), (
            "the detector no longer recognises the narrow test even when it is "
            "present as code — the guard above is blind and would pass regardless."
        )
        assert not planted.lstrip().startswith("#"), "planted control must be code, not a comment"


class TestProbeIsPathComparisonFree:
    def test_probe_does_not_compare_show_toplevel_to_daemon_dir(self) -> None:
        """A `--show-toplevel` string comparison would abort on symlinked paths.

        `--show-prefix` asks the question directly and needs no normalisation,
        so guard against a future "simplification" back to comparing paths.
        """
        script = LAYER1_UPGRADE_SH.read_text(encoding="utf-8")

        toplevel_compare = re.search(
            r"--show-toplevel[^\n]*\]\s*=\s*" + re.escape(_DAEMON_DIR_VAR),
            script,
        )
        assert toplevel_compare is None, (
            "upgrade.sh compares `--show-toplevel` against $DAEMON_DIR. That "
            "aborts whenever symlinks make the two spellings differ. Use "
            "`--show-prefix` (empty == toplevel) instead."
        )
