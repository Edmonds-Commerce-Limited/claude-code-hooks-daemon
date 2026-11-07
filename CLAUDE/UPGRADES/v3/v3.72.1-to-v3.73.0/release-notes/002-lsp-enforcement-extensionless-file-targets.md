# Callout: lsp_enforcement no longer denies a grep over extensionless files no language server serves

**Plan**: 00567
**Audience**: client projects

A symbol-like `grep` that names two or more existing files with no suffix (for example `grep -n foo_bar bin/tool1 bin/tool2` over shell scripts) was denied whenever any language server was enabled, while the same search over their directory was only advised. Named files are now judged by their own suffix, and an extensionless file counts as unserved, so both forms get the same advisory. A named file with a served suffix is still enforced, including in a mixed list, and targets that cannot be judged (missing paths, a file list piped through `xargs`) keep the cautious answer that an enabled server covers the search (reported as issue #162).
