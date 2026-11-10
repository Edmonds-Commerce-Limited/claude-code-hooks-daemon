# Callout: no stray `settings.json.bak-*` file when the merge changed nothing

**Plan**: 00594
**Audience**: client projects

The installer and upgrader copy `.claude/settings.json` to `.claude/settings.json.bak-<timestamp>` before merging it. When the merge then changed nothing, that backup was byte-identical to the live file yet stayed behind, showing up as an untracked path that blocked clean-tree checks and worktree removal. A backup identical to the merged result is now deleted; a merge that changes the file still keeps its backup exactly as before.
