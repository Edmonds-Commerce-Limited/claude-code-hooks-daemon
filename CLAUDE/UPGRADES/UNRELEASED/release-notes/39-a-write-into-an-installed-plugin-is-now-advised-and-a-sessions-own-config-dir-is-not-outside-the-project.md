# Callout: a write into an installed plugin is now advised, and a session's own config dir counts as in bounds

**Plan**: 00468
**Audience**: everyone

Findings G10 and G16. This affects everyone who uses Claude Code plugins, and
anyone who runs a session with a different Claude config dir from the
daemon's.

**New advisory, `installed_plugin_edit_advisor`** (on by default, never
blocks). Claude Code keeps each installed plugin's files under
`plugins/cache/` and each marketplace clone under `plugins/marketplaces/`, in
its config dir. It replaces those files on the next plugin update, so an edit
there is lost without a word. The edit also changes a prompt, hook or script
from what its author published. A Write, Edit, NotebookEdit or plain Bash
write to one of those files now draws an advisory. It names each file and says
to fork the plugin or send the change upstream. A plugin's own data store,
`plugins/data/`, is not covered. To turn it off, set
`handlers.pre_tool_use.installed_plugin_edit_advisor.enabled: false`.

**`project_containment` now reads the session's config dir from the payload.**
The daemon worked out Claude Code's config dir from its own environment
(`$CLAUDE_CONFIG_DIR`, else `~/.claude`). A session started with a different
`CLAUDE_CONFIG_DIR` from the daemon's had writes to its own config dir denied
as outside the project. The dir is now also taken from the hook payload's
`transcript_path` (`<config dir>/projects/<project>/<session>.jsonl`), and
writes under either dir are allowed. The new advisory checks both dirs too.
