# Callout: `lsp_enforcement` enforces only where an enabled plugin serves the searched language

**Plan**: 00468
**Audience**: everyone

Finding P5. This affects everyone who enables `lsp_enforcement`, and anyone
who sets `ENABLE_LSP_TOOL`.

`lsp_enforcement` took `ENABLE_LSP_TOOL` as proof that the LSP tool could
answer a lookup. Claude Code keeps that tool inactive until a code
intelligence plugin for the language is installed. So a symbol search in a
language no plugin served was denied with "LSP tool available for this
lookup", and the LSP call that followed failed. For example, a `.ts` search in
a session with only a Python language server did this.

The handler now reads the enabled Claude Code plugins and the language
servers they declare. It works out the searched file type from the Grep
`glob`, `type` or `path`, or from a grep/rg command's `--include`,
`-g`/`--glob`, `-t`/`--type` and file arguments. A search that names no file
type counts as covered when any language server is enabled.
`ENABLE_LSP_TOOL` is no longer consulted.

**`no_lsp_mode` now defaults to `advisory`** (it was `block`). Where no
enabled plugin serves the searched file type, the search is allowed. The
agent is told to install a code intelligence plugin for that language. A
config that sets `no_lsp_mode: block` explicitly keeps denying, now with the
same advice. The shipped example config sets `advisory`.

The handler's relevance check, used by config review, now asks the same
question: is there an enabled plugin with a language server?
