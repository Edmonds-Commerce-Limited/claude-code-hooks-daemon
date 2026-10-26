## 19:29 · decision · —

Finding for Task 3.2: the daemon emits no status-line message reading "settings.json is not valid JSON".

Searched src/, scripts/, init.sh and the stubs for that wording and for variants (invalid JSON, unparseable settings, malformed settings). The only status-line code touching settings.json is handlers/status_line/settings_reader.py, which reads the USER's ~/.claude/settings.json for display values and returns empty on a bad file without any message. The text the owner saw is therefore most likely Claude Code's own report of the project's .claude/settings.json, which the daemon cannot edit.

What the daemon controls and now does: the init.sh parse guard (which the status-line stub carries too) names `.claude/hooks-daemon/bin/hooks-daemon repair-install`, and the verb reports settings.json as OK or BROKEN, with the by-hand instruction for a conflicted file. TROUBLESHOOTING lists the settings.json symptom beside the stub symptoms. I did not invent a new daemon status-line segment for a message the daemon does not own (YAGNI); if the owner wants one, it is a separate task.
