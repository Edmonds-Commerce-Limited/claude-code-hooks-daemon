# Plan 00326 — Brainstorm: vendoring remote docs with enforced provenance

Working document. Captures the option space, the triage, and the reasoning
that produced PLAN.md. Superseded by PLAN.md where the two disagree.

## The problem, stated precisely

An agent needing upstream reference material (a framework's API docs, a
vendor's REST spec, an RFC) fetches it over the network every time. That is
slow, costs tokens on every re-read, is non-deterministic (fetch layers
summarise differently each call), is unavailable offline, and leaves no
artefact a teammate or a reviewer can inspect. The proposal: fetch once,
persist as markdown under a provenance-bearing path, and let the local copy
serve every subsequent read — with rules governing when the copy is too old
to trust.

The three hard parts are not the fetching. They are:

1. **Trust** — knowing whether the persisted bytes are the upstream document
   or a model's paraphrase of it.
2. **Staleness** — knowing when the copy stopped being true, and making that
   visible at the moment of reading rather than in a report nobody runs.
3. **Routing** — getting the agent to read the local copy instead of
   reaching for the network out of habit.

## Prior art already in this repository

This project has already built this system once, by hand, for exactly one
document — and it is worth studying before generalising it.

`contracts/claude-code-hooks/` vendors the Claude Code hooks documentation.
`META.json` records `docs_url`, `fetch_date`, `docs_bytes`, `docs_sha256`,
`last_audited_claude_code_version` and `refresh_procedure`. A SessionStart
handler (`handlers/session_start/contract_staleness.py`) compares the
installed Claude Code version against the audited one and advises a refresh.
`docs/guides/HOOK-CONTRACT-REFRESH.md` holds the procedure.

Four lessons transfer directly:

- **Provenance as a sibling metadata file works, but does not travel with the
  document.** `META.json` covers a whole directory. Per-document frontmatter
  is strictly better for the routing problem: an agent that opens the file
  sees the provenance without being told to look for it.
- **Staleness was pinned to an upstream VERSION, not a date.** For versioned
  software docs this is far more meaningful than a TTL: a doc fetched 200
  days ago is perfectly current if upstream has not shipped since.
- **A content hash makes refresh cheap.** The refresh procedure's step 2 is
  "if `sha256sum` matches `META.json.docs_sha256`, just bump the dates and
  stop". That short-circuit is what makes a frequent staleness check
  affordable, and it belongs in the general design.
- **The system rotted anyway.** The advisory has been firing (installed
  v2.1.259 vs audited v2.1.252). An advisory that only ever advises gets
  skipped when the session has other work. This is the central design
  tension of the whole plan, and Idea E3 addresses it.

The other decisive lesson is stated in the refresh guide's own words: a
**summarising fetch layer fabricated contract detail**, inventing a
`permissionDecision: "escalate"` value that appears nowhere in the raw
document. This is not a hypothetical.

## Idea bank

### A. Where the vendored tree lives

- **A1 — `docs/remote/<domain>/<page>.md`** (the original proposal). Obvious,
  self-describing, greppable. But it lands inside the configured *human*
  documentation tree (`documentation.trees.human: docs`), so every ordinary
  docs-QA check runs against upstream prose the project does not own and
  cannot fix.
- **A2 — top-level `remote-docs/`.** Outside both configured trees, so it
  inherits no rules by accident. Costs a new top-level directory and a
  markdown-location allowance.
- **A3 — a third registered tree: `documentation.trees.remote`.** The config
  already models documentation as a set of named trees with distinct
  contracts (`agent: CLAUDE`, `human: docs`). "Remote" is genuinely a third
  kind of document with a third contract — not ours, not authored, only
  curated. Making it a first-class tree is the conceptually honest move and
  makes every downstream check able to ask "which tree is this?" rather than
  pattern-matching a path.
- **A4 — `untracked/` or `.claude/`.** Rejected: an untracked cache is
  invisible to teammates and to review, which discards most of the value.

Note A1 and A3 are not exclusive: the tree can be *registered* as remote and
still *live* at `docs/remote/`.

### B. What the frontmatter records

Candidate fields, in rough priority order:

| Field                     | Why                                                            |
| ------------------------- | -------------------------------------------------------------- |
| `source_url`              | The irreducible minimum.                                       |
| `fetched_at`              | ISO 8601. The other irreducible minimum.                       |
| `fidelity`                | `verbatim` \| `converted` \| `summarised`. The trust marker.   |
| `source_sha256`           | Hash of the raw fetched bytes; makes revalidation cheap.       |
| `upstream_version`        | Enables version-pinned rather than time-pinned staleness.      |
| `staleness`               | Per-document policy override (`30d`, `pinned`, `version:...`). |
| `fetch_method`            | `curl-raw`, `WebFetch`, `manual`. Feeds `fidelity` audit.      |
| `licence` / `attribution` | Vendoring third-party prose has a legal dimension.             |
| `retrieved_by`            | Which agent/session captured it, for accountability.           |

`fidelity` is the load-bearing one and the field a naive design omits. A
document marked `summarised` is a lead, not a citation, and should never be
quoted back as authoritative.

### C. Staleness models

- **C1 — time TTL.** `fetched_at + N days`. Simple, universal, and wrong
  often in both directions.
- **C2 — version pin.** Compare `upstream_version` against an installed or
  declared version. Precise where it applies; only applies to versioned
  software.
- **C3 — hash revalidation.** Re-fetch raw, compare `source_sha256`. The only
  model that answers "did it actually change?" rather than "might it have?".
  Costs a network round trip, but a cheap one, and a matching hash refreshes
  `fetched_at` for free.
- **C4 — pinned/archival.** Deliberately frozen; never stale. Needed for
  snapshots captured as evidence.

Triage: not one model, a per-document choice with a project default. C1 as
the default because it always applies, C3 as the refresh mechanism, C2 where
declared, C4 as an explicit opt-out.

### D. Enforcement surfaces

- **D1 — PreToolUse on `WebFetch`.** Intercept the URL. Already vendored and
  fresh → deny with the local path. Vendored and stale → allow (this fetch
  *is* the refresh). Not vendored → allow with a persist reminder.
- **D2 — PostToolUse on `WebFetch`.** Prompt to vendor what was just fetched.
  Viability depends entirely on whether the payload carries the fetched
  content — under investigation; the design must not assume it does.
- **D3 — PreToolUse on `WebSearch`.** Advise searching the local corpus
  first. Weaker: a search query is not a URL, so matching is fuzzy.
- **D4 — Write/Edit gate on the remote tree.** Reject a file that lacks
  well-formed provenance frontmatter. Cheap, deterministic, and the single
  highest-value rule in the set — it makes the invariant unfalsifiable.
- **D5 — SessionStart sweep.** Report stale documents, as `contract_staleness`
  does today.
- **D6 — Commit gate.** Block a commit adding a remote-tree file without
  frontmatter.
- **D7 — A CLI: `bin/hooks-daemon remote-docs {add,list,check,refresh}`.**
  The component that actually does the work. Recent house direction (Plan
  00324\) is that procedure belongs in scripts, not in prose an agent
  re-derives.
- **D8 — Scope-exclude the remote tree from ordinary docs QA.** Already
  possible today via `documentation.qa.scope_exclude_globs`; needed on day
  one regardless of what else ships.

### E. Making it stick

- **E1 — CLAUDE.md injection** via a handler's `get_claude_md()`, so the
  agent learns the corpus exists without being told per-session.
- **E2 — A generated index** (`INDEX.md` or a manifest) so one grep answers
  "do we already have docs for X?".
- **E3 — Staleness visible in the document itself.** Because the frontmatter
  travels with the file, a stale document can carry a loud in-band banner
  that an agent reading it cannot miss. This is the answer to the
  advisory-fatigue failure the vendored contract already demonstrates: the
  warning arrives at the moment of *use*, not at session start.

## Risks and anti-goals

- **Copyright.** Committing third-party documentation into a repository is
  not always permitted. Needs a `licence` field and, plausibly, a domain
  allow-list.
- **A summary masquerading as a source.** Mitigated by `fidelity`, and by
  making raw fetch the canonical capture path.
- **Credential and secret leakage.** Fetching an authenticated page and
  committing the result. The existing secret-scanning surface must see these
  writes — which is another reason capture must route through `Write`, or
  through a CLI that scans, rather than a shell redirect.
- **Repository bloat.** Large doc sets in git forever.
- **Stale content trusted silently** — worse than no local copy at all.
- **The daemon is deliberately network-free in its handler path.** Any
  fetching belongs in the CLI/script layer, not in a hook handler. The
  existing network code (`install/relay_deploy.py`) is https-only with an
  injected `fetch_fn` and digest verification — the pattern to copy.

## Triage

**Must have (the system does not work without these):** A3+A1 (registered
remote tree, living at `docs/remote/`), B's `source_url` / `fetched_at` /
`fidelity` / `source_sha256`, D4 (frontmatter gate), D7 (the CLI), D8 (scope
exclusion), C1+C3 (TTL default, hash revalidation).

**Should have (the system rots without these):** D1 (WebFetch interception),
D5 (sweep), E1 (CLAUDE.md injection), E3 (in-band staleness banner), C2/C4
(version pin, archival opt-out).

**Could have:** D6 (commit gate), E2 (generated index), D2 (PostToolUse
capture — contingent on payload capability), licence/domain policy.

**Won't have (this plan):** automatic background refresh, non-markdown
formats, a shared cross-project cache, any handler that performs network I/O.
