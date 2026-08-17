# Bug report: `hooks-daemon delete-branch` crashes on a merged branch that is ahead of its own remote-tracking ref

**Component**: `claude-code-hooks-daemon` — `delete-branch` CLI
**Version**: 3.53.1 (upstream commit `51846428`, "Release v3.53.1")
**Severity**: medium — no data loss, but the command is unusable for a real and common branch shape,
fails with a raw traceback, and leaves an orphaned 1.9 MB artefact behind.
**Reproduced**: yes, in the reporting client repo (identifier withheld — it is not needed to act on this).

## Summary

For a branch classified `merged`, `delete_branches()` deliberately delegates to the safe
`git branch --delete` so that git re-checks the ancestry independently. That design is right. But
`git branch -d` refuses on a **second, independent** condition the daemon's classifier does not
model: the branch must also be merged into **its own upstream remote-tracking ref**, not just into
the protected ref. A branch that is fully contained in `main` while sitting one commit ahead of
`origin/<itself>` therefore hits a refusal the daemon never anticipated — and because `_git()`
defaults to `check=True` and the CLI catches only `ValueError`, the `CalledProcessError` escapes as
an unhandled traceback.

The result is a direct contradiction between the two halves of the tool: `--dry-run` reports
**"nothing can be lost"**, and the real run then crashes without deleting anything.

## Reproduction

Branch state — merged into `main` via PR, but one local commit ahead of its own remote ref:

```
$ git branch -vv
  feature/poc-sales-completion  f289086 [origin/feature/poc-sales-completion: ahead 1] Merge pull request #17 ...
* feature/sandbox-account-onboarding b74d08c [origin/feature/sandbox-account-onboarding] ...
  main                          70c9327 [origin/main] ...

$ git merge-base --is-ancestor feature/poc-sales-completion HEAD && echo MERGED
MERGED
```

`git branch -d` refuses first, and its warning states the exact condition:

```
$ git branch -d feature/poc-sales-completion
warning: not deleting branch 'feature/poc-sales-completion' that is not yet merged to
         'refs/remotes/origin/feature/poc-sales-completion', even though it is merged to HEAD.
error: The branch 'feature/poc-sales-completion' is not fully merged.
```

That refusal is what `CLAUDE.md` points at `delete-branch` to resolve, so the dry run is next:

```
$ .claude/hooks-daemon/bin/hooks-daemon delete-branch --dry-run feature/poc-sales-completion
  feature/poc-sales-completion: merged — tip is an ancestor of the protected ref — nothing can be lost

Dry run — nothing was deleted.
```

The real run crashes:

```
$ .claude/hooks-daemon/bin/hooks-daemon delete-branch feature/poc-sales-completion
Traceback (most recent call last):
  ...
  File ".../daemon/cli.py", line 4875, in main
    return cast("int", args.func(args))
  File ".../daemon/cli.py", line 2943, in cmd_delete_branch
    report = delete_branches(
  File ".../daemon/branch_safety.py", line 424, in delete_branches
    _git(repo, *delete_argv_for_tier(classification.tier), classification.name)
  File ".../daemon/branch_safety.py", line 160, in _git
    return subprocess.run(  # nosec B603 B607 - trusted system tool, list form
subprocess.CalledProcessError: Command '['git', '-C', '/workspace', 'branch', '--delete',
'feature/poc-sales-completion']' returned non-zero exit status 1.
```

The branch still exists afterwards.

## Root cause

`classify_branch()` proves `merged` by ancestry against the protected ref
(`DEFAULT_PROTECTED_REF = "main"`, `branch_safety.py:72`, tier assigned at `:286`).

`delete_argv_for_tier()` (`:82-98`) then chooses the safe delete for that tier, with an explicit and
well-argued docstring: *"Git then re-runs its own merged-ancestry check independently of ours, so a
bug in `classify_branch` cannot cause a silent loss."*

