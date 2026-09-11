# Callout: `worktree-reap` stops refusing worktrees over generated files

**Plan**: 00380
**Audience**: operators

`worktree-reap` refuses any worktree carrying an uncommitted path, because an
uncommitted path might be work you have not saved. That rule is unchanged. What
has changed is what counts as one.

`git status` runs INSIDE each worktree, so it applies that worktree's
`.gitignore` — and a worktree's `.gitignore` is whatever its pinned commit
carried. A generated path added to the ignore list afterwards is invisible
there, so the daemon's own output reads as your unsaved work and the worktree
is refused for ever. In this repository five worktrees accumulated that way,
four of them held by a single generated advisory file, and every one of the
five had zero commits unmerged to the base branch the whole time.

An UNTRACKED path that the MAIN checkout would ignore now no longer counts as
work. Main's ignore rules are the current authority on what is generated, and
consulting them also covers generated paths added later.

**Only untracked paths are ever dropped.** `git check-ignore` answers about a
path and cannot see that the same path is tracked and modified inside the
worktree, so a staged, modified or deleted tracked file is never filtered — it
still refuses, even if its path matches an ignore rule. A failed ignore query
drops nothing, on the same principle that an unreadable `git status` is never
read as a clean one.

**The refusal message has been rewritten, and the old one was misleading.** It
said "remove it by hand" and the summary said "N need a human". Neither was
true: no rule blocks `git worktree remove --force`, so an agent reading the
refusal can inspect and remove the worktree itself. That phrasing caused this
repository's five stale worktrees to be handed to a human repeatedly instead of
being cleaned up. The message now says removal is not blocked, names the
command, and gives a checkable test for "accounted for" — \`git log --oneline

<base>..<branch>` empty, and every listed path either generated output or a
change already on the base — while still explaining why the command will not
make that judgement for you: a rebased commit that already landed looks exactly
like one that did not.

**If you keep generated files under `.claude/`**, check they are gitignored.
This release also untracks `.claude/reports/`, which is daemon-generated output
that had reached version control by accident.
