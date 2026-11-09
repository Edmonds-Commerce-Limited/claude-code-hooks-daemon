# Callout: lsp_enforcement no longer judges a grep that filters stdin, or `git grep`

**Plan**: 00588
**Audience**: client projects

(GitHub #169.) `lsp_enforcement` (R-LSP-SYMBOL-LOOKUP) treated `printf ... | grep -v some_name` as a project-wide symbol lookup, because a grep with no file target was read as "the whole project", and it picked up the `grep` inside `git grep -lF some_name HEAD -- dir` the same way. Neither searches a file a language server indexes, so neither is denied or advised any more: a grep or rg fed by a pipe, a `<` redirect or a `<<<` here-string and naming no file, and every `git grep` (with or without a ref or pathspec, `git -C dir grep` included). A `grep -r` stage still searches the working directory and stays judged. `grep -rn some_name src/`, `rg some_name`, a grep with no target as the first command, the Grep tool, and which patterns look like identifiers are unchanged. A command mixing a skipped grep with a real one is judged as before.
