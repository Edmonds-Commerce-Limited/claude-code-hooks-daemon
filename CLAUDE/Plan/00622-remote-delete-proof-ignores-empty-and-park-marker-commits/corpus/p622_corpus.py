"""Plan 00622 corpus: every delete-proof decision over a labelled set of branch shapes.

Run once with PYTHONPATH at the pre-fix source and once at the fixed source, each
writing JSON; ``compare`` then counts the flips. Labels are hand-assigned from what
the shape BUILDS, never from either rule:

  Y  every byte of the branch's content is in the default branch
  N  the branch carries content the default does not hold
  E  the branch carries no content at all (only empty commits off the default)

Usage: p622_corpus.py run <workdir> <out.json> | compare <before.json> <after.json>
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
UNPARK = "Unpark branch\n\nUnparked: t\n"
PARK = "Park branch: wait\n\nParked-Reason: wait\nParked-By: t\n"
PROOFS = ("remote", "guard", "local", "local-hook")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=ENV
    ).stdout.strip()


def write(r: Path, f: str, text: str, msg: str | None = None) -> None:
    (r / f).parent.mkdir(parents=True, exist_ok=True)
    (r / f).write_text(text, encoding="utf-8")
    git(r, "add", f)
    git(r, "commit", "-q", "-m", msg or f"write {f}")


def empty(r: Path, msg: str) -> None:
    git(r, "commit", "-q", "--allow-empty", "--cleanup=verbatim", "-m", msg)


def br(r: Path, n: str, start: str = "main") -> None:
    git(r, "checkout", "-q", "-b", n, start)


def on(r: Path, n: str) -> None:
    git(r, "checkout", "-q", n)


def land(r: Path, n: str, how: str) -> None:
    on(r, "main")
    if how == "merge":
        git(r, "merge", "--no-ff", "-q", "-m", f"Merge {n}", n)
    elif how == "ff":
        git(r, "merge", "--ff-only", "-q", n)
    elif how == "squash":
        git(r, "merge", "--squash", "-q", n)
        git(r, "commit", "-q", "-m", f"Squash {n}")
    elif how == "pick":
        write(r, f"unrelated-{n}.txt", "u\n")
        git(r, "cherry-pick", f"main..{n}")
    on(r, n)


def main_write(r: Path, f: str, text: str, back: str) -> None:
    on(r, "main")
    write(r, f, text, f"main {f}")
    on(r, back)


def commit_on(r: Path, n: str, msg: str, parents: list[str], tree: str) -> None:
    args = ["commit-tree", tree, "-m", msg]
    for p in parents:
        args += ["-p", p]
    git(r, "update-ref", f"refs/heads/{n}", git(r, *args))


# --- shapes: (label, builder). Each builder leaves branch `n` built; caller publishes.
def s_ff(r, n):
    br(r, n)
    write(r, f"{n}.txt", "x\n")
    land(r, n, "ff")


def s_merge(r, n):
    br(r, n)
    write(r, f"{n}.txt", "x\n")
    land(r, n, "merge")


def s_squash3(r, n):
    br(r, n)
    for i in range(3):
        write(r, f"{n}{i}.txt", f"{i}\n")
    land(r, n, "squash")


def s_pick(r, n):
    br(r, n)
    write(r, f"{n}a.txt", "a\n")
    write(r, f"{n}b.txt", "b\n")
    land(r, n, "pick")


def s_one_extra(r, n):
    br(r, n)
    write(r, f"{n}a.txt", "a\n")
    write(r, f"{n}b.txt", "b\n")
    on(r, "main")
    git(r, "merge", "--squash", "-q", f"{n}~1")
    git(r, "commit", "-q", "-m", "first")
    on(r, n)


def s_pure_empty(r, n):
    br(r, n)
    empty(r, "Park it")
    main_write(r, f"later-{n}.txt", "l\n", n)


def s_pure_empty_main_empty(r, n):
    br(r, n)
    empty(r, "Park it")
    on(r, "main")
    empty(r, "main empty")
    on(r, n)


def s_pure_writer_park(r, n):
    br(r, n)
    empty(r, PARK)


def s_delete_only(r, n):
    main_write(r, f"keep-{n}.txt", "k\n", "main")
    br(r, n)
    git(r, "rm", "-q", f"keep-{n}.txt")
    git(r, "commit", "-q", "-m", "rm")


def s_delete_only_empty(r, n):
    s_delete_only(r, n)
    empty(r, "Unpark branch")


def s_revert_older(r, n):
    main_write(r, f"k-{n}.txt", "v1\n", "main")
    main_write(r, f"k-{n}.txt", "v2\n", "main")
    br(r, n)
    git(r, "revert", "--no-edit", "HEAD")


def s_revert_older_empty(r, n):
    s_revert_older(r, n)
    empty(r, "Unpark branch")


def s_rename(r, n):
    br(r, n)
    git(r, "mv", "base.txt", f"moved-{n}.txt")
    git(r, "commit", "-q", "-m", "mv")


def s_copy(r, n):
    br(r, n)
    write(r, f"copy-{n}.txt", "base\n")


def s_chmod(r, n):
    br(r, n)
    (r / "base.txt").chmod(0o755)
    git(r, "commit", "-q", "-a", "-m", "x")


def s_main_reverted_later(r, n):
    s_pick(r, n)
    on(r, "main")
    git(r, "rm", "-q", f"{n}a.txt")
    git(r, "commit", "-q", "-m", "rm")
    on(r, n)


def s_old_base_other(r, n):
    main_write(r, f"k-{n}.txt", "v1\n", "main")
    br(r, n)
    write(r, f"k-{n}.txt", "v2\n")
    main_write(r, f"k-{n}.txt", "v2-other\n", n)
    main_write(r, f"k-{n}.txt", "v3\n", n)


def s_old_base_held(r, n):
    main_write(r, f"k-{n}.txt", "v1\n", "main")
    br(r, n)
    write(r, f"k-{n}.txt", "v2\n")
    main_write(r, f"k-{n}.txt", "v2\n", n)
    main_write(r, f"k-{n}.txt", "v3\n", n)


def s_squash_changed_again(r, n):
    s_squash3(r, n)
    main_write(r, f"{n}0.txt", "later\n", n)


def s_deletion_both(r, n):
    s_delete_only(r, n)
    on(r, "main")
    git(r, "rm", "-q", f"keep-{n}.txt")
    git(r, "commit", "-q", "-m", "rm")
    on(r, n)


def s_parked_merged(r, n):
    s_merge(r, n)
    empty(r, PARK)


def s_unparked_merged(r, n):
    s_merge(r, n)
    empty(r, PARK)
    empty(r, UNPARK)


def s_parked_unmerged(r, n):
    br(r, n)
    write(r, f"{n}.txt", "x\n")
    empty(r, PARK)


def s_work_above_park(r, n):
    s_parked_merged(r, n)
    write(r, f"{n}-more.txt", "m\n")


def s_plain_unpark_merged(r, n):
    s_merge(r, n)
    empty(r, "Unpark branch")


def s_plain_empty_ff(r, n):
    s_ff(r, n)
    empty(r, "note")


def s_many_empty(r, n):
    s_merge(r, n)
    empty(r, "Unpark branch")
    empty(r, "x\n\nParked-Reason: w\nParked-By: t\n")
    empty(r, UNPARK)


def s_pick_empty(r, n):
    br(r, n)
    write(r, f"{n}a.txt", "a\n")
    write(r, f"{n}b.txt", "b\n")
    empty(r, "Unpark branch")
    on(r, "main")
    write(r, f"u-{n}.txt", "u\n")
    git(r, "cherry-pick", f"{n}~2", f"{n}~1")
    on(r, n)


def s_squash_empty(r, n):
    br(r, n)
    write(r, f"{n}a.txt", "a\n")
    write(r, f"{n}b.txt", "b\n")
    land(r, n, "squash")
    empty(r, UNPARK)


def s_modified_merge(r, n, marker="Unpark branch"):
    br(r, n)
    write(r, f"{n}a.txt", "a1\n")
    write(r, f"{n}b.txt", "b1\n")
    write(r, f"{n}a.txt", "a2\n")
    on(r, "main")
    (r / f"{n}a.txt").write_text("a2\n")
    (r / f"{n}b.txt").write_text("b1\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "reworked")
    on(r, n)
    empty(r, marker)


def s_modified_merge_writer(r, n):
    s_modified_merge(r, n, UNPARK)


def s_empty_mid_unmerged(r, n):
    br(r, n)
    write(r, f"{n}a.txt", "a\n")
    empty(r, "Unpark branch")
    write(r, f"{n}b.txt", "b\n")


def s_empty_mid_merged_then_work(r, n):
    s_merge(r, n)
    empty(r, "Unpark branch")
    write(r, f"{n}-more.txt", "m\n")


# adversarial
def a_content_named_unpark(r, n):
    s_merge(r, n)
    write(r, f"{n}-x.txt", "x\n", UNPARK)


def a_content_named_park(r, n):
    s_ff(r, n)
    write(r, f"{n}-x.txt", "x\n", PARK)


def a_content_named_plain_unpark(r, n):
    s_merge(r, n)
    write(r, f"{n}-x.txt", "x\n", "Unpark branch")


def a_change_revert_empty(r, n):
    br(r, n)
    write(r, f"{n}.txt", "w\n")
    git(r, "revert", "--no-edit", "HEAD")
    empty(r, "Unpark branch")


def a_empty_over_unmerged(r, n):
    s_merge(r, n)
    write(r, f"{n}-l.txt", "l\n")
    empty(r, "Unpark branch")


def a_ours_merge(r, n):
    br(r, f"{n}-side")
    write(r, f"{n}-side.txt", "s\n")
    br(r, n, "main")
    write(r, f"{n}.txt", "x\n")
    land(r, n, "merge")
    git(r, "merge", "-q", "-s", "ours", "-m", "Unpark branch", f"{n}-side")
    git(r, "branch", "-q", "-D", f"{n}-side")


def a_ours_merge_writer_msg(r, n):
    br(r, f"{n}-side")
    write(r, f"{n}-side.txt", "s\n")
    br(r, n, "main")
    write(r, f"{n}.txt", "x\n")
    land(r, n, "merge")
    tip = git(r, "rev-parse", "HEAD")
    side = git(r, "rev-parse", f"{n}-side")
    commit_on(r, n, UNPARK, [tip, side], git(r, "rev-parse", "HEAD^{tree}"))
    on(r, n)
    git(r, "branch", "-q", "-D", f"{n}-side")


def a_one_byte(r, n):
    br(r, n)
    write(r, f"{n}.txt", "value = 1\n")
    main_write(r, f"{n}.txt", "value = 2\n", n)
    empty(r, "Unpark branch")


def a_one_byte_writer(r, n):
    br(r, n)
    write(r, f"{n}.txt", "value = 1\n")
    main_write(r, f"{n}.txt", "value = 2\n", n)
    empty(r, UNPARK)


def a_root_named_unpark(r, n):
    br(r, f"{n}-s")
    write(r, f"{n}-root.txt", "r\n")
    tree = git(r, "rev-parse", "HEAD^{tree}")
    on(r, "main")
    git(r, "branch", "-q", "-D", f"{n}-s")
    commit_on(r, n, "Unpark branch", [], tree)


def a_empty_over_other(r, n):
    br(r, f"{n}-o")
    write(r, f"{n}-o.txt", "o\n")
    br(r, n, f"{n}-o")
    empty(r, "Unpark branch")
    git(r, "branch", "-q", "-D", f"{n}-o")


def a_revert_main_empty(r, n):
    main_write(r, f"m-{n}.txt", "m\n", "main")
    br(r, n)
    git(r, "revert", "--no-edit", "HEAD")
    empty(r, UNPARK)


def a_empty_forged_tree(r, n):
    """Writer message, tree of an unmerged scratch commit, parent = merged tip."""
    s_merge(r, n)
    br(r, f"{n}-s", n)
    write(r, f"{n}-f.txt", "f\n")
    tree = git(r, "rev-parse", "HEAD^{tree}")
    on(r, "main")
    parent = git(r, "rev-parse", n)
    commit_on(r, n, UNPARK, [parent], tree)
    git(r, "branch", "-q", "-D", f"{n}-s")


def a_mode_only_then_empty(r, n):
    s_chmod(r, n)
    empty(r, "Unpark branch")


def a_rename_then_empty(r, n):
    s_rename(r, n)
    empty(r, UNPARK)


# --- round 2 (the loosening review): whitespace-only picks, orphans, replace refs, grafts.
def _ws_pick(r, n, top):
    br(r, n)
    write(r, f"{n}.py", "def f():\n    return  1  \n", "fix f")
    if top is not None:
        empty(r, top)
    main_write(r, f"{n}.py", "def f():\n    return 1\n", n)


def r2_ws_pick_bare(r, n):
    """Control: patch-ids ignore whitespace, an older weakness of patch-equivalence."""
    _ws_pick(r, n, None)


def r2_ws_pick_empty(r, n):
    _ws_pick(r, n, "Unpark branch")


def r2_ws_pick_writer_park(r, n):
    """The park writer's own marker over a whitespace-only pick."""
    _ws_pick(r, n, PARK)