The gap is that `git branch -d` does **not** run only "our" check. Its refusal message above states
the condition outright — it checks against `refs/remotes/origin/<name>`, and says so *"even though it
is merged to HEAD"*, i.e. it knows the protected-ref check passes and refuses anyway. (This matches
the documented `-d` rule that a branch must be fully merged into its upstream if it has one, and into
`HEAD` otherwise; the manual could not be re-read on this machine, so the quoted runtime warning is
the evidence relied on here — it is the more direct of the two in any case.) The two checks are
therefore not the same predicate, and one can fail while the other passes. The daemon models
"content is recoverable from `main`"; git additionally enforces "nothing is unpushed". A branch whose
merge commit was never pushed satisfies the first and fails the second.

Two code-level consequences:

1. **`branch_safety.py:424`** — `_git()` defaults to `check=True` (`:153`), so git's refusal raises.
   The call site does not catch it.
2. **`cli.py:2942-2955`** — the `try` around `delete_branches()` catches `ValueError` only, so the
   `CalledProcessError` propagates to `main()` and prints a traceback.

## Secondary findings from the same trace

**The documented all-or-nothing contract can be violated.** `delete_branches()` promises
*"delete all of them or none"* (`:354-357`), but the deletion is a plain loop over classifications
(`:422-424`) with no rollback. Given `["already-merged-ok", "merged-but-ahead-of-upstream"]`, git
deletes the first and raises on the second, leaving a partial deletion — precisely the state the
docstring says is unacceptable. Single-branch invocations hide this.

**An orphaned recovery bundle is left behind.** `bundle_path` defaults to
`untracked/deleted-branches.bundle` (`cli.py:4696-4700`) and the bundle is written *before* the loop
(`:418-420`). The crash left a real one:

```
$ ls -la untracked/deleted-branches.bundle
-rw------- 1 root root 1980726 Aug 17 13:10 untracked/deleted-branches.bundle

$ git bundle list-heads untracked/deleted-branches.bundle
f289086e01c1bf8f8494c36e115c912bf1b7a4d0 refs/heads/feature/poc-sales-completion
```

1.9 MB of recovery data for a branch that was never deleted. Anyone finding this file later would
reasonably read it as evidence the branch is gone.

## Suggested fixes

Roughly in order of value:

1. **Handle git's refusal instead of crashing.** Call the delete with `check=False`, and on a
   non-zero exit report git's own stderr with the tier that was proven. The message practically
   writes itself, because git names the condition: *"merged to `main`, but git refuses `-d` while the
   branch is ahead of `origin/<name>`."*
2. **Model the upstream condition in `classify_branch()`,** so `--dry-run` and the real run agree.
   This is the substantive fix: a dry run that says "nothing can be lost" must not be followed by a
   failure. If the tier stays `merged` but git will refuse, the dry run should say so and name the
   remedy.
3. **Decide the intended behaviour for this shape and state it.** The branch's content *is* in
   `main`, so the daemon's own safety argument is satisfied and using `--force` here would lose
   nothing. But `delete_argv_for_tier()`'s docstring deliberately reserves the force flag for tiers
   where ancestry is severed, and silently escalating a `merged` branch to `--force` would erode the
   guarantee the tier exists to provide. A cleaner resolution is a distinct tier — "merged, but
   unpushed relative to its own remote" — that keeps the proof explicit rather than widening
   `merged`.
4. **Make the loop match the all-or-nothing docstring,** or soften the docstring. Pre-flighting each
   delete (`git branch --merged` / a dry classification pass) before mutating anything would keep the
   promise.
5. **Do not leave the bundle on a failed run** — remove it, or name it by outcome, so an orphaned
   bundle cannot be mistaken for a completed deletion.

## Impact on this repo

Low. The branch (`feature/poc-sales-completion`, merged via PR #17) is harmless clutter and was left
in place; `git branch -D` is blocked by the `destructive_git` handler and was not attempted, which is
correct. The two artefacts a reader may notice are that branch and the orphaned bundle above.
