# Plan 00620: rulings on the open questions Q1 to Q8

Supporting document for [PLAN.md](PLAN.md). It answers the questions in
[FEASIBILITY.md](FEASIBILITY.md) section 7 and fixes the shape of the verdict mechanism.

**Provenance.** Every ruling here was settled by a fable sub-agent under the owner's
delegation, 2026-11-19. None of it is the owner's own words. A later owner message
overturns any ruling, and the builder then follows the owner.

## 1. The governing rule, and what it forces

The project's guard rule is that a branch is deleted only when a machine check proves the
removal, and that an agent's own assertion that a branch is valueless never counts.
FEASIBILITY section 3 classes the judgement "no value" as trusted: nothing recomputes it. A
sub-agent's verdict is still an agent's assertion, however independent the sub-agent is.

So the verdict cannot be the fact that unlocks the delete. The ruling is:

**The delete is unlocked by a fact the guard recomputes at delete time: the branch's whole
unproven work is held in a verified recovery bundle, so the removal loses nothing. The
verdict is a second, necessary condition. Neither is sufficient alone.**

- A verified bundle with no verdict does not unlock: the caller's wish to remove is not a
  reason, and a bundle alone would make this route a general exit for any unproven branch.
- A verdict with no verified bundle does not unlock: that would be a delete resting on an
  agent's judgement.

This is the peer's bundle-and-reason idea (journal, 2026-11-18 16:12) joined to the owner's
Opus verdict, with one change: the reason is never typed by the requesting agent. The
reviewer writes the reasons, per commit and per path.

### What the guard recomputes at delete time (machine checks)

1. The branch tip equals the verdict's tip and the classification's tip, and the existing
   pre-delete re-check (`tip_moved_since_proof`) passes.
2. The inventory (cherry-unique commits and content-unique paths) recomputed from git equals
   the verdict's inventory line for line.
3. The bundle file exists at the path the guard itself wrote, `git bundle verify` passes
   against this repository, the bundle lists the tip sha, and the file's sha256 equals the
   one the guard recorded when it wrote it.
4. The verdict is unexpired, unconsumed and overall `no-value`, and every superseded-by
   citation resolves on the default branch.
5. The ledger line for this removal is written before git is asked to delete.

### What stays trusted (the residue, stated plainly)

- The judgement "no value" itself.
- The hook event chain behind the verdict record (Q1).
- That the bundle file is kept after the delete. The guard proves it exists and verifies at
  the moment of the delete; it does not police the file afterwards.

The consequence of a wrong or forged verdict is therefore bounded: the work leaves the
branch list and sits in a verified bundle, restorable by the one command the delete prints.
It is not destroyed.

### Amendment to the plan's Non-Goals

PLAN.md listed "no archive refs, tags or bundles". The Overview attributes the rejection of
refs and tags to the owner; it does not attribute bundles to the owner. Refs and tags stay
excluded. Bundles are admitted by this ruling, because a bundle is a file, not a ref: it
does not appear in any branch or tag listing, does not count in any pool, and cannot be
mistaken for live work. This is the ruling most likely to be overturned, so it is listed in
section 4.

## 2. Answers

### Q1. Threat model: accepted, with the bundle as the reason it is safe to accept

"Motivated but not forging" is accepted as the boundary. Reasons:

- It is the boundary every other guard in the repository already uses (FEASIBILITY
  section 1, point 5).
- The only real alternative is a different trust domain, which means a human, which defeats
  the plan's purpose.
- Because of section 1, the forgeable part (the verdict chain) gates a recoverable action
  only. A forger gains a branch moved into a bundle, with a tracked ledger line naming it.

The design keeps every "daemon-observed" binding of FEASIBILITY section 3. Each makes
forgery a deliberate, ordered, evidence-leaving act.

### Q2. A fresh-context sub-agent of the owning session is acceptable

A sub-agent always shares its dispatcher's session id, so "a different session" would need a
human or a scheduler outside the session, which again defeats the purpose. The rule the
guard enforces is:

- the reviewer's identity (`<session_id>:<agent_id>`) is not the branch's creator and is not
  in its touch record;
- the reviewer is not a fork and was not resumed (one human-text user turn);
- the reviewer's prompt is the daemon-composed one, byte for byte.

