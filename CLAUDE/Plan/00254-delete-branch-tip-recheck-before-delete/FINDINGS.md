# Plan 00254 — reproductions

Every block below is real output. The finding arrived from a peer review session;
none of it was accepted until it had been executed here independently.

## The seam

`delete_branches` classifies everything, then writes ONE bundle for the batch
(`branch_safety.py:613`), then deletes in a loop (`:617`). No `rev-parse` between
them. `write_recovery_bundle` is therefore both the widest part of the window and
the natural interposition point for a test — a peer committing "during the bundle"
is the realistic case, not a contrived one.

## 1. As shipped: silent loss on `merged-not-in-head`

Branch merged into `main`, no upstream, HEAD standing on a branch that does not
contain it. A peer commits to it via a second worktree while the bundle is written.

```
tier       : merged-not-in-head
argv       : ('branch', '--delete', '--force')
peer added : b4e2e8e on 'done'
refused    : False | deleted: ('done',)
branches   : ['main', 'work']
bundle head: 34703400ceba8f5d9820255d2ec7f458a357c66b refs/heads/done
recoverable: ['base.txt', 'd.txt']
peer-only.txt recoverable? : False
```

Exit 0, "deleted", a bundle path printed as the recovery route — and the peer's
file exists nowhere. Nothing in the output gives the reader anything to notice.

## 2. The counterfactual: the same race under the safe delete

Identical scenario, argv forced back to `-d` (what this branch got before Plan
00253 added its tier).

```
tier       : merged-not-in-head
argv       : ('branch', '--delete')
peer added : b4e2e8e on 'done'
refused    : True | deleted: ()
blocker    : done: git refused the delete (proven merged-not-in-head) — error: The branch 'done' is not fully merged.
branches   : ['done', 'main', 'work']
```

So `-d` was the concurrency guard — by accident. It was never chosen for that; it
was chosen because git's own merged check is battle-tested. This is the
observation Plan 00253 recorded when reproducing the reviewer's unverified TOCTOU
claim, now shown to have a consequence.

## 3. The exposure predates Plan 00253

Same race on `merged-unpushed`, which has used the force delete since Plan 00249:

```
tier merged-unpushed | argv ('branch', '--delete', '--force')
refused False | deleted ('feat',)
branch still present: False
peer-only.txt recoverable? False
```

This is what makes it a latent defect across four tiers rather than a regression.
Plan 00253 removed accidental cover from one case; it did not create the gap.

## 4. `update-ref -d <ref> <sha>` is a real compare-and-swap

```
stale sha delete  : rc=1 error: cannot lock ref 'refs/heads/victim': is at 207b332b… but expected a196c3…
victim survived   : True
current sha delete: rc=0
victim gone       : True
```

## 5. …but it is the wrong trade here (Decision 1)

The claim under test was that the force tiers give up nothing by switching, since
git checks nothing there. Executed, that premise is false.

**A branch checked out in another worktree:**

```
force delete  : rc=1 "error: Cannot delete branch 'wtForce' checked out at '/tmp/…/wtForce'"
wtForce survived: True
update-ref CAS: rc=0 ''
wtCas survived  : False
its worktree still on disk: True
worktree HEAD now: 'HEAD'
```

The force delete refuses. `update-ref -d` deletes and leaves the peer's worktree
with a dangling `HEAD`.

**This needs stating more precisely than a first pass did.** `classify_branch`
already refuses a branch checked out in a linked worktree — `REFUSAL_WORKTREE`,
`branch_safety.py:427` — so in the ordinary path the switch would lose nothing;
the daemon never reaches the delete. The loss is confined to the RACING case,
which is this plan's whole subject: a peer that checks out the branch AFTER
classification moves no tip, so no tip re-check can see it, while git's
delete-time check still refuses. Through the real engine, with the checkout
interposed during the bundle write:

```
--- force-delete (as shipped)
    classified tier      : merged-not-in-head  (tip unchanged: True)
    refused True | deleted ()
    'done' still a branch: True
    peer worktree HEAD   : 'done'
```

A note on what that run does NOT show. The same probe tried to emulate the CAS at
the delete site by swapping `delete_argv_for_tier`, and that emulation is invalid:
`delete_branches` appends the branch name to the argv, so it issued
`update-ref -d refs/heads/done <sha> done`, which git rejects as malformed. Its
"refused" result is an argv error, not the behaviour under test, and is not
evidence of anything. The CAS behaviour is established by the direct-git run
above, where the worktree-checked-out branch was deleted with rc=0.

**Config cleanup:**

```
before : branch.viaForce.remote/merge + branch.viaCas.remote/merge
after  : branch.viaCas.remote origin, branch.viaCas.merge refs/heads/viaCas
```

The force delete removes the branch's upstream config; `update-ref -d` leaves it.
Those two keys are precisely what `_safe_delete_reference` reads to pick a tier, so
a later branch of the same name would inherit a dead upstream and classify
differently.

## What this changes about the fix

Keep git's delete, re-read the tip. The window shrinks from a whole bundle pack to
one git invocation, and no existing guard is given up. The residual window is real
and must be stated rather than implied away.

Method note, since it is the second time in this review chain: the fixture that
reproduces a bug is not automatically the fixture that explains it. Here the
peer's own suggested remedy reproduced its intended behaviour perfectly and was
still the wrong change, because the harness only exercised the property it was
built to exercise.