def _orphan_ws(r, n, top):
    git(r, "checkout", "-q", "--orphan", n)
    git(r, "rm", "-q", "-rf", ".")
    write(r, "base.txt", "base  \n", "orphan root")
    if top is not None:
        empty(r, top)


def r2_orphan_ws_bare(r, n):
    """Control: no merge base, a whitespace twin of main's file."""
    _orphan_ws(r, n, None)


def r2_orphan_ws_empty(r, n):
    _orphan_ws(r, n, "note")


def _replace_content(r, n, message):
    br(r, n)
    write(r, f"{n}-secret.txt", "only here\n", "add secret")
    content = git(r, "rev-parse", "HEAD")
    parent = git(r, "rev-parse", "HEAD~1")
    fake = git(
        r, "commit-tree", git(r, "rev-parse", f"{parent}^{{tree}}"), "-p", parent, "-m", message
    )
    git(r, "replace", content, fake)


def r2_replace_content_any_msg(r, n):
    _replace_content(r, n, "note")


def r2_replace_content_park_msg(r, n):
    _replace_content(r, n, PARK)


def r2_replace_main_tip(r, n):
    """The default's tip replaced by a merge that appears to take the branch."""
    br(r, n)
    write(r, f"{n}-secret.txt", "only here\n", "add secret")
    content = git(r, "rev-parse", "HEAD")
    main_write(r, f"later-{n}.txt", "l\n", n)
    tip = git(r, "rev-parse", "main")
    fake = git(
        r, "commit-tree", git(r, "rev-parse", "main^{tree}"), "-p", tip, "-p", content, "-m", "m"
    )
    git(r, "replace", tip, fake)


