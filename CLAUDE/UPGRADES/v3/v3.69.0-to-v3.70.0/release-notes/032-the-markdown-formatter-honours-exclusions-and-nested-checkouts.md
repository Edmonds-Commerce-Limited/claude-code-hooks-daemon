# Callout: the markdown formatter honours `exclude_paths` and leaves nested git checkouts alone, and its advisory no longer understates what it changed

**Plan**: 00509
**Audience**: everyone

The PostToolUse handler `markdown_table_formatter` formats the whole of every `.md` file it is given, and that does not change. What changes is its reach and its report. It now honours its own `handlers.post_tool_use.markdown_table_formatter.options.exclude_paths` and the project-wide `daemon.exclude_paths`, so generated or hand-formatted markdown can be opted out. A `.md` file inside a nested, separately versioned git checkout below the project root (a vendored clone or a submodule) is no longer rewritten, as `format-markdown` already did since Plan 00429; a linked worktree of the same repository is still formatted. The advisory used to say "aligned table pipes" even when bullet markers, blank lines or escaping had changed too: it now names the known changes only when they account for the whole diff, and otherwise says "Reformatted the whole file (mdformat)" (reported as issue #79).
