"""Review-2 probe: name-rule (>cap link-holding dirs) corpus on main / branch, cap patched / lifted.

Usage: PYTHONPATH=<tree>/src:<tree> python probe.py <tag> <cap|lifted> <cold|built> <out.json>
Fixture: fx/proj with 20 holding dirs (w00..w19/.bin/tool -> r.md), w19/zz/late -> outside dummy,
w19/zz/dl -> outside dir. The protected file name is assembled so this file never spells one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

R = Path("/workspace/untracked/scratch/00623-review2")
PROT = "id_" + "rsa"


def build(base: Path) -> Path:
    if base.exists():
        shutil.rmtree(base)
    outside = base / "outside"
    outside.mkdir(parents=True)
    (outside / PROT).write_bytes(b"DUMMY\n")
    (base / "home").mkdir()
    root = base / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_bytes(b"x\n")
    (root / "r.md").write_bytes(b"hello\n")
    for n in range(20):
        h = root / f"w{n:02d}" / ".bin"
        h.mkdir(parents=True)
        (h / "tool").symlink_to(root / "r.md")
    deep = root / "w19" / "zz"
    deep.mkdir()
    (deep / "late").symlink_to(outside / PROT)
    (deep / "dl").symlink_to(outside)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    return root


def main() -> None:
    tag, capmode, idx, out = sys.argv[1:5]
    out = str(Path(out).resolve())
    commands = [c for c in (R / "commands.txt").read_text().splitlines() if c and not c.startswith("#")]
    base = R / "fx"
    root = build(base)
    os.chdir("/")
    os.environ["TMPDIR"] = str(base / "outside")
    os.environ["HOME"] = str(base / "home")
    from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as gm
    from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import SecretFileGuardHandler
    from claude_code_hooks_daemon.utils import path_exclusion, protected_file_index
    from claude_code_hooks_daemon.utils import secret_file_matching as sfm

    try:
        from claude_code_hooks_daemon.utils import link_index
    except ImportError:
        link_index = None
    if capmode == "cap" and hasattr(sfm, "LINK_SCAN_DIRECTORY_CAP"):
        sfm.LINK_SCAN_DIRECTORY_CAP = 8
    patches = [patch.object(gm, "resolve_project_root", return_value=str(root)),
               patch.object(path_exclusion, "resolve_project_root", return_value=str(root))]
    if hasattr(sfm, "resolve_project_root"):
        patches.append(patch.object(sfm, "resolve_project_root", return_value=str(root)))
    for p in patches:
        p.start()
    handler = SecretFileGuardHandler()
    index = protected_file_index.build_index(root, tuple(handler._patterns()))
    protected_file_index.remember(index)
    if link_index is not None:
        link_index.reset_link_indexes()
        if idx == "built":
            link_index.prewarm(str(root))
            link_index.wait_for_link_index(60.0)
            assert link_index.link_scan_for(str(root)) is not None
    rows = []
    for c in commands:
        hi = {"tool_name": "Bash", "tool_input": {"command": c}, "cwd": str(root)}
        try:
            d = handler.handle(hi).decision.value if handler.matches(hi) else "allow(nomatch)"
        except Exception as exc:  # report, never hide
            d = f"error:{type(exc).__name__}:{exc}"
        rows.append({"command": c, "decision": d})
    Path(out).write_text(json.dumps(rows, indent=1))
    print(tag, capmode, idx, "deny", sum(r["decision"] == "deny" for r in rows), "of", len(rows))


if __name__ == "__main__":
    main()
