from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.handlers.pre_tool_use.project_containment import (
    ProjectContainmentHandler,
)

ROOT = Path("/repo")


def bash(cmd, cwd="/repo/sub"):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}


cases = [
    "echo hi > ../../tmp/out.txt",
    "curl https://example.com/x -o ../../../tmp/x.sh",
    "wget https://example.com/x -O ../../../tmp/x.sh",
    "mkdir -p ../../../tmp/newdir",
    "tar -cf ../../../tmp/a.tar src",
    "rsync -a src/ ../../../tmp/dest/",
    "cd /tmp && echo hi > out.txt",
    "echo hi > /tmp/../tmp/out.txt",
    "sh -c 'echo hi > /tmp/x'",
    "sh -c 'sh -c \"echo hi > /tmp/x\"'",
    'sh -c \'sh -c "sh -c \\"echo hi > /tmp/x\\""\'',
    "install -m 644 a.txt /tmp/b.txt",
    "dd if=/dev/zero of=/tmp/z.bin",
    "cp README.md /tmp/",
    "echo hi > /tmp/x.txt # comment",
    "python3 -c \"open('/tmp/x','w')\"",
    "tee /tmp/a.txt /tmp/b.txt < in.txt",
    "cat > /tmp/here.txt <<'EOF'\nbody\nEOF",
]

with patch(
    "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
    return_value=ROOT,
):
    h = ProjectContainmentHandler()
    for c in cases:
        matched = h.matches(bash(c))
        targets = h._named_targets(bash(c))
        print(f"{'DENY ' if matched else 'ALLOW'} | {c!r} -> {targets}")
