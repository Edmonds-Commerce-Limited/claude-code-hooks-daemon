# Callout: the supervisor top hat is green only for a session the supervisor oversees

**Plan**: 00553
**Audience**: operators

The status-line `supervisor_indicator` used to turn green for every session of a project as soon as any `claude-supervise` process was visible, so a session with no supervisor claimed an auto-compact safety net it did not have (reported as issue #140). A supervisor now counts for a session only when that session's id is in the environment of a process in the supervisor's own descendant tree, the same rule the supervisor applies to its own sessions. The status-file pid and the `/proc` scan are both held to it, and each session keeps its own cache. A session with no id, or whose ownership cannot be read, renders orange (a status file exists) or nothing, never green.
