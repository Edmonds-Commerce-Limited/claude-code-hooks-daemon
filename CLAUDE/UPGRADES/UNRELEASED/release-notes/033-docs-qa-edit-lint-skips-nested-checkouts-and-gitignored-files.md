# Callout: the docs QA edit-time lint skips nested git checkouts and gitignored files

**Plan**: 00510
**Audience**: everyone

The write-time docs QA lint (`docs_qa_edit`) and `docs-qa --lint` now leave out two kinds of file they used to judge. A `CLAUDE.md` inside a nested, separately versioned git checkout below the project root (a vendored clone, a submodule, or a linked worktree of another repository) is no longer held to this project's module-doc budget, and neither is a file the project's `.gitignore` excludes, which is what the sweep already did. `docs-qa --lint` now refuses such a file as "not a documentation file". This repository's own linked worktrees stay in scope, and so does any file git cannot judge (the project is not a git repository, or git is unavailable). The cost is one `git check-ignore` for the one path per documentation edit, about 2 ms (reported as issue #80).
