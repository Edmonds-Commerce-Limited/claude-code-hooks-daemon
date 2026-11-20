"""A fake scratch tree for the scratch-sweep tests (Plan 00627 Task 1.1).

``root`` plays ``untracked/scratch/``; ``outside`` is a sibling directory that
holds dummy files a link inside the root may point at, so a test can prove the
sweep never followed one. Every timestamp is set with ``lstat`` semantics
(``follow_symlinks=False``), so ageing a tree never touches a link's target.

An unreadable directory is made with :meth:`ScratchTree.refusing_scandir`
rather than ``chmod 000``: these tests run as root in the container, where a
mode of 000 does not stop a listing, and a test built on it would pass without
testing anything.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - test fixtures build real git repositories
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.core.scratch_repos import ProjectGit
from claude_code_hooks_daemon.core.scratch_walk import ScandirFn

#: name relative to ``base`` -> (mtime_ns, ctime_ns), every inode, links not followed.
Snapshot = dict[str, tuple[int, int]]


@dataclass(frozen=True)
class ScratchTree:
    """A scratch root and an outside directory under one temporary base."""

    base: Path
    root: Path
    outside: Path

    def _path(self, rel: str) -> Path:
        return self.root / rel

    def file(self, rel: str, content: bytes = b"x", mtime: float | None = None) -> Path:
        """A regular file at ``rel`` under the root, parents created."""
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if mtime is not None:
            os.utime(path, (mtime, mtime), follow_symlinks=False)
        return path

    def directory(self, rel: str, mtime: float | None = None) -> Path:
        """A directory at ``rel`` under the root."""
        path = self._path(rel)
        path.mkdir(parents=True, exist_ok=True)
        if mtime is not None:
            os.utime(path, (mtime, mtime), follow_symlinks=False)
        return path

    def outside_dummy(self, name: str, content: bytes = b"dummy") -> Path:
        """A dummy file outside the root, for a link to point at."""
        path = self.outside / name
        path.write_bytes(content)
        return path

    def symlink(self, rel: str, target: Path | str) -> Path:
        """A symbolic link at ``rel`` pointing at ``target`` (never resolved)."""
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        return path

    def hardlink(self, rel: str, existing: Path) -> Path:
        """A second name at ``rel`` for the inode of ``existing``."""
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.hardlink_to(existing)
        return path

    def fifo(self, rel: str) -> Path:
        """A named pipe at ``rel``."""
        path = self._path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)
        return path

    def git_marker(self, rel_dir: str, gitdir: str | None = None) -> Path:
        """A ``.git`` directory in ``rel_dir``, or a ``.git`` FILE naming ``gitdir``."""
        directory = self.directory(rel_dir)
        marker = directory / ".git"
        if gitdir is None:
            marker.mkdir()
        else:
            marker.write_text(f"gitdir: {gitdir}\n")
        return marker

    def set_tree_mtime(self, rel: str, mtime: float) -> None:
        """Set the mtime of ``rel`` and everything under it, deepest first, links not followed."""
        top = self._path(rel)
        for path in [*self._descendants(top), top]:
            os.utime(path, (mtime, mtime), follow_symlinks=False)

    def _descendants(self, top: Path) -> list[Path]:
        if top.is_symlink() or not top.is_dir():
            return []
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(top, topdown=False):
            found.extend(Path(dirpath) / name for name in (*filenames, *dirnames))
        return found

    def refusing_scandir(self, *refused: str) -> ScandirFn:
        """``os.scandir``, raising ``PermissionError`` for each directory in ``refused``."""
        blocked = {str(self._path(rel)) for rel in refused}

        def scandir(path: str) -> os._ScandirIterator[str]:
            if path in blocked:
                raise PermissionError(13, "Permission denied", path)
            return os.scandir(path)

        return scandir

    def snapshot(self) -> Snapshot:
        """Every inode under ``base`` (root and outside): name -> (mtime_ns, ctime_ns).

        atime is left out on purpose: listing a directory may change it.
        """
        result: Snapshot = {}
        for path in self._all_under_base():
            info = os.lstat(path)
            result[path.relative_to(self.base).as_posix()] = (info.st_mtime_ns, info.st_ctime_ns)
        return result

    def _all_under_base(self) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(self.base):
            yield Path(dirpath)
            for name in filenames:
                yield Path(dirpath) / name
            for name in dirnames:
                candidate = Path(dirpath) / name
                if candidate.is_symlink():
                    yield candidate


#: Every git the helpers run reads no global or system config, so a developer's
#: own settings (hooks, filters, a default branch) cannot change a fixture.
GIT_TEST_ENV: dict[str, str] = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_TERMINAL_PROMPT": "0",
}


def git(cwd: Path, *args: str) -> str:
    """Run git in ``cwd`` for a fixture; raises when git fails. Returns stdout, stripped."""
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        **GIT_TEST_ENV,
    }
    done = subprocess.run(  # nosec B603 B607 - fixed argv, test fixture only
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return done.stdout.strip()


def commit_file(repo: Path, rel: str, content: str, message: str = "c") -> str:
    """Write ``rel`` in ``repo``, commit it, and return the new HEAD sha."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    git(repo, "add", "--", rel)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@dataclass(frozen=True)
