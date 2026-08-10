"""Detecting an upstream HISTORY REWRITE, as distinct from ordinary divergence.

Why this distinction is worth code: the two states look identical to
``git status`` -- both report "diverged, N ahead, M behind" -- but the correct
response is opposite.

* Ordinary divergence: local work and remote work are genuinely different.
  Merging is right.
* History rewrite: the remote replayed the SAME content under new shas (a
  ``filter-repo`` run to strip secrets, say). Every local commit is a
  pre-rewrite duplicate. Merging re-introduces every commit the rewrite
  existed to destroy, and re-publishes them.

The discriminator is the TREE. A rewrite changes commit metadata and leaves
content untouched, so HEAD and upstream resolve to the same tree object while
their commit shas differ. Ordinary divergence changes content, so the trees
differ too.

These tests build real repositories. The rewrite is modelled with
``git commit-tree`` + ``update-ref`` on the bare remote, which produces exactly
what a rewrite produces -- an identical tree under a new sha -- without needing
a force-push or a second working copy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.utils import git_sync

_TIMEOUT = 30


def _run(cwd: Path, *args: str) -> str:
    """Run git and return trimmed stdout, raising on failure (fixtures FAIL FAST)."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=_TIMEOUT,
    )
    return result.stdout.strip()


def _init(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )
    _run(path, "config", "user.email", "test@example.com")
    _run(path, "config", "user.name", "Test")


def _clone_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(bare_remote, clone)`` sharing one root commit."""
    seed = tmp_path / "seed"
    _init(seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _run(seed, "add", "README.md")
    _run(seed, "commit", "-qm", "seed")

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(seed), str(remote)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(remote), str(clone)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )
    _run(clone, "config", "user.email", "test@example.com")
    _run(clone, "config", "user.name", "Test")
    return remote, clone


def _rewrite_remote(remote: Path, clone: Path) -> None:
    """Replay the remote tip under a new sha, keeping the tree byte-identical."""
    tree = _run(clone, "rev-parse", "HEAD^{tree}")
    rewritten = _run(remote, "commit-tree", tree, "-m", "rewritten")
    _run(remote, "update-ref", "refs/heads/main", rewritten)
    _run(clone, "fetch", "--quiet", "origin")


def _advance_remote_with_content(tmp_path: Path, remote: Path) -> None:
    """Add a genuinely new remote commit that CHANGES content."""
    pusher = tmp_path / "pusher"
    subprocess.run(
        ["git", "clone", str(remote), str(pusher)],
        capture_output=True,
        check=True,
        timeout=_TIMEOUT,
    )
    _run(pusher, "config", "user.email", "test@example.com")
    _run(pusher, "config", "user.name", "Test")
    (pusher / "new.txt").write_text("genuinely new\n", encoding="utf-8")
    _run(pusher, "add", "new.txt")
    _run(pusher, "commit", "-qm", "real work")
    _run(pusher, "push", "-q", "origin", "main")


class TestUpstreamTreeMatches:
    """``upstream_tree_matches`` separates a rewrite from real divergence."""

    def test_true_when_remote_was_rewritten(self, tmp_path: Path) -> None:
        remote, clone = _clone_with_remote(tmp_path)
        _rewrite_remote(remote, clone)

        # Precondition: this really is a divergence, not a fast-forward.
        status = git_sync.upstream_status(clone)
        assert status is not None
        assert status.ahead > 0 and status.behind > 0, "fixture did not diverge"

        assert git_sync.upstream_tree_matches(clone) is True

    def test_false_when_remote_has_genuinely_new_work(self, tmp_path: Path) -> None:
        remote, clone = _clone_with_remote(tmp_path)
        _advance_remote_with_content(tmp_path, remote)
        _run(clone, "fetch", "--quiet", "origin")

        assert git_sync.upstream_tree_matches(clone) is False

    def test_true_when_merely_up_to_date(self, tmp_path: Path) -> None:
        """Identical trees with no divergence is not a rewrite, but is still
        truthfully 'same tree'. Callers gate on divergence separately, so this
        pins that the function reports the TREE and nothing else."""
        _, clone = _clone_with_remote(tmp_path)

        assert git_sync.upstream_tree_matches(clone) is True

    def test_false_when_no_upstream(self, tmp_path: Path) -> None:
        repo = tmp_path / "solo"
        _init(repo)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        _run(repo, "add", "f.txt")
        _run(repo, "commit", "-qm", "only")

        assert git_sync.upstream_tree_matches(repo) is False

    def test_false_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()

        assert git_sync.upstream_tree_matches(plain) is False


def _commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _run(repo, "add", name)
    _run(repo, "commit", "-qm", f"add {name}")


def _rewrite_whole_history(remote: Path, clone: Path) -> None:
    """Replay EVERY commit under a new sha, keeping each tree byte-identical.

    This is what ``filter-repo`` does to the commits at and after the first
    modified one: same content, new shas, so the patch IDs still match.
    """
    parent = ""
    for sha in _run(clone, "rev-list", "--reverse", "HEAD").splitlines():
        tree = _run(clone, "rev-parse", f"{sha}^{{tree}}")
        args = ["commit-tree", tree, "-m", f"rewritten {sha[:7]}"]
        if parent:
            args += ["-p", parent]
        parent = _run(remote, *args)
    _run(remote, "update-ref", "refs/heads/main", parent)
    _run(clone, "fetch", "--quiet", "origin")


class TestUpstreamWasRewritten:
    """The realistic case: a rewrite with local commits stacked on top.

    Tree equality alone is not enough. ANY local commit changes the tree, so a
    tree-only check silently stops firing the moment a single commit lands
    locally after the rewrite — which is exactly when the wrong advice is most
    likely to be acted on. Patch-id equivalence keeps working.
    """

    def test_true_for_pure_rewrite(self, tmp_path: Path) -> None:
        remote, clone = _clone_with_remote(tmp_path)
        _rewrite_remote(remote, clone)

        assert git_sync.upstream_was_rewritten(clone) is True

    def test_true_when_local_commits_sit_on_top_of_a_rewrite(self, tmp_path: Path) -> None:
        """The case tree-equality misses entirely."""
        remote, clone = _clone_with_remote(tmp_path)
        _commit(clone, "a.txt", "a\n")
        _commit(clone, "b.txt", "b\n")
        _run(clone, "push", "-q", "origin", "main")
        _rewrite_whole_history(remote, clone)
        # A genuinely new local commit AFTER the rewrite: trees now differ.
        _commit(clone, "later.txt", "later\n")

        assert git_sync.upstream_tree_matches(clone) is False, (
            "fixture failed to make the trees differ — it would not exercise " "the patch-id path"
        )
        assert git_sync.upstream_was_rewritten(clone) is True

    def test_false_for_ordinary_divergence(self, tmp_path: Path) -> None:
        """Both sides did real, different work. Merging is correct here."""
        remote, clone = _clone_with_remote(tmp_path)
        _advance_remote_with_content(tmp_path, remote)
        _run(clone, "fetch", "--quiet", "origin")
        _commit(clone, "mine.txt", "local work\n")

        assert git_sync.upstream_was_rewritten(clone) is False

    def test_false_when_not_a_repo(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()

        assert git_sync.upstream_was_rewritten(plain) is False
