# Plan 00620: design of the no-value removal route

Supporting document for [PLAN.md](PLAN.md). It is the builder's elaboration of
[RULINGS.md](RULINGS.md), not a proposal awaiting approval: where this document and the
rulings disagree, the rulings win and this document is wrong. It is judged by the
independent loosening review and the adversarial pass of Task 2.4.

The code home is one module, `src/claude_code_hooks_daemon/core/branch_reject.py`. Slice 1
ships it with no caller; slice 2 wires it into `delete-branch`, the `branch-reject` CLI, the
dispatch gate and the SubagentStop recorder.

## 1. Configuration: `branches.reject`

One model, `BranchRejectConfig`, under `BranchesConfig.reject`. Every number below is a
default there, never a constant in the module.

| Key                      | Default                         | Meaning                                                                    |
| ------------------------ | ------------------------------- | -------------------------------------------------------------------------- |
| `verdict_lifetime_hours` | 24                              | A verdict is valid this long from `issued_at`                              |
| `window_days`            | 7                               | The rolling window the rate count reads from the ledger                    |
| `two_reviewer_after`     | 3                               | Once this many removals are in the window, the next needs two              |
| `refuse_after`           | 10                              | Once this many removals are in the window, the route refuses               |
| `ledger_path`            | `.claude/branch-removals.jsonl` | Tracked ledger, relative to the checkout the delete runs in                |
| `bundle_dir`             | `untracked/branch-rejects`      | Bundle directory, relative to the MAIN checkout, never a worktree          |
| `state_dir`              | `untracked/branch-reject-state` | Request, dispatch, verdict and keep records, relative to the MAIN checkout |

**The thresholds read "once N are in the window".** RULINGS Q5 says "above 3 removals every
further removal needs two". The module reads it as: with `n` removals already in the window,
the next removal needs two reviewers when `n >= two_reviewer_after` and is refused when
`n >= refuse_after`. So removals 1 to 3 take one reviewer, the 4th and later take two, and
the 11th is refused. This is the stricter of the two readings.

## 2. The inventory

What the reviewer must judge, and what the guard recomputes at delete time. Measured
against the DEFAULT branch only, never an integration line (a line is not where rejected
work is judged superseded).

- `commits`: the `git cherry <default> <tip>` unique commits (`cherry_unique_shas`), plus
  every merge commit in `<default>..<tip>`. `cherry` never lists merges, and a merge can
  carry content of its own (an evil merge), so a merge is always listed for judgement.
  Sorted, full shas.
- `paths`: `content_unique_paths_of(tip, reachable(default))`, the tip-tree paths whose
  blob exists nowhere in the default's history. Sorted.

Every git failure raises `RejectError`. A failed walk never reads as an empty inventory.
Paths the branch deleted are not listed: a deletion holds no work that a reviewer could
judge, and the bundle keeps the whole tip regardless.

## 3. State layout (daemon state, main checkout)

`<main>/<state_dir>/` holds one JSON file per record, written atomically
(`write_text` to a sibling temp file, then `os.replace`):

| File                         | Writer (slice)                       | Content                                                                                                    |
| ---------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `requests/<nonce>.json`      | `branch-reject request` (2)          | `RejectRequest`: nonce, branch, tip, default_sha, inventory, reviewers_required, prompt_sha256, created_at |
| `dispatches/<nonce>.json`    | PreToolUse/PostToolUse `Agent` (2)   | `DispatchRecord`: nonce, session_id, tool_use_id, agent_id                                                 |
| `verdicts/<verdict_id>.json` | SubagentStop recorder (2)            | `Verdict` (section 4)                                                                                      |
| `keeps/<verdict_id>.json`    | SubagentStop recorder, on `keep` (2) | `KeepRecord`: branch, tip, commits, reasons, recorded_at                                                   |
| `stops/<nonce>.json`         | SubagentStop recorder (2)            | Marker: schema, nonce. Created exclusively on the reviewer's FIRST stop                                    |

The nonce is 32 lowercase hex characters from `secrets.token_hex(16)`; the verdict id is
the same shape. A file name that is not that shape is ignored and never opened.

