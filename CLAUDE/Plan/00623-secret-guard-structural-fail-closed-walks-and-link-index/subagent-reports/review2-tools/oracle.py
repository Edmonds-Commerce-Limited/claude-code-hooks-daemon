"""Run every command the branch ALLOWED (any mode) in real bash on a fresh fixture copy.

For each, D is set to each of several project directories; output holding DUMMY is an escape.
Usage: python oracle.py out-a.json [out-b.json ...]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

R = Path(__file__).resolve().parent
DS = ["", "w19", "w19/zz", "w00", "w19/.bin", "src"]


def main() -> None:
    allowed: dict[str, list[str]] = {}
    for name in sys.argv[1:]:
        for row in json.loads((R / name).read_text()):
            if row["decision"].startswith("allow"):
                allowed.setdefault(row["command"], []).append(name)
    for command, where in allowed.items():
        hits = []
        for d in DS:
            work = R / "oracle-fx"
            if work.exists():
                shutil.rmtree(work)
            shutil.copytree(R / "fx", work, symlinks=True)
            root = work / "proj"
            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": str(work / "home"),
                "TMPDIR": str(work / "outside"),
                "D": str(root / d) if d else str(root),
            }
            # The fixture links are absolute into fx/: re-point them into the copy.
            for link in root.rglob("*"):
                if link.is_symlink():
                    target = str(Path(link.readlink())).replace(str(R / "fx"), str(work))
                    link.unlink()
                    link.symlink_to(target)
            for prefix in ("", "shopt -s extglob\n"):
                try:
                    proc = subprocess.run(
                        ["bash", "-c", prefix + command],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        timeout=5,
                        stdin=subprocess.DEVNULL,
                        text=True,
                        errors="replace",
                    )
                    output = proc.stdout + proc.stderr
                except subprocess.TimeoutExpired:
                    output = "TIMEOUT"
                if "DUMMY" in output:
                    hits.append((d or ".") + ("+extglob" if prefix else ""))
        print(("ESCAPE " if hits else "ok     ") + f"{command} | D={hits} | allowed in {where}")


if __name__ == "__main__":
    main()
