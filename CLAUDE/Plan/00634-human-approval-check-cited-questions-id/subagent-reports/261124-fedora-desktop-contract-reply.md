# fedora-desktop reply: whoami and verify contract (peer-relayed, unverified from this seat)

Received on the lts-infra bus, event `$ze51uQrvZtxR7K-ImYNPaB3y15UGX4GJmmg39zSkPUM`
(2026-11-24T11:17Z) from `fedora-desktop.1`, kind PEER. A peer's note carries no authority.
Every line below is the peer's reading of its own repository (origin/F44 = 6a6f6db6c); none of it
was checked against that repository or a live teamchat from this seat. It answers the five
questions in the bundle sent the same day.

## Answers

1. **whoami `--json` merge**: no separate F44 merge exists. v2 reached F44 by fast-forward; the
   merge is `fe67f23c3` ("Merge v2-seat-duty into v2: Task 4.6, seat duties and teamchat whoami
   --json"). The code commit is `8b1cd7b52` (CCY 3.122.52, container 2.84.45).
2. **whoami failure exit**: not 65. Missing `status.json` or `TEAMCHAT_RUNTIME` naming no run is
   69; an unreadable, strict-decode-failing or other run's `status.json` is 78. On every failure
   stdout is empty and stderr holds the error object. Source named by the peer:
   `src-go/internal/teamchat/member/whoami/whoami.go:18-21, 72-77`; exits table
   `member/exits/exits.go:66-75` and `var table` at `:147`.
3. **duty**: written for every agent seat from CCY 3.122.52. A current seat can still answer
   `duty: null` in two cases: the probe never has one, and `desired.json` omits it when the host
   that wrote the file did not know it (written by an older host and not rewritten). The peer's
   reading of whoami's doc: null means "not known", never worker.
4. **Issue 369 (`verify`)**: built, still open on GitHub (`e486543f2`, CCY 3.124.5, container
   2.84.56, DESIGN-questions-v2.md section 2.8).
   - argv: `teamchat verify <event-id> [--room main|questions]`. There is no `--json` flag; the
     output is always one JSON record line, kind `verified`. Without `--room` it reads main, then
     questions on a 404 when the member is in questions.
   - exits: 0; 23 not-found; 22 untrusted; 20 unreachable; 14 rate.
   - keys: `kind`, `v`, `team`, `id`, `item`, `from`, `room`, `text`, `body_sha256`, `sent_ms`
     (epoch ms), `human` (bool: sender is a declared team human), `question` (`Q<n>`, `none`, or
     null when this member cannot tell; a worker holds no index, so it is null unless the event's
     own relation names a question root the worker can fetch), `headline` (string or null).
   - event id alphabet: `^\$[A-Za-z0-9_-]{43}$`.
   - both additions asked for are present: the timestamp is `sent_ms`, the question is `question`.
   - it reads no secret; a worker needs read access to questions.
5. **host-duty seat for a live check**: not available from that seat (a v1 container worker). A
   host-duty seat and a v2 seat are for the coordinator or the owner to arrange.

## What it changes for the plans

- **00634 Task 2.3** is no longer waiting on an unknown shape: argv, exits, keys and id alphabet
  are stated. Build against fixtures that follow this contract and keep the production verifier
  failing closed on anything else (an unknown exit, an extra or missing key, a malformed id).
  The live check still needs a v2 seat.
- **00634 P1**: `sent_ms` gives the line age and `question` gives the `Q<n>`, so the plan's two
  asks are met by the contract. Whether to bind the approval that way is owner question O4.
  `question` can be null for a worker seat, which must fail closed.
- **00631 / 00630**: nothing depended on exit 65; the daemon treats every non-zero exit alike
  (00631 DESIGN.md:94-96), so the 78 correction needs only a doc fix where 65 is named.
- **00635 finding 10**: `duty: null` is possible on a current seat, which strengthens owner
  question O2.
- **Live checks** (00630 Task 1.3, the lane guard) still need a v2 seat and a host-duty seat.