The recorder writes the verdict under `verdict_id = nonce`, with an exclusive create
(`os.link`, as `dispatches/` uses), so one nonce has at most one verdict. A verdict counts
only from a clean, final stop. The first stop of an identified reviewer creates
`stops/<nonce>.json` before anything else. A later stop of the same nonce, or any stop
whose `stop_hook_active` is not literally `false`, withdraws (unlinks) the nonce's verdict
and records nothing. A stop hook that blocked the first reply therefore leaves no verdict.
A keep record is never withdrawn, because it only restricts. The recorder never writes the
dispatch record's agent id and never touches the ledger.

A record is believed only through its chain. A verdict counts only when a request with its
nonce exists, a dispatch record binds that nonce to the verdict's reviewer agent, and the
request, the verdict and the recomputed git facts agree (section 5). A verdict file written
by hand with no request and no dispatch record is therefore inert, which is the "forged"
case the red tests pin. A same-user forger who writes all three files is the residue
RULINGS Q1 accepts.

## 4. The verdict record

```json
{
  "schema": 1,
  "verdict_id": "<32 hex>",
  "nonce": "<32 hex>",
  "branch": "feature-x",
  "tip": "<40 hex>",
  "default_sha": "<40 hex>",
  "inventory": {"commits": ["<sha>"], "paths": ["src/a.py"]},
  "items": [
    {"kind": "commit", "ref": "<sha>", "decision": "no-value", "reason": "...", "superseded_by": []},
    {"kind": "path", "ref": "docs/x.md", "decision": "no-value", "reason": "...",
     "superseded_by": ["path:docs/y.md", "commit:<sha>"]}
  ],
  "overall": "no-value",
  "issued_at": 1795000000.0,
  "reviewer": {
    "session_id": "...", "agent_id": "...",
    "models": ["claude-opus-5-5"],
    "downgraded": false, "fork": false, "user_turns": 1,
    "reply_sha256": "<64 hex>"
  }
}
```

The recorder fills `reviewer` from the agent transcript (every assistant record's
`message.model`, the downgrade scan, the count of human-text user turns), never from
`meta.json`: the live probe (JOURNAL 2026-11-20 00:48) found `meta.json` names the
requested alias and an unrelated `pickedEffortModel`, not the model that ran. The binding
from the parent call to the agent reads `meta.json`'s camelCase `toolUseId`.

## 5. Verdict validation (`verdict_problems`)

Returns every problem found; an empty list is the only pass. Each check fails closed.

01. Shape: schema 1, ids of the right form, the verdict id EQUAL to its nonce, `overall`
    and every `decision` in `{no-value, keep}`, every reason non-empty. Separately,
    `verdicts_for` raises (so the route refuses) when any verdict file is not named by its
    own id.
02. Chain: the request with this nonce exists; the verdict's branch, tip, default sha and
    inventory equal the request's; the dispatch record for the nonce names the same
    session and agent as `reviewer`.
03. Tip: the verdict's tip equals the branch's current tip.
04. Inventory: equals the inventory recomputed from git now, commit for commit and path for
    path, and the items cover it exactly: one item per commit and per path, no extra, no
    duplicate.
05. Overall: `no-value` requires every item `no-value`; any `keep` item makes it `keep`.
06. Keep by default: a path item judged `no-value` whose path is a test, a plan or journal
    file, a doc or config (`is_keep_by_default`) must carry at least one citation.
07. Citations: `commit:<sha>` must be an ancestor of the default; `path:<p>` must exist in
    the default's tree. The guard checks the citation resolves, never that it is apt.
08. Expiry: `issued_at <= now < issued_at + verdict_lifetime_hours`. A verdict from the
    future is a problem too.
09. Single use: the verdict id, its nonce and its reviewer agent id are each absent from
    every ledger line (removal or git-refused). `record_removal` re-checks ids and agents
    at append time. These bindings refuse a used verdict that is re-filed under a fresh id,
    or a used chain (request, dispatch and verdict) copied whole under a fresh nonce. A
    forger who also writes a new agent id is the residue RULINGS Q1 accepts.
10. Reviewer: at least one model, every model resolves to Opus or above, not downgraded,
    not a fork, exactly one human-text user turn, a 64-hex reply digest.
11. Independence: `<session>:<agent>` of the reviewer is neither the branch's creator nor
    on its touch record (`branch_records.branch_identities`).

When two reviewers are required, each verdict passes on its own and the agent ids are
distinct; disagreement is `keep`.

