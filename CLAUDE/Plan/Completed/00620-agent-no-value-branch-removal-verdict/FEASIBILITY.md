# Plan 00620 Phase 1: Feasibility of a sub-agent no-value verdict

Supporting document for [PLAN.md](PLAN.md), Task 1.1 (what a hook can prove) and the
groundwork for Task 1.2 (the design). No guard code was changed to produce it. Every
claim cites the code it rests on; where a claim could not be checked here it says so.

## 1. The Task 1.1 answer, first

**A hook cannot PROVE a sub-agent's model or its independence against the agent that
asks for the delete.** It can make a forgery a deliberate, multi-step act that leaves
evidence, which is a different and weaker property. The plan says to report this to
the owner before designing further. This document therefore gives the evidence, a
recommended design that holds under the weaker property, and the questions the owner
must answer before Task 1.2 turns the design into an approved DESIGN.md.

Why it cannot be proven, from the code:

1. **The daemon socket accepts any same-user process.** The socket is mode 0660 and the
   daemon makes no peer check beyond stamping a pid
   (`src/claude_code_hooks_daemon/constants/permissions.py`, the `DAEMON_UMASK` comment:
   "no chown/chgrp, no SO_PEERCRED peer check"; `daemon/server.py` `_peer_pid` only
   records the pid). An agent's Bash runs as the same user, so it can pipe a JSON
   payload into `.claude/hooks/subagent-stop` (the same forwarder Claude Code runs).
2. **An unmarked payload is classified REAL.** `daemon/synthetic_traffic.py`:
   "An unmarked, unrecognised session is REAL." The synthetic marker is an honesty
   label the producer sets on itself; omitting it costs a forger nothing.
3. **The SubagentStop payload carries no model.** `contracts/claude-code-hooks/SubagentStop.json`
   lists `session_id`, `transcript_path`, `agent_id`, `agent_type`,
   `agent_transcript_path`, `last_assistant_message`, `effort`, crons and tasks. The model
   exists only inside the agent transcript file (`message.model` on each assistant record,
   read by `utils/transcript_spend.py`), and the transcript path is a payload field the
   forger chooses.
4. **Every store the daemon could consult is writable by the same user**: the agent
   transcript and its `meta.json` (under the Claude Code projects directory), the branch
   creator and touch records (`core/branch_records.py` keeps them in `git config`, so a
   `git config` call rewrites them), and any file under `untracked/`.
5. **The fences that exist are pattern guards, not boundaries.** `write_protected_paths`
   (R-WRITE-PROTECTED-PATH) and `secret_file_guard` (R-SECRET-BASH-MENTION) both match the
   path in the command text; both describe themselves as "an action guard ... it stops a
   careless action". A Python one-liner that builds the path at run time is not seen.

So the honest threat model is the one every other guard in this repository already
uses: **an agent that is motivated to finish, may rationalise, and takes the easiest
route, but does not deliberately forge daemon inputs.** Against that agent the design
below is strong: every easy route (asserting, writing a file, framing the reviewer's
brief, reusing an old verdict, deleting after the tip moved) is closed by a machine
check. Against an agent that sets out to forge, it is evidence and friction only. The
owner must accept or reject that threat model (Question Q1).

## 2. What already exists that the design can stand on

