"""Every daemon-shipped skill tree is deployed, tracked and free of drift.

Plan 00338. ``.claude/.gitignore`` carries the unanchored pattern
``hooks-daemon/``, whose own comment says it excludes "the cloned daemon
repository" — that is ``.claude/hooks-daemon/``. Without a leading slash git
matches at every depth below ``.claude/``, so it also swallowed
``.claude/skills/hooks-daemon/``, the DEPLOYED skill tree, which has nothing
to do with the clone.

The cost was measured, not supposed: Plan 00336 Task 4.3 found
``.claude/skills/hooks-daemon/references/troubleshooting.md`` still naming a
``/tmp`` path its source had moved off. Nobody saw it because ``git status``
cannot report a file git is ignoring. The sibling deployed skill,
``.claude/skills/docs-qa/``, IS tracked, and its equivalent drift surfaced the
moment it was redeployed — two adjacent trees, opposite treatment, decided by
a missing ``/``.

These tests pin the two properties that make the treatment a decision rather
than a side effect: every deployed skill tree is visible to git, and every one
still matches the source it was copied from.
"""

from __future__ import annotations

import filecmp
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SKILLS_ROOT = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills"
DEPLOYED_SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"
GIT = shutil.which("git") or "git"

# The path git is asked about when checking the daemon-clone exclusion.
#
# A path INSIDE the directory, deliberately. The pattern is `/hooks-daemon/`,
# and a trailing slash makes it DIRECTORY-ONLY: git will not match it against a
# path it cannot tell is a directory, which means any checkout where the clone
# is absent answers "not ignored". Naming the bare directory therefore tested
# the container rather than the pattern -- it passed here, where a deployed
# install exists, and failed on every CI runner.
_DAEMON_CLONE_PROBE = Path(".claude") / "hooks-daemon" / "README.md"


def _deployed_skill_trees() -> list[Path]:
    return sorted(path for path in DEPLOYED_SKILLS_ROOT.iterdir() if path.is_dir())


def _shipped_skill_names() -> list[str]:
    """The skills ``deploy_skills`` copies: one subdirectory per bundled skill."""
    return sorted(path.name for path in SOURCE_SKILLS_ROOT.iterdir() if path.is_dir())


def _is_ignored(path: Path) -> bool:
    """Whether git is ignoring ``path``. ``check-ignore`` exits 1 when it is not."""
    result = subprocess.run(
        [GIT, "-C", str(REPO_ROOT), "check-ignore", "-q", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _drifted_files(source: Path, deployed: Path) -> list[str]:
    """Repo-relative paths differing between the two trees, recursively."""
    comparison = filecmp.dircmp(str(source), str(deployed))
    drifted: list[str] = []

    def walk(node: filecmp.dircmp, prefix: str) -> None:
        for name in sorted(node.left_only):
            drifted.append(f"{prefix}{name} (in source, not deployed)")
        for name in sorted(node.right_only):
            drifted.append(f"{prefix}{name} (deployed, not in source)")
        for name in sorted(node.diff_files):
            drifted.append(f"{prefix}{name} (contents differ)")
        for name, sub in sorted(node.subdirs.items()):
            walk(sub, f"{prefix}{name}/")

    walk(comparison, "")
    return drifted


class TestEveryDeployedSkillTreeIsVisibleToGit:
    """A tree git ignores cannot be reviewed, and drifts in silence."""

    def test_no_deployed_skill_tree_is_ignored(self) -> None:
        ignored = [
            str(tree.relative_to(REPO_ROOT))
            for tree in _deployed_skill_trees()
            if _is_ignored(tree)
        ]

        assert not ignored, (
            "These deployed skill trees are invisible to `git status`, so drift "
            "from their source reaches no review and no commit gate:\n  "
            + "\n  ".join(ignored)
            + "\nAnchor the .claude/.gitignore pattern that catches them "
            "(a leading `/` confines it to .claude/ itself), or ignore them "
            "explicitly by name so the next reader sees a decision."
        )

    def test_the_daemon_clone_directory_stays_ignored(self) -> None:
        """The regression guard on the other side of the anchor.

        ``.claude/hooks-daemon/`` is a full clone of this repository in a
        client install. Anchoring the pattern must not stop excluding it —
        that is the exclusion the comment is actually about.
        """
        assert _is_ignored(REPO_ROOT / _DAEMON_CLONE_PROBE), (
            "The daemon clone directory is no longer ignored. Anchoring the "
            "pattern went too far — `/hooks-daemon/` still has to match "
            ".claude/hooks-daemon/."
        )

    def test_the_exclusion_holds_where_the_clone_is_absent(self, tmp_path: Path) -> None:
        """The same guard, asked somewhere the directory does NOT exist.

        This is the CI condition, and it is why the assertion above must not
        name the bare directory. ``/hooks-daemon/`` carries a trailing slash,
        which makes it DIRECTORY-ONLY, and git cannot know that a path which is
        not on disk is a directory — so `check-ignore` answers "not ignored"
        on any checkout without a deployed client install. In this container
        the directory exists, the pattern matches, and the test passed while CI
        failed on the identical assertion.
        """
        (tmp_path / ".claude").mkdir(parents=True)
        subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True)
        (tmp_path / ".claude" / ".gitignore").write_text(
            (REPO_ROOT / ".claude" / ".gitignore").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        result = subprocess.run(
            [GIT, "-C", str(tmp_path), "check-ignore", "-q", str(tmp_path / _DAEMON_CLONE_PROBE)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, (
            "The daemon-clone exclusion does not hold on a checkout without a "
            "deployed install, so this guard only ever tested the container it "
            "ran in. Ask git about a path INSIDE the directory — that answer "
            "does not depend on the directory being present."
        )


class TestEveryDeployedSkillTreeMatchesItsSource:
    """Tracking makes drift REVIEWABLE; this makes it DETECTED.

    A deployed tree that matches today can drift tomorrow, and the redeploy
    that would reveal it may be months away — which is exactly how the
    ``troubleshooting.md`` drift survived. Comparing the trees turns the
    discovery from an accident into a check.
    """

    def test_every_shipped_skill_is_deployed(self) -> None:
        deployed = {tree.name for tree in _deployed_skill_trees()}
        missing = [name for name in _shipped_skill_names() if name not in deployed]

        assert not missing, (
            "Skills bundled in the daemon source were never deployed to "
            f".claude/skills/: {missing}. Run the daemon's skill deployment."
        )

    def test_no_deployed_skill_tree_has_drifted_from_its_source(self) -> None:
        drift: list[str] = []
        for name in _shipped_skill_names():
            source = SOURCE_SKILLS_ROOT / name
            deployed = DEPLOYED_SKILLS_ROOT / name
            if not deployed.is_dir():
                continue
            drift.extend(f"{name}/{entry}" for entry in _drifted_files(source, deployed))

        assert not drift, (
            "A deployed skill tree no longer matches the source it was copied "
            "from. The deployed copy is generated — edit the source under "
            "src/claude_code_hooks_daemon/skills/ and redeploy, never the "
            "deployed file:\n  " + "\n  ".join(drift)
        )
