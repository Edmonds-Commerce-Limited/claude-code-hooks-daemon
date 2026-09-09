# Callout: contract-status answers "has upstream hooks.md moved?" in one command

**Plan**: 00327
**Audience**: operators

`hooks-daemon contract-status` raw-fetches the Claude Code hooks documentation
the vendored contract was audited against, compares its sha256 with
`contracts/claude-code-hooks/META.json`, and reports the verdict as the exit
code (0 unchanged, 1 changed, 2 error); `--save` keeps the raw body for the
audit that follows. The manual `curl` + `sha256sum` opening of the refresh
procedure can go — the extraction steps that follow a CHANGED verdict remain a
verified manual audit by design, and the vendored contract now records the
2.1.263 text.