PLAN.md's goal is reworded to match: "never by the agent that created or touched the
branch" replaces "never by the session that owns the branch".

### Q3. "At least Opus" is the whole model rule

No "at least the caller's family" rule and no "different family" rule. The caller's family is
no better proven than the reviewer's, and a different-family rule would have nothing to
select from. Independence comes from the fresh context, the fixed prompt, and the second
reviewer on escalation (Q5). Any assistant record below Opus, or any downgrade record, voids
the verdict, as FEASIBILITY already proposes.

### Q4. Delete now; no condemned state

With the bundle, the work is recoverable for as long as the file is kept, which does not
depend on `gc.pruneExpire`. The condemned state would add a fourth pool state to protect
against a loss that the bundle already prevents. Two consequences:

- The `gc.pruneExpire` check and ledger field proposed in FEASIBILITY section 5 are dropped.
- The route refuses outright when the bundle cannot be written or does not verify. There is
  no fallback to a bundle-less delete.

### Q5. Retry and escalation

- A `keep` verdict is final for that tip. No new request is accepted for the same tip.
- After the tip changes, one further request is accepted for that branch name, and it needs
  two agreeing `no-value` verdicts from two distinct reviewer agents. The daemon-composed
  prompt for those reviews quotes the earlier keep verdict's reasons. Moving the tip is the
  cheapest way to shop for a second opinion, so the second opinion is made harder to win.
- After a second `keep` on a branch name, the route is closed for that name. The work is
  merged, parked, or left to the owner.
- Disagreement between two reviewers counts as `keep`.
- The keep history is keyed on the work, not only on the name. A request whose inventory
  shares any unique commit with the inventory of an earlier `keep` verdict is a re-review of
  that verdict whatever the branch is called, so renaming a branch earns no fresh start.
- A review that ends with no verdict (an unparseable reply, a damaged transcript, a killed
  or still-running reviewer, a withdrawn verdict) is an unresolved attempt on that work,
  keyed like the keep history. Each one adds a required reviewer, and a second one closes
  the route for that work until a human decides (`MAX_UNRESOLVED_REVIEWS = 2`, a constant,
  not config). Garbling or killing an unwelcome review is otherwise a free second opinion
  (review finding F-BYPS F2; DESIGN.md section 6).
- A verdict is valid for 24 hours from issue (`branches.reject.verdict_lifetime_hours`).
- Rate, per repository, counted from the ledger over a rolling 7 days
  (`branches.reject.window_days`): above 3 removals (`two_reviewer_after`) every further
  removal needs two agreeing reviewers; above 10 (`refuse_after`) the route refuses and the
  digest says so. The numbers are defaults in config, not constants.

### Q6. Existing archive exits: a follow-up plan, not this plan

Ruled in principle: once the verdict route has shipped, `recovery_copy_advisory` should stop
advising `refs/archive/<name>` and should point at the reject route instead, since the
bundle does the same job without a ref. The `remote-held` tier stays: it is a true
nothing-is-lost proof and other flows rest on it. Plan 00619 is complete and is not
reopened. Task 3.1 in PLAN.md files the follow-up plan after this one merges, so the advice
is never changed to name a route that does not exist yet.

### Q7. Local only in this plan; the remote delete stays refused

A valid verdict unlocks the local `delete-branch` only. R-GIT-PUSH-DELETE-REMOTE is not
changed by this plan. Reasons:

- A remote branch is the one copy that survives the loss of a clone. The bundle this plan
  writes lives in one clone's ignored directory. Trading the first for the second is a real
  loss of durability, and the "nothing is lost" proof of section 1 would not honestly hold.
- A remote delete is beyond any local recovery, which is why that rule exists.

This leaves the peer's five parked remote branches unsolved by this plan. The remote unlock
is a second stage with one precondition that is not an engineering choice: a durable home
for the bundle that outlives the clone. That choice is the owner's (section 4). Until it is
made, a rejected branch that has a remote copy keeps the copy.

### Q8. Ledger location and who commits it

- Ledger: `.claude/branch-removals.jsonl`, tracked, append-only, one JSON object per line
  (`branches.reject.ledger_path`). JSON lines rather than markdown so that the single-use
  check and the rate count read it without parsing prose.
