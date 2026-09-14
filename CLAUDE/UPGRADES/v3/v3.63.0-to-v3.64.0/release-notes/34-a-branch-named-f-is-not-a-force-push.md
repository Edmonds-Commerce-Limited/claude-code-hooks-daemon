# Callout: a branch name containing `-f-` is no longer read as a force push

**Plan**: 00382
**Audience**: operators
**Issue**: #37

`destructive_git` denied an ordinary push when the branch name happened to
contain `-f-`. `git push origin feature/lane-f-adoption` was blocked as
R-GIT-PUSH-FORCE with no force flag and no `+` refspec anywhere in it, and
renaming the branch let the identical command through.

The force markers now each have to START a whitespace-delimited argument, which
is the rule the `+`-refspec marker has always followed. A branch name carrying
`-f-`, or ending in `-f`, is an ordinary push and is allowed. `--follow-tags`
and `--no-force-with-lease` are likewise not force pushes — the second negates
the lease rather than requesting one.

**The same investigation found the opposite defect, and it is the more serious
half.** Git groups short options, so `git push -uf origin main` is a force
push — and it was NOT blocked in any release before this one, because the
literal `-f` never appears in `-uf`. `-fu` and `-nf` slipped through for the
same reason. All are now denied, along with any other single-dash cluster
carrying an `f`; a cluster without one (`-nq`, `-u`) is untouched.

**If you relied on the old behaviour to push with `-uf`, it will now stop.**
That was never intended to work. Use `git push -u` and ask a human to run the
force, as with every other force push.

No configuration changes. If you previously renamed a branch to get a push
through, the original name works again.