| Fact                                                                                                                                            | Where                                                                                                      |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `delete-branch` refuses `unproven`: "the caller's own assertion is not a tier"                                                                  | `daemon/branch_safety.py` `delete_branches`                                                                |
| A proof is bound to the tip sha and re-checked immediately before the delete                                                                    | `branch_safety.tip_moved_since_proof` (Plan 00254); the residual window is one git call                    |
| Every delete prints `git branch <name> <sha>` from the proved tip                                                                               | `DeletionReport.restore_commands`                                                                          |
| Three other callers of `delete_branches`: `cleanup_after_merge`, `delete_if_merged`, `clean_sweep` (the `branch-sweep --clean` bulk path)       | `core/branch_cleanup.py`                                                                                   |
| SubagentStop already writes a per-agent record from the agent transcript: spend, resolved model, `tool_use_id`, `downgraded` / `fallback_model` | `handlers/subagent_stop/subagent_cache_aggregator.py` `record`                                             |
| The agent transcript and its `meta.json` are found from `agent_id`                                                                              | `utils/transcript_tail.resolve_agent_transcript`, `read_agent_meta`                                        |
| A dispatch's model is predicted from the per-call `model`, the definition frontmatter, the env, then inheritance; a `fork` is its own source    | `utils/dispatch_tier.py` (`DispatchSource.FORK`), `utils/model_tiers.py` (`haiku < sonnet < opus < fable`) |
| PreToolUse on the `Agent` tool sees `subagent_type`, `model`, `prompt`; PostToolUse carries `tool_response.agentId`                             | `handlers/post_tool_use/budget_exhaustion_detector.py` reads `agentId`                                     |
| A resumed agent keeps its `agent_id`                                                                                                            | `handlers/subagent_stop/subagent_report_size_blocker.py` (review m2)                                       |
| Creator and touch identities are `<session_id>:<agent_id>`                                                                                      | `core/branch_records.py` `identity`                                                                        |
| Local `git branch -D` is already allowed when a remote holds the branch; an unmerged remote delete is refused                                   | R-GIT-BRANCH-FORCE-DELETE, R-GIT-PUSH-DELETE-REMOTE, `core/remote_branch_proof.py`                         |

## 3. Bindings: machine-verified, daemon-observed, or trusted

"Daemon-observed" means the daemon saw it arrive on a hook event and recorded it in its
own process at the time, so a forger must fabricate the event live and in the right order;
the content is still same-user writable. "Machine-verified" means the guard recomputes it
from git at delete time and needs no trust in any record.

| Binding                                            | Class                             | How                                                                                                                                                                                                 |
| -------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tip sha                                            | Machine-verified                  | Verdict names a sha; delete requires `rev-parse` of the branch == verdict tip == classification tip, then `tip_moved_since_proof` again before git runs                                             |
| Completeness of the inventory                      | Machine-verified                  | The guard recomputes the unique commits (`cherry_unique_shas`) and `content_unique_paths_of`; the verdict must list every one with a reason, no more and no fewer                                   |
| "Superseded by" citations on keep-by-default paths | Machine-verified (reference only) | Each cited sha must be reachable from the default and each cited path must exist there; the guard checks that the citation resolves, never that the argument is right                               |
| Expiry                                             | Machine-verified                  | Issued-at and the configured lifetime, against the daemon clock                                                                                                                                     |
| Single use                                         | Machine-verified                  | The verdict id is recorded in the ledger at delete; a second use is refused, so a branch recreated at the same sha needs a new verdict                                                              |
| Brief not framed by the caller                     | Daemon-observed                   | The daemon composes the review prompt; the PreToolUse `Agent` gate denies a reviewer dispatch whose prompt is not byte-equal to an outstanding request                                              |
| Nonce to `agent_id`                                | Daemon-observed                   | PreToolUse `Agent` (prompt carries the nonce, gives `tool_use_id`) then PostToolUse (`agentId`) then the agent's `meta.json` `tool_use_id`                                                          |
| Reviewer model at least Opus                       | Daemon-observed, then file-read   | Dispatch gate denies a predicted family below Opus; at SubagentStop every assistant record in the agent transcript must resolve to Opus or above, and `scan_transcript_tail` must find no downgrade |
| Not a fork, not resumed                            | Daemon-observed, then file-read   | Gate denies `subagent_type == fork`; transcript must hold exactly one human-text user turn (the canonical prompt)                                                                                   |
| Reviewer is not the branch's creator or a toucher  | File-read (git config)            | `identity(session, agent)` absent from `hooksDaemonCreator` / `hooksDaemonTouchedBy`                                                                                                                |
| Reviewer cannot change the branch                  | Trusted (definition)              | A fixed, tracked agent definition with no Write/Edit tools; its blob is compared to the default branch's copy at dispatch                                                                           |
| Report path                                        | Daemon-written                    | The daemon stores `last_assistant_message` itself (as `subagent_report_persistence` already does) and records the file's sha256 in the verdict; the reviewer never names a path                     |
| The judgement "no value"                           | Trusted                           | Nothing machine-checks value. This is the residue the owner is accepting                                                                                                                            |

