# Callout: `docs_qa` and `doc_truth` now respect `.gitignore`

**Plan**: 00466 (N9)
**Audience**: client projects

The `docs_qa` corpus (`module-doc-budget`, `source-tree-markdown`) and the
`doc_truth` QA script walked the filesystem for markdown with no regard for
`.gitignore`. Installing a Claude Code plugin vendors its spec markdown into
a gitignored config tree (e.g. `.claude/ccy/plugins/`), and both checks
reported it as this project's own documentation — a local full QA run could
fail on files nobody wrote and nobody can act on, even though CI never saw
the problem (a fresh checkout has no such tree).

Both now filter file discovery through `git`'s own view of the tree: tracked
files, plus untracked files no `.gitignore` rule excludes. A project with no
`.git` at all is unaffected — the filter is a no-op outside a git repository,
matching the pre-existing behaviour exactly.

If your project vendors a config directory Claude Code writes into and
expects one specific gitignored file to still be checked (as this daemon
does for its own `.claude/ccy/CLAUDE.md`), it needs to be named explicitly;
see `docs_qa/corpus.py`'s `_GITIGNORED_MARKDOWN_INCLUDES` for the pattern.