## 6. Request admission and the keep history

`admit_request(branch, tip, inventory, keeps, removals_in_window, config)` returns the
number of reviewers required (1 or 2) or raises `RejectRefused` naming why:

- a keep record for this tip (by name, or by sharing a commit): refused, a keep is final for
  its tip;
- related keep records (same name, or sharing any unique commit with this inventory, so a
  rename earns nothing): one earlier keep makes this a re-review needing two reviewers, two
  or more close the route;
- the rate rule of section 1;
- the larger requirement wins.

## 7. The recovery bundle

`write_bundle(repo, branch, tip, default_sha, config)`:

- resolves the MAIN checkout from `git rev-parse --git-common-dir` and refuses
  (`RejectError`) when that is not a `.git` directory of a non-bare checkout;
- writes `<main>/<bundle_dir>/<slug>-<tip12>.bundle` with
  `git bundle create <tmp> refs/heads/<branch> ^<default_sha>` and renames it into place;
  the slug keeps `[A-Za-z0-9._-]` and maps everything else to `-`;
- never overwrites: an existing file at the path is kept and verified instead;
- returns `BundleRecord(path, sha256, tip)`.

`bundle_problems(repo, record)` (an empty list is a pass): the file exists, its sha256 equals
the record's, `git bundle verify` passes in this repository, and `git bundle list-heads`
lists the tip.

Restore lines printed by the delete:
`git fetch <bundle> refs/heads/<branch>:refs/heads/<branch>` and `git branch <branch> <tip>`.

## 8. The ledger

`.claude/branch-removals.jsonl`, one JSON object per line, appended with a single
`O_APPEND` write and an `fsync`. Fields: `schema`, `branch`, `tip`, `default_sha`,
`verdict_ids`, `reviewer_agent_ids`, `reviewer_models`, `reply_sha256s`, `bundle_path`,
`bundle_sha256`, `restore_commands`, `removed_at`.

Reading is strict: a line that is not a JSON object with every field raises
`RejectError`, so a damaged ledger refuses the route rather than undercounting the rate or
forgetting a consumed verdict.

**Two branches appending, then merging.** `.gitattributes` carries
`.claude/branch-removals.jsonl merge=union`, so two appends on two branches merge as both
lines with no conflict. A test merges two real branches to pin it.

## 9. The review prompt (composed by the daemon, slice 2)

The prompt is composed from the request alone, never from caller text, and its sha256 is
stored on the request so the dispatch gate compares bytes:

```
[branch-reject review] nonce <nonce>

You are reviewing the unmerged work on branch `<branch>` at tip <tip>, measured against
the default branch at <default_sha>. Decide, for each item below, whether it has any
value. Doubt means keep.

Keep by default, unless you cite what supersedes it on the default branch: tests, plan and
journal files, documentation, configuration, and any work a plan or journal describes.

Commits not on the default branch:
- <sha> <subject>
Files whose content exists nowhere on the default branch:
- <path>

<on a re-review: the earlier keep verdict's reasons, quoted>

Reply with exactly this block and nothing after it:
BRANCH-REJECT-VERDICT nonce=<nonce> tip=<tip>
commit <sha> no-value|keep: <reason> [superseded-by: commit:<sha> path:<path> ...]
path <path> no-value|keep: <reason> [superseded-by: ...]
overall no-value|keep
END-BRANCH-REJECT-VERDICT
```

## 10. The delete (slice 2 contract, pinned red in slice 1)

`delete_branches(..., reject_route=RejectRoute(...))`. `None`, the default, is today's
behaviour, so `clean_sweep`, `cleanup_after_merge` and `delete_if_merged` never consult a
verdict. With a route, an `unproven` branch is deleted only when, in order: the verdicts
for its current tip validate (section 5) in the number required (section 6); the bundle is
written and `bundle_problems` is empty; the tip re-check passes; the ledger line is
appended (RULINGS section 1 item 5: before git is asked); git deletes. The classification
then reports tier `rejected-bundled` and the report's restore commands carry both lines of
section 7. Any failure before the ledger append leaves the branch in place and names the
problem.

Decided in slice 2 (`approve_removal`, `record_removal`, `record_git_refusal`):

