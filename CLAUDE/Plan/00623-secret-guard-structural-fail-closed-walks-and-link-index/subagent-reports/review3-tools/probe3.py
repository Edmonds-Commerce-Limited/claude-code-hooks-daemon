"""Review-3 probe: the two loosenings (plain /proc/self file, git commit/status after a computed cd).

Usage:
  PYTHONPATH=<tree>/src python probe3.py judge <tag> <out.json>   # guard verdicts on corpus3.txt
  python probe3.py oracle <out.json> [...]                         # run every ALLOWED command in bash

Fixture fx3/: outside/ is a git repo holding the dummy protected file (committed, then modified,
so a diff prints it) plus an innocently named link m -> it. proj/ holds sub/dl -> outside,
flink -> outside/<protected>, olink -> outside. The oracle runs each command from proj with
OLDPWD=proj/sub/dl, so `cd -` lands in the foreign repo. Output holding DUMMY is an escape.
The protected file name is assembled so this file never spells one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

R = Path(__file__).resolve().parent
# Fixtures (nested .git, a protected-named dummy) live in gitignored scratch, never here.
FX = R.parents[4] / "untracked" / "scratch" / "p623rev3"
PROT = "id_" + "rsa"
HOOK = "#!/bin/sh\ncat m\n"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(cwd: Path, *args: str) -> None:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(cwd), **GIT_ENV}
    subprocess.run(["git", "-C", str(cwd), *args], check=True, env=env, capture_output=True)


def build(base: Path) -> Path:
    if base.exists():
        shutil.rmtree(base)
    outside = base / "outside"
    outside.mkdir(parents=True)
    (outside / PROT).write_bytes(b"DUMMY-OLD\n")
    _git(outside, "init", "-q")
    _git(outside, "add", PROT)
    _git(outside, "commit", "-q", "-m", "init")
    (outside / PROT).write_bytes(b"DUMMY-NEW\n")
    (outside / "m").symlink_to(outside / PROT)
    (base / "home").mkdir()
    root = base / "proj"
    (root / "sub").mkdir(parents=True)
    (root / "r.md").write_bytes(b"hello\n")
    (root / "sub" / "dl").symlink_to(outside)
    (root / "flink").symlink_to(outside / PROT)
    (root / "olink").symlink_to(outside)
    _git(root, "init", "-q")
    # ORACLE_VARIANT: ambient git state the guard cannot see after `cd -`.
    variant = os.environ.get("ORACLE_VARIANT", "")
    if variant == "repo-config":
        _git(outside, "config", "commit.verbose", "true")
    elif variant == "home-config":
        (base / "home" / ".gitconfig").write_text("[commit]\n\tverbose = true\n")
    elif variant == "hook":
        hook = outside / ".git" / "hooks" / "pre-commit"
        hook.write_text(HOOK)
        hook.chmod(0o755)
    return root


def judge(tag: str, out: str) -> None:
    commands = [
        c.replace("<NL>", "\n")
        for c in (R / "corpus3.txt").read_text().splitlines()
        if c and not c.startswith("#")
    ]
    base = FX / f"fx3-{tag}"
    root = build(base)
    os.chdir(str(root) if os.environ.get("DAEMON_CWD_ROOT") else "/")
    os.environ["HOME"] = str(base / "home")
    from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as gm
    from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
        SecretFileGuardHandler,
    )
    from claude_code_hooks_daemon.utils import path_exclusion, protected_file_index
    from claude_code_hooks_daemon.utils import secret_file_matching as sfm

    try:
        from claude_code_hooks_daemon.utils import link_index
    except ImportError:
        link_index = None
    patches = [
        patch.object(gm, "resolve_project_root", return_value=str(root)),
        patch.object(path_exclusion, "resolve_project_root", return_value=str(root)),
    ]
    if hasattr(sfm, "resolve_project_root"):
        patches.append(patch.object(sfm, "resolve_project_root", return_value=str(root)))
    for p in patches:
        p.start()
    handler = SecretFileGuardHandler()
    index = protected_file_index.build_index(root, tuple(handler._patterns()))
    protected_file_index.remember(index)
    if link_index is not None:
        link_index.reset_link_indexes()
    if link_index is not None and not os.environ.get("COLD"):
        link_index.prewarm(str(root))
        link_index.wait_for_link_index(60.0)
    rows = []
    for c in commands:
        hi = {"tool_name": "Bash", "tool_input": {"command": c}, "cwd": str(root)}
        try:
            d = handler.handle(hi).decision.value if handler.matches(hi) else "allow(nomatch)"
        except Exception as exc:  # report, never hide
            d = f"error:{type(exc).__name__}:{exc}"
        rows.append({"command": c, "decision": d})
    Path(out).write_text(json.dumps(rows, indent=1))
    print(tag, "deny", sum(r["decision"] == "deny" for r in rows), "of", len(rows))


def oracle(names: list[str]) -> None:
    allowed: dict[str, list[str]] = {}
    for name in names:
        for row in json.loads(Path(name).read_text()):
            if not row["decision"].startswith("deny"):
                allowed.setdefault(row["command"], []).append(Path(name).stem)
    for command, where in allowed.items():
        work = FX / "oracle-fx3"
        root = build(work)
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(work / "home"),
            "OLDPWD": str(root / "sub" / "dl"),
            **GIT_ENV,
        }
        try:
            proc = subprocess.run(
                ["bash", "-c", command],
                cwd=root,
                env=env,
                capture_output=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
                text=True,
                errors="replace",
            )
            output = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            output = "TIMEOUT"
        flag = "ESCAPE " if "DUMMY" in output else "ok     "
        print(flag + json.dumps(command) + f" | allowed in {where}")


if __name__ == "__main__":
    if sys.argv[1] == "judge":
        judge(sys.argv[2], sys.argv[3])
    else:
        oracle(sys.argv[2:])