def r2_graft_main_tip(r, n):
    """A legacy info/grafts entry giving the default's tip the branch as a parent."""
    br(r, n)
    write(r, f"{n}-secret.txt", "only here\n", "add secret")
    content = git(r, "rev-parse", "HEAD")
    main_write(r, f"later-{n}.txt", "l\n", n)
    tip = git(r, "rev-parse", "main")
    parent = git(r, "rev-parse", "main~1")
    grafts = Path(git(r, "rev-parse", "--absolute-git-dir")) / "info" / "grafts"
    grafts.parent.mkdir(parents=True, exist_ok=True)
    grafts.write_text(f"{tip} {parent} {content}\n", encoding="utf-8")


SHAPES: list[tuple[str, Callable[[Path, str], None]]] = [
    ("Y", s_ff),
    ("Y", s_merge),
    ("Y", s_squash3),
    ("Y", s_pick),
    ("N", s_one_extra),
    ("E", s_pure_empty),
    ("E", s_pure_empty_main_empty),
    ("E", s_pure_writer_park),
    ("N", s_delete_only),
    ("N", s_delete_only_empty),
    ("N", s_revert_older),
    ("N", s_revert_older_empty),
    ("N", s_rename),
    ("N", s_copy),
    ("N", s_chmod),
    ("Y", s_main_reverted_later),
    ("N", s_old_base_other),
    ("Y", s_old_base_held),
    ("Y", s_squash_changed_again),
    ("Y", s_deletion_both),
    ("Y", s_parked_merged),
    ("Y", s_unparked_merged),
    ("N", s_parked_unmerged),
    ("N", s_work_above_park),
    ("Y", s_plain_unpark_merged),
    ("Y", s_plain_empty_ff),
    ("Y", s_many_empty),
    ("Y", s_pick_empty),
    ("Y", s_squash_empty),
    ("Y", s_modified_merge),
    ("Y", s_modified_merge_writer),
    ("N", s_empty_mid_unmerged),
    ("N", s_empty_mid_merged_then_work),
    ("N", a_content_named_unpark),
    ("N", a_content_named_park),
    ("N", a_content_named_plain_unpark),
    ("N", a_change_revert_empty),
    ("N", a_empty_over_unmerged),
    ("N", a_ours_merge),
    ("N", a_ours_merge_writer_msg),
    ("N", a_one_byte),
    ("N", a_one_byte_writer),
    ("N", a_root_named_unpark),
    ("N", a_empty_over_other),
    ("N", a_revert_main_empty),
    ("N", a_empty_forged_tree),
    ("N", a_mode_only_then_empty),
    ("N", a_rename_then_empty),
    ("N", r2_ws_pick_bare),
    ("N", r2_ws_pick_empty),
    ("N", r2_ws_pick_writer_park),
    ("N", r2_orphan_ws_bare),
    ("N", r2_orphan_ws_empty),
    ("N", r2_replace_content_any_msg),
    ("N", r2_replace_content_park_msg),
    ("N", r2_replace_main_tip),
    ("N", r2_graft_main_tip),
]


