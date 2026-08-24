#!/usr/bin/env bash
# Probe for Plan 00266: can a daemon-side command hook compose a prompt that a
# native agent hook then fetches by tool_use_id?
#
# Reads the PreToolUse payload on stdin, derives the per-event key that BOTH
# sides can see, and writes a per-event instruction file. The agent hook is
# told to read the file named after the tool_use_id in its own input, so no
# coordination channel is needed between the two hooks.
set -euo pipefail

PROMPT_DIR="${CLAUDE_PROJECT_DIR:-/workspace}/untracked/prompts"
mkdir -p "$PROMPT_DIR"

payload_file="$(mktemp)"
trap 'rm -f "$payload_file"' EXIT
cat > "$payload_file"

python3 - "$PROMPT_DIR" "$payload_file" <<'PYEOF'
import json
import pathlib
import sys

prompt_dir = pathlib.Path(sys.argv[1])
data = json.loads(pathlib.Path(sys.argv[2]).read_text())

tool_use_id = data.get("tool_use_id")
if not tool_use_id:
    sys.exit(0)

command = data.get("tool_input", {}).get("command", "")

# The daemon side is where the real work would happen: run the existing regex,
# consult the verdict log, read config. Here it just decides which instruction
# the model should be given for THIS event -- which is the point being tested.
if "ECHD_DYNAMIC" in command:
    verdict = (
        'Respond with exactly: {"ok": false, '
        '"reason": "DYNAMIC_PROMPT_FETCHED_BY_TOOL_USE_ID"}'
    )
else:
    verdict = 'Respond with exactly: {"ok": true}'

(prompt_dir / f"{tool_use_id}.txt").write_text(verdict + "\n")
PYEOF
