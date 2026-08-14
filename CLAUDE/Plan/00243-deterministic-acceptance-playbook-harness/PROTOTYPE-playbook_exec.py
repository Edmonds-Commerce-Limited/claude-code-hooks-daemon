"""Execute the EXECUTABLE subset of the acceptance playbook deterministically.

Sends each playbook test's command to the PRODUCTION hook wrapper
(.claude/hooks/pre-tool-use) as a subprocess with the event JSON on stdin,
exactly as tests/acceptance/test_stop_hook_hard_block.py does for the Stop
wrappers. This exercises the real bash forwarder -> socket -> daemon ->
handler-chain path.

The command string is only ever DATA here: it is placed in tool_input.command
and handed to the hook wrapper, which returns a decision. No shell ever runs
it. That is what makes it safe to probe destructive commands.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path("/workspace")
PLAYBOOK = REPO / "untracked" / "playbook.md"
WRAPPER = REPO / ".claude" / "hooks" / "pre-tool-use"

BLOCK_RE = re.compile(r"^#### Test (\d+): (.+?)$", re.M)
TYPE_RE = re.compile(r"^\*\*Type\*\*:\s*(.+?)\s*$", re.M)
DECISION_RE = re.compile(r"^\*\*Expected Decision\*\*:\s*(\w+)", re.M)
CMD_RE = re.compile(r"\*\*Command\*\*:\s*\n```bash\n(.*?)\n```", re.S)

SKIP_MARKERS = ("VERIFIED_BY_LOAD", "OBSERVABLE")


def parse_blocks(text: str) -> list[dict]:
    marks = list(BLOCK_RE.finditer(text))
    out: list[dict] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.start() : end]
        tm, dm, cm = TYPE_RE.search(body), DECISION_RE.search(body), CMD_RE.search(body)
        if not (tm and dm and cm):
            continue
        out.append(
            {
                "n": m.group(1),
                "title": m.group(2).strip(),
                "type": tm.group(1).strip(),
                "expected": dm.group(1).strip().lower(),
                "command": cm.group(1).strip(),
            }
        )
    return out


FILE_PATH_RE = re.compile(r"file_path\s*=\s*'([^']+)'|file_path\s*=\s*\"([^\"]+)\"")
CONTENT_RE = re.compile(
    r"content\s*=\s*'(.*?)'\s*(?:[,)]|\s*$)|content\s*=\s*\"(.*?)\"\s*(?:[,)]|\s*$)", re.S
)
NEW_STRING_RE = re.compile(r"new_string\s*=\s*'(.*?)'\s*[,)]", re.S)


def classify(command: str) -> tuple[str, dict]:
    """Decide which TOOL a playbook command really exercises.

    The playbook renders Write/Edit tests as a tool call or as prose, not as
    a shell command. Sending those as Bash tests nothing — the handler under
    test inspects file content, not a command string.
    """
    fp = FILE_PATH_RE.search(command)
    if not fp:
        return "Bash", {"command": command}
    path = fp.group(1) or fp.group(2)

    ns = NEW_STRING_RE.search(command)
    if ns or "Edit(" in command:
        body = ns.group(1) if ns else ""
        return "Edit", {
            "file_path": path,
            "old_string": "",
            "new_string": body.replace("\\n", "\n").replace("\\t", "\t"),
        }

    cm = CONTENT_RE.search(command)
    body = (cm.group(1) or cm.group(2)) if cm else ""
    return "Write", {
        "file_path": path,
        "content": body.replace("\\n", "\n").replace("\\t", "\t"),
    }


def send(command: str, session: str) -> str:
    tool_name, tool_input = classify(command)
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": session,
        "cwd": str(REPO),
    }
    proc = subprocess.run(
        ["bash", str(WRAPPER)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        cwd=str(REPO),
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        return "allow"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "unparseable"
    hso = data.get("hookSpecificOutput") or {}
    return hso.get("permissionDecision") or data.get("decision") or "allow"


def main() -> int:
    blocks = parse_blocks(PLAYBOOK.read_text(encoding="utf-8"))
    runnable = [b for b in blocks if not any(s in b["type"] for s in SKIP_MARKERS)]
    skipped = len(blocks) - len(runnable)

    mismatches: list[dict] = []
    passes = 0
    for b in runnable:
        got = send(b["command"], f"playbook-{b['n']}")
        want = "deny" if b["expected"] == "deny" else "allow"
        norm = "deny" if got == "deny" else ("allow" if got in ("allow", "ask") else got)
        if norm == want:
            passes += 1
        else:
            mismatches.append({**b, "got": got})

    print(f"playbook blocks parsed : {len(blocks)}")
    print(f"  skipped (load/observable): {skipped}")
    print(f"  executed via production wrapper: {len(runnable)}")
    print(f"  matched expected decision: {passes}")
    print(f"  MISMATCHES: {len(mismatches)}")
    print()
    for m in mismatches:
        tool, _ = classify(m["command"])
        print(f"[Test {m['n']}] {m['title']}")
        print(f"    tool={tool}  type={m['type']}  expected={m['expected']}  got={m['got']}")
        print(f"    cmd: {m['command'][:110]}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