def _fresh(root: Path) -> Path:
    bare = root / "remote.git"
    git(root, "init", "-q", "--bare", "-b", "main", str(bare))
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "base.txt", "base\n", "base")
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    return repo


def _decide(repo: Path, n: str) -> dict[str, str]:
    from claude_code_hooks_daemon.config.models import BranchesConfig
    from claude_code_hooks_daemon.core.remote_branch_proof import prove_remote_merged
    from claude_code_hooks_daemon.daemon.branch_safety import classify_branch
    from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import _remote_delete_note

    cfg = BranchesConfig(default="main")
    remote = prove_remote_merged(repo, "origin", [n], "main", cfg)
    guard = _remote_delete_note(f"git push origin --delete {n}", repo, cfg)
    full = classify_branch(repo, n)
    fast = classify_branch(repo, n, content_tier=False)
    return {
        "remote": remote.evidence.get(n, "DENY") if n in remote.tips else "DENY",
        "guard": "ALLOW" if guard is None else "DENY",
        "local": (full.tier or "DENY") if full.is_safe else "DENY",
        "local-hook": (fast.tier or "DENY") if fast.is_safe else "DENY",
    }


def run(workdir: Path, out: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, object]] = {}
    for label, build in SHAPES:
        root = Path(tempfile.mkdtemp(dir=workdir))
        try:
            repo = _fresh(root)
            n = build.__name__.replace("_", "-")
            build(repo, n)
            git(repo, "push", "-q", "-f", "origin", f"refs/heads/{n}:refs/heads/{n}")
            git(repo, "checkout", "-q", "main")
            git(repo, "push", "-q", "-f", "origin", "main")
            git(repo, "fetch", "-q", "--prune", "origin")
            results[n] = {"label": label, **_decide(repo, n)}
        finally:
            shutil.rmtree(root)
    out.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _allow(value: object) -> bool:
    return value != "DENY"


