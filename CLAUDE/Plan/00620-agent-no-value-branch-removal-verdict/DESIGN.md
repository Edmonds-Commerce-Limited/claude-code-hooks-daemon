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

The nonce is 32 lowercase hex characters from `secrets.token_hex(16)`; the verdict id is
the same shape. A file name that is not that shape is ignored and never opened.

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

01. Shape: schema 1, ids of the right form, `overall` and every `decision` in
    `{no-value, keep}`, every reason non-empty.
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
09. Single use: the verdict id is absent from every ledger line.
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
problem. A git refusal after the append leaves a ledger line for a removal that did not
happen; slice 2 must decide how that line is marked (an appended `"outcome": "git-refused"`
line is the first candidate, since the ledger is append-only).