## 4. Failure modes

| Mode                                                               | Closed by                                                                                                                                                        | Residual                                                                                   |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Agent asserts no value itself                                      | No assertion path; `unproven` still refused without a verdict record the daemon wrote                                                                            | None at the honest threat model                                                            |
| Agent writes a verdict file                                        | Records are written only by the SubagentStop handler, keyed by a daemon-held nonce; a file with no matching outstanding request and observed dispatch is ignored | A same-user forger can fake the whole event chain (section 1)                              |
| Verdict laundering through the brief ("this is obsolete, confirm") | Daemon-composed prompt, exact-match dispatch gate, no caller text                                                                                                | The reviewer still reads the branch, its commit messages and plans, which the caller wrote |
| Laundering by retry (dispatch until one reviewer agrees)           | Every request and every verdict, keep or remove, is ledgered; a keep verdict on a tip blocks new requests for that tip; the digest shows the count               | Owner sets the retry policy (Q5)                                                           |
| Laundering by resume ("reconsider")                                | Exactly one human-text user turn in the transcript; resume changes that                                                                                          | None beyond section 1                                                                      |
| Tip moves after the verdict                                        | Tip binding, then the existing pre-delete re-check                                                                                                               | One git call, as today                                                                     |
| Branch recreated at the same sha                                   | Single-use verdict id                                                                                                                                            | None                                                                                       |
| Same-model self-review (correlated blind spots)                    | Fresh context (no fork, no resume), fixed prompt, at least Opus, and a second independent reviewer on escalation                                                 | Independence of judgement is not provable; see Q3                                          |
| Reviewer shares the session of the branch owner                    | Every sub-agent shares its dispatcher's `session_id`, so "not the owning session" is impossible without a different dispatcher                                   | See Q2                                                                                     |
| Many no-value verdicts in a row                                    | Rate counter in the ledger; past a configured count per window the next removal needs two agreeing reviewers from distinct agents (or the owner)                 | Threshold is the owner's (Q5)                                                              |
| Bulk path deletes on a stale verdict                               | Unlock only in the explicit, named `delete-branch`; `clean_sweep`, `cleanup_after_merge` and `delete_if_merged` never consult verdicts                           | None                                                                                       |
| Downgraded reviewer (safety fallback swaps the model mid-run)      | Any non-Opus assistant record or a fallback record invalidates the verdict                                                                                       | None                                                                                       |

## 5. Item 4: keeping archive refs and tags from piling up

Two existing routes already create refs that accumulate, and they matter here because
the verdict route is meant to replace them:

1. `core/branch_practice.recovery_copy_advisory` tells an agent to keep a recovery copy as
   `git update-ref refs/archive/<name> <sha>` rather than as a branch.
2. `TIER_REMOTE_HELD` in `branch_safety` lets `delete-branch` succeed once the remote holds
   the tip under a ref this clone does not fetch, which is exactly a pushed archive ref.

Together they are a working "archive it, then delete it" exit for unproven work, which is
the sprawl the owner rejected in Plan 00619. That is outside this plan's scope to change
(Q6), but the verdict route should be designed so it never needs either.

**Smallest design: no ref of any kind.** The removal leaves one tracked ledger line and the
printed restore line. The honest consequence: after the delete, recovery depends on git
keeping unreachable objects (`gc.pruneExpire`, plus any HEAD or worktree reflog that still
names the commits), which is a default, not a guarantee. To make that window usable
without a ref, the ledger line records the repository's effective `gc.pruneExpire`, the
guard refuses the verdict route when it is `now` or disabled, and the digest is produced
on a cadence well inside it.

**Optional stronger variant (Q4): condemn, then delete.** The verdict marks the branch
condemned (a `git config` key beside the park and keep keys), the branch leaves the
WIP-cap count at once, and the actual delete happens on a later explicit run after the
owner's next digest. Nothing is ever unrecoverable before the owner has seen it, still
with zero refs and no human action required. Cost: one more state for the pools to
understand.