- Fields: branch, tip, default sha, verdict id(s), reviewer agent id(s) and model(s), reply
  sha256(s), bundle path, bundle sha256, restore command, time.
- Writer: `delete-branch` appends the line to the checkout it runs in, before the delete.
- Committer: the agent that ran the delete, in its next commit. An uncommitted ledger line
  leaves the worktree dirty, which the existing stop guard already refuses to leave behind.
- Bundles: `untracked/branch-rejects/<branch-slug>-<tip12>.bundle`
  (`branches.reject.bundle_dir`), ignored by git, never committed. The directory is always
  resolved against the repository's main checkout, never against the worktree the command
  runs in: a linked worktree is removed when its work is done, and a bundle written inside
  one would go with it. The guard refuses when it cannot resolve the main checkout.
- This plan ships no command that deletes a bundle.
- The builder must check how an append-only tracked file behaves when two branches each
  append a line and then merge, and choose the fix (a union merge attribute is the first
  candidate) with a test.

## 3. Shape of the mechanism

One command family, `hooks-daemon branch-reject`, plus the existing `delete-branch`:

1. `branch-reject request <branch>`: classifies the branch (must be `unproven`, not
   protected, not checked out in a worktree, no `keep` verdict on this tip, route not
   refused by the rate rule), records `{nonce, branch, tip, default sha, inventory}` in
   daemon state, and prints the reviewer type and the exact dispatch prompt. It accepts no
   free text from the caller. There is no `--reason`.
2. The reviewer: a tracked, read-only agent definition, `model: opus`, with the
   keep-by-default rules of PLAN.md. FEASIBILITY section 6 items 2 to 4 stand as drafted
   (dispatch gate on PreToolUse `Agent`, record on SubagentStop).
3. `delete-branch <name>`: for an `unproven` branch with a valid verdict, writes the bundle,
   runs the section 1 checks, appends the ledger line, then deletes through the existing
   path. It reports under a new tier name, `rejected-bundled`. It prints two restore lines:
   the fetch from the bundle, and `git branch <name> <sha>`.
4. `clean_sweep`, `cleanup_after_merge` and `delete_if_merged` never consult verdicts.
5. `branch-reject digest`: lists every removal and every keep verdict since the last digest;
   the session-start branch report names the count of undigested removals.

The DESIGN.md of Task 1.2 is no longer a document awaiting approval. It is the builder's
elaboration of these rulings (record schema, review prompt text, state layout), and it is
judged by the independent loosening review and the adversarial pass, which stay mandatory.

## 4. What is still the owner's

Nothing here blocks the first build slice. These are the points worth the owner's glance:

1. **Bundles are admitted** (section 1), against the letter of the original Non-Goals.
2. **The threat model is accepted** (Q1) on the argument that the forgeable part gates a
   recoverable action only.
3. **Remote deletes stay refused** (Q7). Unlocking them needs a durable off-clone home for
   bundles, which only the owner can choose.
4. **Bundle retention.** This plan never deletes a bundle. Whether and when they may be
   pruned is left open.

## 5. First buildable slice

Slice 1 changes no delete behaviour:

1. Live probe, journalled: a background `Agent` dispatch's PostToolUse carries `agentId`, and
   the agent's `meta.json` `tool_use_id` matches the parent call. If either fails, stop and
   journal it; the nonce binding of FEASIBILITY section 3 must be redesigned first.
2. DESIGN.md: verdict record schema, ledger line schema, review prompt text, state layout.
3. A pure module (no handler, no CLI wiring) with tests written first, covering: the
   inventory computation; verdict validation (wrong tip, expired, consumed, inventory
   mismatch, unresolved citation, reviewer below Opus, downgraded reviewer, fork, resumed,
   reviewer is creator or toucher); bundle write and verify (missing file, failed verify,
   tip absent from the bundle, sha256 mismatch, and a run from a linked worktree writing
   into the main checkout); keep history across a rename; ledger append and the rate count.
4. Red tests for the delete path, committed red as the security rules of this plan require:
   forged, reused, stale, wrong-tip and self-written verdicts, and a valid verdict with no
   verified bundle.

Slice 2 wires `delete-branch` and the `branch-reject` commands and turns the red tests
green. Slice 3 is the digest. Slice 4 is the loosening review, the adversarial forge
attempt, QA and the release note.
