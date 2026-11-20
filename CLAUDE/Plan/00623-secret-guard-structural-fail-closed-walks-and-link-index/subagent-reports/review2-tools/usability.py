"""Task 4: build the branch's link index over /workspace in-process and time real commands."""

import os
import time
from unittest.mock import patch

from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as gm
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import link_index, path_exclusion
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

ROOT = "/workspace"
print("BUILD_DIRECTORY_CAP", getattr(link_index, "BUILD_DIRECTORY_CAP", None))
os.chdir("/")
with (
    patch.object(gm, "resolve_project_root", return_value=ROOT),
    patch.object(sfm, "resolve_project_root", return_value=ROOT),
    patch.object(path_exclusion, "resolve_project_root", return_value=ROOT),
):
    start = time.monotonic()
    link_index.prewarm(ROOT)
    link_index.wait_for_link_index(600.0)
    print(f"build {time.monotonic() - start:.1f}s")
    scan = link_index.link_scan_for(ROOT)
    if scan is None:
        print("index: none (not built)")
    else:
        v = scan.value
        print("complete", scan.complete, "reason", getattr(scan, "reason", None))
        print("holding", len(v.holding), "dirlinks", len(v.directory_links), "links", len(v.links))
    full = sfm.scan_project_links(ROOT)
    print("scan complete", full.complete, "named", full.value.named is not None)
    handler = SecretFileGuardHandler()
    for command in [
        "cd ~/x && cat f",
        'cd "$(git rev-parse --show-toplevel)" && cat f',
        'cd "$(mktemp -d)" && ls',
        "cat README.md",
        "cd src && ls",
        'cd "$D" && cat CLAUDE.md',
    ]:
        hook = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": ROOT}
        t = time.monotonic()
        decision = handler.handle(hook).decision.value if handler.matches(hook) else "allow"
        print(f"{decision:6} {time.monotonic() - t:.2f}s | {command}")
