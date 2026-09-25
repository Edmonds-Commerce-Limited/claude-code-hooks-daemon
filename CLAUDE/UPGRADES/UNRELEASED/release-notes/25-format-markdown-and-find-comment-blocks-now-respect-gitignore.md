# Callout: `format-markdown` and `find-comment-blocks` now respect `.gitignore`

**Plan**: 00468
**Audience**: client projects

Plan 00468 Task 3.1 (P3). The same defect class as 00466 N9, in two more walkers. `format-markdown`
(`daemon/cli.py`, also driven by `housekeeping`'s mutating step) and
`find-comment-blocks` walked the filesystem for markdown/comments with no
regard for `.gitignore`. Installing a Claude Code plugin vendors files into a
gitignored config tree (e.g. `.claude/ccy/plugins/`), so a local
`format-markdown` run against an installed plugin reported 173 files as
needing reformatting — content nobody in the project wrote and nobody can
act on.

Both now filter through the same `git_visible_paths` /
`git_visible_ancestor_dirs` helpers 00466 N9 introduced (the latter is now a
shared helper in `utils/git_repo.py` rather than private to `docs_qa/corpus.py`).
The pre-existing pruning of nested git repos and `daemon.exclude_paths` is
unchanged. A project with no `.git` at all is unaffected — the filter is a
no-op outside a git repository.

`format-markdown` also now refuses to run against an explicitly named path
that is itself gitignored, rather than rewriting it: `format-markdown .claude/ccy/plugins` prints an error and exits non-zero instead of touching
vendored plugin content.

Both walkers also skip Claude Code's config directory (`$CLAUDE_CONFIG_DIR`,
else `~/.claude`) whenever it sits inside the project, whether or not git
would show it. This covers a tracked config dir, a project that is not a git
repository, and a home that is a symlink into the project, or the reverse.
A config dir that contains the whole project excludes nothing.
`markdown_organization` uses the same test.