def compare(before_path: Path, after_path: Path) -> int:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    flips: dict[str, list[str]] = {"DENY->ALLOW": [], "ALLOW->DENY": []}
    bad = 0
    decisions = 0
    for n, old in before.items():
        new = after[n]
        for proof in PROOFS:
            decisions += 1
            if _allow(old[proof]) == _allow(new[proof]):
                continue
            kind = "DENY->ALLOW" if _allow(new[proof]) else "ALLOW->DENY"
            flips[kind].append(f"{old['label']} {n} {proof}: {old[proof]} -> {new[proof]}")
        for proof in PROOFS:
            if old["label"] == "N" and _allow(new[proof]):
                bad += 1
                print(
                    f"ALLOW ON CONTENT NOT IN DEFAULT: {n} {proof} "
                    f"(before {old[proof]}, after {new[proof]})"
                )
    print(f"shapes={len(before)} decisions={decisions}")
    for kind, rows in flips.items():
        print(f"{kind}: {len(rows)}")
        for row in rows:
            print(f"  {row}")
    n_flips = sum(1 for row in flips["DENY->ALLOW"] if row.startswith("N "))
    print(f"DENY->ALLOW on N (content not in default): {n_flips}")
    print(f"ALLOW on N after: {bad}")
    return 1 if n_flips or bad else 0


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit(compare(Path(sys.argv[2]), Path(sys.argv[3])))
