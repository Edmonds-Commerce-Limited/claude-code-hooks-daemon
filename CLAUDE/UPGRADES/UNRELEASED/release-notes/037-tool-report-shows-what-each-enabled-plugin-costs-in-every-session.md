# Callout: tool-report shows what each enabled plugin costs in every session

**Plan**: 00468
**Audience**: everyone

Every enabled Claude Code plugin puts its skills' and agents' names and
descriptions into context in every session, whether or not you use it.
`hooks-daemon tool-report` now has a section with one row per enabled
plugin. Each row gives the listed skills (and any hidden with
`disable-model-invocation`), the agents, the characters measured from the
plugin's files, and a token estimate. MCP tool schemas are not measured.
The JSON output carries the same figures under `plugins`.

`lsp_noise_checker` also works out where the Claude config dir is instead of
assuming ccy's `.claude/ccy`. When that directory is inside your project, it
asks your language server to exclude its `plugins/` tree, whatever the
directory is called.