- **Nothing is trusted from a record that git can answer.** The default sha the bundle is
  cut against and the ledger records is `rev-parse` of the default now. The reviewer count
  is recomputed at delete time from `admit_request` over the keeps and the ledger, and the
  larger of that and each request's own count wins, so a request admitted at an empty
  window cannot carry one reviewer past the two-reviewer or refuse threshold.
- **Any stored `keep` for this tip refuses**, even beside enough valid `no-value`
  verdicts; only then are the rest validated, and invalid ones are named in the refusal.
- **Eligibility:** only `unproven` with no refusal. A protected, current, worktree or
  unmerged-line branch stays refused whatever verdict exists.
- **Phases:** validation and the bundle write happen with every other blocker, so one
  unapproved branch removes none of the batch. A dry run validates and writes nothing.
  The route measures against `RejectRoute.default_ref` (the CLI sets the resolved default,
  since `--protected-ref` may name an integration line), falling back to `protected_ref`.
- **Bundle prerequisites.** `bundle_problems` also reads the bundle header and requires
  every prerequisite to be an ancestor of the base it was cut against
  (`BundleRecord.base`). Without it a planted thin bundle (`feat ^feat~1`) verifies and
  lists the tip, yet restores nothing once the branch is gone; a test pins the refusal.
  A `@filter` capability (a filtered bundle omits objects) refuses too.
- **Only bytes the guard wrote are trusted.** `git bundle verify` reads the header, not the
  pack: a probe (git 2.47) showed a planted bundle with a truncated pack, and a planted
  `--filter=blob:none` bundle, both passing it. `_create_bundle` therefore writes a
  `<bundle>.sha256` sidecar beside the file, and an existing bundle is reused only when its
  sha256 equals that record. A planted file, or one altered after the guard wrote it,
  refuses. A same-user forger who writes both files is the residue RULINGS Q1 accepts.
- **The batch counts itself.** Phase one appends nothing, so each approval passes the
  number already approved in the batch as `pending`, added to the window count; one
  batch cannot carry several removals past the two-reviewer or refuse threshold.
- **A crash between the append and git's answer** leaves an uncancelled removal line for
  a branch that may still exist. This is the cost of the ruling's append-first order; the
  digest (section 11) flags every listed removal whose branch still resolves at its
  recorded tip as `STILL PRESENT at its tip`.
- **A git refusal after the append** appends a second line,
  `{"outcome": "git-refused", branch, tip, verdict_ids, detail, refused_at}`.
  `read_ledger` returns only removals no refusal cancels (same tip and verdict ids), so
  the rate count does not see it; `read_ledger_entries` returns every line for the
  digest. The refused attempt's verdicts stay consumed (fail closed: a retry needs a fresh
  review). If even the refusal line cannot be appended, the blocker says the ledger
  wrongly records the removal. A line with an unknown `outcome` raises.

## 11. The digest (slice 3)

`branch-reject digest [--mark-read] [--format text|json]` lists every ledger removal, every
`git-refused` line and every keep verdict not yet marked read, then the rate line (removals
in the window and the reviewers the next removal needs, or that the route is refusing).

- **Identity, not position.** The watermark (`<state_dir>/digest.json`) holds the sha256 of
  each read entry's canonical JSON, and the ids of the read keeps. A line that arrives by a
  `merge=union` after a digest still shows as undigested.
- **Listing never advances the watermark.** Only `--mark-read` does, and it marks exactly
  the entries of the `Digest` that was printed, never one that arrived after the listing.
  The listing is built and rendered before the mark, so a failure prints nothing and marks
  nothing.
- **Strict.** A damaged ledger, keep record or watermark raises `RejectError` (exit 2); an
  unreadable state never reads as "nothing to digest".
- **It gates nothing.** `approve_removal` never reads the watermark, so an agent that marks
  entries read hides them from the digest only and unlocks no delete. The rate counts every
  removal in the window, marked or not.
- **Crash flag.** A listed removal whose branch still resolves at its recorded tip is
  flagged `STILL PRESENT at its tip` (section 10).

**The session-start count.** `branch_sweep` adds one line on every SessionStart source when
anything is undigested: the counts of removals, git refusals and keeps, and the digest
command. It reads only (no git call per entry, nothing written) and is independent of the
branch inventory, so an inventory failure does not hide it. No main checkout (not a
repository, or bare) is silent; a damaged ledger or watermark prints a loud
"unreadable" line instead of a count.