## 6. Recommended design (draft for Task 1.2)

1. **Request.** `hooks-daemon branch-verdict request <branch>` classifies the branch
   (must be `unproven`, not protected, not in a worktree), records `{nonce, branch, tip, default sha, inventory}` in daemon state and prints the exact dispatch prompt and the
   reviewer type. No caller-supplied text is accepted.
2. **Reviewer definition.** A tracked, read-only agent definition (Read, Grep, Glob, a
   read-only Bash), frontmatter `model: opus`. Its prompt states the keep-by-default rules
   from PLAN.md (tests, plan files, docs, config, anything a plan or journal describes are
   kept unless a superseding commit or path on the default is cited) and the required
   output block: tip, nonce, one line per unique commit and per content-unique path with a
   verdict (`no-value` or `keep`) and a reason, and an overall verdict.
3. **Dispatch gate (PreToolUse `Agent`).** For that reviewer type: deny unless the prompt
   equals an outstanding request, the model resolves to Opus or above, and it is not a
   fork. Record `tool_use_id` to nonce; PostToolUse records `agentId`.
4. **Record (SubagentStop).** For an `agent_id` bound to a nonce: parse the block; check
   tip and nonce; check every transcript assistant record's model and the downgrade scan;
   check a single user turn; check the reviewer identity is not a creator or toucher;
   store the reply and its sha256; write the verdict record into daemon state, tagged
   with issued-at and the configured lifetime. A `keep` verdict is recorded too and blocks
   further requests for that tip.
5. **Delete.** `delete-branch <name>` only (never the sweep or merge-cleanup paths): an
   `unproven` branch proceeds when a valid, unconsumed, unexpired verdict exists for its
   current tip, the recomputed inventory matches the verdict line for line, and every
   superseded citation resolves. The delete uses the existing path, so the tip re-check and
   the restore line are unchanged.
6. **Ledger and digest.** One tracked line per removal: branch, tip, default sha, verdict
   id, reviewer agent id and model, reply sha256, `gc.pruneExpire`, restore command. The
   digest lists every removal and every keep verdict since the last digest.
7. **Escalation.** Past a configured number of removals per window, a single verdict no
   longer suffices: two agreeing verdicts from distinct reviewer agents are required.

The build phase must confirm by a live dispatch what is inferred here from contracts and
existing handlers: that a background dispatch's PostToolUse carries `agentId`, and that
the agent `meta.json` `tool_use_id` matches the parent call.

## 7. Open questions for the owner

- **Q1. Threat model.** Accept "motivated but not forging" as the boundary, given that a
  same-user agent can fabricate the hook event chain? If not, the only real boundary is a
  different trust domain (a human, or a dispatcher the agent's user cannot reach), and the
  plan's autonomy goal cannot be met.
- **Q2. "Never by the session that owns the branch."** A sub-agent always shares its
  dispatcher's session id. Is a fresh-context sub-agent of the owning session acceptable,
  or must the review be dispatched by a different session (for example a coordinator or a
  scheduled job)?
- **Q3. Same-model review.** Is "at least Opus" enough, or must the reviewer be at least
  the caller's family, or a different family from the caller?
- **Q4. Delete now, or condemn then delete** after the owner's next digest?
- **Q5. Retry and escalation numbers.** May a branch with a `keep` verdict ever be
  re-reviewed (after its tip changes only?), and what removal count per window triggers
  the two-reviewer rule?
- **Q6. Existing archive exits.** Should `recovery_copy_advisory` and the archive use of
  `remote-held` be retired (in Plan 00619 or a new plan) so the verdict route is the only
  exit for unproven work?
- **Q7. Remote copy.** Local only, or does a valid verdict also unlock the remote delete
  that R-GIT-PUSH-DELETE-REMOTE refuses today? A branch with a remote copy can already be
  deleted locally, so the pools' remote half only shrinks if this is yes.
- **Q8. Ledger location.** Which tracked file holds the ledger, and who commits it (the
  `delete-branch` run appending to the checkout it runs in, then the agent's next commit)?
