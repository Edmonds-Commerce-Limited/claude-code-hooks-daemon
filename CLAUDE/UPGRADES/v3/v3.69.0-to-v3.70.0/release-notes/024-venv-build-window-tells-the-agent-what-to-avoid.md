# Callout: while a fresh checkout's venv builds, the hook message says what to avoid

**Plan**: 00488
**Audience**: operators

On a fresh checkout the daemon cannot answer until the background venv build finishes, so no guard judges tool calls meanwhile. That stays as it was: PreToolUse keeps allowing, since denying would wedge the agent (even `sleep` would be denied) and waiting cannot fit inside the hook timeout. What changes is the message the agent sees on every hook event during the build: it now adds a line telling it to keep to reads and ordinary edits, and not to commit, push, delete branches or touch protected files until the status line clears. The failed, refused and disabled states do not carry the line. No configuration change is needed.
