# Callout: lsp_enforcement no longer reads `semgrep <name>` as a grep for a symbol

**Plan**: none (bug fix)
**Audience**: all projects

A Bash command that merely named a tool ending in `grep` or `rg` followed by an identifier-shaped argument, for example `llm_qa.py ... semgrep shell_check`, could be denied as a symbol search, even when the command's only real grep searched a text file. The pattern is now taken only from a `grep` or `rg` that starts a word, so an argument list is no longer mistaken for a search.
