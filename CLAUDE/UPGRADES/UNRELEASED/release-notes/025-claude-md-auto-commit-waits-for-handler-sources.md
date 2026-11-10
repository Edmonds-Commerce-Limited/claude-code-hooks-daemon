# Callout: the CLAUDE.md auto-commit waits for uncommitted plugin and project handler files

**Plan**: 00591
**Audience**: client projects

(GitHub #172.) On restart the daemon regenerates the CLAUDE.md handler block and commits it. If a `plugins:` or `project_handlers:` handler file was still untracked or modified, that commit recorded a rule row no committed code declared. The commit is now held back while any such source file is untracked or modified: CLAUDE.md stays dirty and one log line names the file. Commit the handler and the next restart commits the block. Library handlers, sources outside the repository, and projects with no plugin or project handlers behave as before.