class GitProject:
    """A real project repository with a bare ``origin``, around a scratch tree."""

    tree: ScratchTree
    project: Path
    remote: Path

    def clone(self, rel: str) -> Path:
        """A clone of the project at ``rel`` under the scratch root, its remote kept."""
        target = self.tree.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        # file:// so objects are copied: a local-path clone hard-links them, and the
        # walk's link-count rule would make every such entry STUCK.
        git(self.tree.root, "clone", "-q", f"file://{self.remote}", str(target))
        return target

    def standalone(self, rel: str, *, commit: bool = True) -> Path:
        """A fresh repository at ``rel``: no remote, history unrelated to the project."""
        target = self.tree.root / rel
        target.mkdir(parents=True, exist_ok=True)
        git(target, "init", "-q", "-b", "main")
        if commit:
            commit_file(target, "notes.txt", "standalone\n")
        return target

    def worktree(self, rel: str, branch: str) -> Path:
        """A registered worktree of the project at ``rel`` on a new ``branch``."""
        target = self.tree.root / rel
        git(self.project, "worktree", "add", "-q", "-b", branch, str(target))
        return target


#: The one commit :func:`quiet_project_git` reports for HEAD and its one branch.
QUIET_SHA = "0" * 39 + "1"


def quiet_project_git(project_root: Path) -> ProjectGit:
    """A project whose git answers every question with "nothing": no tracked file
    under the root, no worktree, no remote, one branch and no reference to the root.
    For sweep tests whose point is not git.

    The reference set reads an empty answer as UNKNOWN, so the questions it asks
    get a real "nothing": ``git grep`` answers rc 1 (no match), and HEAD and the
    branch listing name one fake commit."""

    def runner(
        cwd: Path, *args: str, timeout: float = 30.0, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if "grep" in args:
            return subprocess.CompletedProcess(["git", *args], 1, "", "")
        if args[:2] == ("rev-parse", "--verify"):
            return subprocess.CompletedProcess(["git", *args], 0, f"{QUIET_SHA}\n", "")
        if args[:1] == ("for-each-ref",) and args[-1] == "refs/heads/":
            return subprocess.CompletedProcess(
                ["git", *args], 0, f"{QUIET_SHA} refs/heads/main\n", ""
            )
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    return ProjectGit(
        root=project_root,
        remote="origin",
        runner=runner,
        worktrees=frozenset(),
        verified={},
        verified_note="",
        remote_blobs=None,
    )


def build_git_project(base: Path) -> GitProject:
    """A scratch tree whose project is a real repository pushed to a bare ``origin``."""
    tree = build_scratch_tree(base)
    project = base / "project"
    remote = base / "remote.git"
    git(base, "init", "-q", "--bare", "-b", "main", str(remote))
    git(project, "init", "-q", "-b", "main")
    (project / ".gitignore").write_text("untracked/\n")
    git(project, "add", ".gitignore")
    commit_file(project, "src/app.py", "print('app')\n", "initial")
    git(project, "remote", "add", "origin", str(remote))
    git(project, "push", "-q", "origin", "main")
    git(project, "fetch", "-q", "origin")
    git(project, "remote", "set-head", "origin", "main")
    return GitProject(tree=tree, project=project, remote=remote)


def build_scratch_tree(base: Path) -> ScratchTree:
    """A fresh fake tree under ``base`` (normally pytest's ``tmp_path``)."""
    root = base / "project" / "untracked" / "scratch"
    outside = base / "outside"
    root.mkdir(parents=True)
    outside.mkdir()
    return ScratchTree(base=base, root=root, outside=outside)
