# Plan 00326: remote docs vendoring and staleness

**Status**: In Progress
**Created**: 2026-09-03
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

An agent that needs upstream reference material — a framework's API docs, a
vendor's REST spec, an RFC — fetches it over the network every time it is
needed. That is slow, costs tokens on every re-read, is unavailable offline,
is non-deterministic between calls, and leaves behind no artefact a teammate
or a reviewer can inspect. This plan makes remote documentation a **vendored,
tracked, provenance-bearing part of the repository**: fetched once, persisted
as markdown under a path that declares where it came from, carrying
frontmatter that records the source URL, the fetch time, the content hash and
— critically — whether the stored bytes are the upstream document or a
paraphrase of it.

The design is not speculative. This repository already built this system by
hand for exactly one document: `contracts/claude-code-hooks/` vendors the
Claude Code hooks documentation, `META.json` records its provenance,
`handlers/session_start/contract_staleness.py` advises when it has aged out,
and `docs/guides/HOOK-CONTRACT-REFRESH.md` holds the refresh procedure. Plan
00326 generalises that one-off into a reusable subsystem and then folds the
original into it, so the generalisation is proven by subsuming the case that
motivated it rather than by assertion.

Two failures already visible in that prior art set the shape of this plan.
First, a summarising fetch layer **fabricated** contract detail during the
Plan 00271 audit — inventing a `permissionDecision: "escalate"` value that
appears nowhere in the raw document. Persisting `WebFetch` output as though
it were the source would institutionalise that failure, so raw capture is the
canonical path and fidelity is recorded per document. Second, the staleness
advisory **rotted**: it is firing in the current session (installed v2.1.259
against an audit of v2.1.252) and has simply been skipped in favour of other
work. A staleness signal delivered only at session start has a demonstrated
failure mode here, so this plan also puts the warning inside the document,
where it is unavoidable at the moment of use.

Full option space, alternatives considered and triage: [BRAINSTORM.md](BRAINSTORM.md).

## Goals

- A remote documentation tree registered as a **first-class documentation
  tree** with its own contract, living outside the agent (`CLAUDE/`) and
  human (`docs/`) trees so it inherits none of the rules written for prose
  this project authors and can fix.
- A **provenance frontmatter schema** — `source_url`, `fetched_at`,
  `fidelity`, `source_sha256`, `licence`, `stale_after`, plus optional
  `upstream_version`, `staleness` and `fetch_method` — that is
  machine-checkable and travels with the document.
- A **capture and refresh CLI** that fetches raw, hashes, converts to
  markdown, and writes the frontmatter, so the procedure lives in a script
  rather than in prose an agent re-derives each time.
- A **write-time gate** that makes a file in the remote tree without valid
  provenance frontmatter impossible to commit.
- **Staleness surfaced at the point of use** — a `stale_after` date in the
  document, and an advisory the moment an agent reads a stale copy — as well
  as in the session-start sweep, with per-document policy and a content-hash
  short-circuit that makes revalidation cheap.
- **Routing**: an agent about to fetch a URL the project has already vendored
  is told about the local copy.
- The existing `contracts/claude-code-hooks/` vendoring **migrated onto this
  subsystem**, with its bespoke staleness handler retired or reduced to a
  thin adapter.

## Non-Goals

- **No network I/O in any hook handler.** The daemon's handler path is
  deliberately network-free; fetching belongs in the CLI/script layer, which
  follows the existing `install/relay_deploy.py` pattern (https-only,
  injected `fetch_fn`, digest-verified, never hard-fails).
- **No automatic background refresh.** Capture and refresh are agent- or
  human-initiated. Extraction from prose docs is verified, not trusted.
- **No non-markdown formats** (PDF, OpenAPI JSON, HTML archives).
- **No shared cross-project or cross-machine cache.** The tree is per-repo.
- **No mirroring of entire documentation sites.** Page-at-a-time capture.
- **No `WebSearch` interception** (D14) and **no capture from the `WebFetch`
  payload** (D15): discovery stays a network operation, and the only capture
  path is the CLI's own raw fetch.
- **No blocking domain allow-list** (D13): licence is declared per document
  and reviewed, not gated at capture.

## Key design decisions

The decisions this plan rests on, each with its reasoning, live in
[DECISIONS.md](DECISIONS.md). The ones that most shape the work:

- **D2/D3** — raw fetch is the canonical capture path, and every document
  records a `fidelity` field. Without these this is a cache; with them it is
  a citable corpus.
- **D5** — staleness is surfaced *in the document*, because the equivalent
  session-start advisory in this repo demonstrably rotted.
- **D10** — path exclusion is global across checks, so it cannot by itself
  give docs QA a remote-docs subset; per-check path scoping does not exist
  today and is new capability (amended in DECISIONS.md: see Task 3.1).
- **D11** — the web-tool `tool_input` field names are settled by capture,
  not assumption.
- **D12** — the tree is a top-level `remote-docs/`, never a `docs/`
  subdirectory; its markdown-location allowance derives from the tree
  registration, so no project needs a config entry for it.
- **D15/D16** — nothing reads the `WebFetch` payload; the point-of-use
  warning is a `stale_after` field plus a `Read`-time advisory, never a
  command that mutates a document to mark it stale.

## Tasks

### Phase 0: De-risk before building

Phase 0 precedes Phase 5: Task 5.1 keys on the `WebFetch` `tool_input` URL
field. **Settled — see [PAYLOADS.md](PAYLOADS.md): the field is
`tool_input.url`.**

- [x] ✅ **Task 0.1**: Payloads captured (see [PAYLOADS.md](PAYLOADS.md)).
  `WebFetch`'s `tool_response.result` is the fast model's **answer to the
  prompt**, not the page — no route exists from a `WebFetch` to the document
  it fetched. D2 confirmed by measurement, D15 upgraded to fact.
- [ ] ⬜ **Task 0.2**: Decide whether the vendored contract should record that
  real `PreToolUse` payloads carry `effort` and `prompt_id`, which its
  `input_example` omits (candidate finding logged in `PAYLOADS.md`). The
  per-event examples may be illustrative by design; either outcome closes
  the task.

### Phase 1: The remote tree and its provenance contract

- [x] ✅ **Task 1.1**: Schema in `remote_docs/provenance.py`; every field has
  a validator and a rejection test.
- [x] ✅ **Task 1.2**: `parse_provenance()` returns a typed `ParseResult`,
  never raising, reporting EVERY invalid field. Reuses the shared splitter,
  promoted to a public `split_frontmatter()`.
- [x] ✅ **Task 1.3**: Tree registered — `documentation.trees.remote` (default
  `remote-docs`), a `remote_docs_dir` axis (defaulted and last, so the
  addition is additive for existing call sites) plus `is_remote_docs_path()`
  on `ProjectLayout`, and a config-derived allowance in
  `markdown_organization`. `is_docs_path()` deliberately does NOT claim the
  tree. Required fixing a latent `normalize_path` defect first (see Task
  1.6) — without it the allowance branch was unreachable.
- [x] ✅ **Task 1.4**: Confirmed by test — a remote doc yields zero sweep
  findings, and a CONTROL test proves the same content in the human tree
  does trip them, so the exclusion is real rather than an empty sweep. No
  `scope_exclude_globs` entry needed: the tree is never corpus-collected.
- [x] ✅ **Task 1.6**: Fix `markdown_organization.normalize_path`, which
  matched its project markers as bare SUBSTRINGS — so `remote-docs/`
  collapsed to `docs/` and the remote tree was silently classified as the
  human docs tree. Markers now match only at a path-segment boundary, and
  the remote tree is itself a marker. Found because Task 1.3's first
  allowance test passed vacuously.
- [x] ✅ **Task 1.5**: `remote-docs` directory role ships (globs derived from
  `layout.remote_docs_dir`), so every install deploys
  `.claude/rules/remote-docs.md`: captured not authored, never reworded,
  frontmatter mandatory. A test asserts the human-docs rule does not also
  match the tree.

### Phase 2: Capture and refresh CLI

- [x] ✅ **Task 2.1**: `remote-docs add <url>` — raw https fetch via an
  injected `fetch_fn`, RAW-bytes hash, provenance frontmatter, written to
  the derived path. The written file parses clean under the Task 1.2 parser
  with no manual edit. `known_sources` licence pre-fill is deferred to
  Task 3.7's config work; capture records `unreviewed` until then.
- [x] ✅ **Task 2.2**: Path derivation is `<host>/<path>.md`, deterministic,
  filesystem-safe, traversal-proof. Where the readable form is lossy (query,
  fragment, sanitised characters) a short URL digest disambiguates, so
  `?v=1` and `?v=2` cannot overwrite each other. An implied `index` is not
  lossy: `/docs` and `/docs/` already derive differently.
- [x] ✅ **Task 2.3**: `remote-docs refresh <--path|--all>` with the hash
  short-circuit — unchanged upstream moves `fetched_at`/`stale_after` only,
  changed upstream rewrites the body. Refresh reads the URL from the file,
  and carries the recorded `licence` across rather than re-deriving it.
- [x] ✅ **Task 2.4**: `remote-docs list` and `remote-docs check` — read-only,
  CI-suitable, exit 1 when any document is stale OR has unreadable
  provenance (silence must not mean "clean" over an unparseable corpus).
- [x] ✅ **Task 2.5**: `write_capture` takes an injected `content_guard`; the
  CLI wires in `SensitiveContentHandler.scan_text`, made public so there is
  one definition of "sensitive" rather than a weaker second copy. A rejected
  capture writes nothing, and the secret-word arm reports only an index,
  never the term.

### Phase 3: The write-time gate

**D17 rewrote this phase.** The gate is a `PreToolUse` handler, not a
`docs_qa` check family: it judges one file's content at write time, so it
needs no corpus, and D12's top-level tree removed the need for a second
scope predicate. Tasks 3.1–3.3 were substrate for the `docs_qa` route and
are no longer paid for by this plan.

- [x] 🟩 **Task 3.4**: `remote_docs_provenance` — a blocking `PreToolUse`
  handler denying a markdown `Write`/`Edit` in the tree whose content lacks
  valid provenance. Names every invalid field at once, and points at
  `remote-docs add` so the deny teaches the capture route rather than
  inviting a hand-written frontmatter block. Only `new_string` is judged on
  an `Edit`, so removing content is never blocked.
- [x] 🟩 **Task 3.6**: `RuleID.REMOTE_DOCS_PROVENANCE`, the `Rule(...)`
  verbose text behind `explain-rule`, and the `HANDLER_REFERENCE.md` entry.
- [x] 🟩 **Task 3.7**: `documentation.remote` — `default_staleness_days`
  (`gt=0`, so a window cannot mark captures stale on arrival) and
  `known_sources` (domain → licence, matched case-insensitively and
  accepting a URL directly, since callers hold URLs). Precedence is
  `--licence` flag > `known_sources` > `unreviewed` sentinel: the flag is
  the narrower statement, the config is the standing default (D13).
- [ ] ⬜ **Task 3.8**: Record the fetcher's reported `source`
  (`accept-markdown` vs `html-fallback`) in provenance — a sharper signal
  than the binary name, distinguishing upstream's own markdown from our
  extraction of their HTML. Deferred from D18 because it changes the
  `FetchFn` contract from `str -> bytes` at every call site.

**Not done here, deliberately** — the dropped Tasks 3.1–3.3 and 3.5, and why
each is either moot or worth filing separately, are recorded in D17.

### Phase 4: Staleness

- [x] 🟩 **Task 4.1**: Time TTL and pinned/archival resolve to a
  `stale_after` date (or the `never` sentinel) at capture, from
  `documentation.remote.default_staleness_days` or `--stale-after-days`.
  Hash revalidation is `refresh`'s `source_sha256` short-circuit, which
  reports `unchanged` and moves only `fetched_at`. **Version pin is not
  built**: the `upstream_version` field exists in the schema but nothing
  populates or compares it, because no vendored source in this repo
  publishes a version to pin to. Left as schema-ready rather than
  speculatively implemented.
- [x] 🟩 **Task 4.2**: `stale_after` is written by `add` and `refresh`; a
  refresh re-derives the window from the document's own record, so a
  project that widened or narrowed one keeps its choice, and a pinned
  document stays pinned. Nothing mutates a document to mark it stale (D16).
- [x] 🟩 **Task 4.3**: `remote_docs_staleness` — a SessionStart advisory
  reporting documents past `stale_after` or whose provenance no longer
  parses (unreadable is not fresh, it is unknown). Silent when the tree is
  absent, so a project vendoring nothing never sees it; the listing is
  capped with a total so a large corpus cannot crowd out other session
  advice. **No version cache** unlike `contract_staleness`: that handler
  caches an external `claude --version` subprocess, whereas this reads
  local files that are cheap and must not be served stale by a cache.
- [ ] ⬜ **Task 4.4**: Ensure a client project's remote tree is treated as
  project-owned — unlike the daemon's vendored contract, a client's
  vendored docs *are* theirs to refresh.

### Phase 5: Routing agents to the local copy

One PreToolUse handler carries both branches; Task 0.1 supplies the
`WebFetch` field name it reads.

- [ ] ⬜ **Task 5.1**: `WebFetch` branch: normalise the URL (scheme, host
  case, trailing slash, fragment, common tracking parameters) and look it
  up in the tree. Vendored and fresh → deny with the local path; vendored
  but stale → allow (the fetch is the refresh); not vendored → allow with a
  capture hint naming the exact `remote-docs add <url>` command.
- [ ] ⬜ **Task 5.2**: `get_claude_md()` guidance so agents learn the corpus
  exists without per-session prompting, plus a generated index so one
  grep answers "do we already have docs for X?".
- [ ] ⬜ **Task 5.3**: `Read` branch: a remote-tree path whose `stale_after`
  has passed → allow with an advisory naming `fetched_at`, `stale_after`
  and the refresh command; `licence: unreviewed` is named in the same
  advisory (D16). Fast path: a prefix test on the tree before any file I/O,
  as `secret_file_guard` does.

### Phase 6: Migrate the existing vendored contract (dogfood)

- [ ] ⬜ **Task 6.1**: Express `contracts/claude-code-hooks/META.json` in the
  new provenance schema, confirming `upstream_version` pinning and
  `fidelity: converted` are expressible.
- [ ] ⬜ **Task 6.2**: Retire `contract_staleness.py` or reduce it to a thin
  adapter over the general staleness evaluator, preserving its
  client-install advisory wording.
- [ ] ⬜ **Task 6.3**: Fold `HOOK-CONTRACT-REFRESH.md`'s procedure into the
  CLI where it is mechanisable, keeping the verification steps that must
  stay human/agent-judged, and clear the currently-firing staleness
  advisory (v2.1.252 → v2.1.259).

### Phase 7: Documentation and acceptance

- [ ] ⬜ **Task 7.1**: Agent-tree deep-dive documenting the remote tree
  contract, the schema and the fidelity rule, plus the remote-tree row in
  `CLAUDE/DirectoryRoles.md`.
- [ ] ⬜ **Task 7.2**: Human-tree guide covering capture, refresh and staleness
  policy configuration.
- [ ] ⬜ **Task 7.3**: `AcceptanceTest` declarations on every new handler, per
  house convention.
- [ ] ⬜ **Task 7.4**: Config-schema entries, defaults, and a `config-changes`
  manifest entry for the upgrade path.

## Success Criteria

- [ ] A markdown file in the remote tree without valid provenance frontmatter
  cannot be written via `Write`/`Edit` and cannot pass the commit gate.
- [ ] `remote-docs add <url>` produces a file whose frontmatter records source
  URL, fetch time, raw content hash, fidelity, licence and `stale_after`,
  with no manual editing.
- [ ] `remote-docs refresh` on unchanged upstream content performs no rewrite
  beyond `fetched_at`/`stale_after`, and says so.
- [ ] A stale document announces its staleness **in its own contents**, and
  an agent reading it through `Read` is told so at that moment.
- [ ] Ordinary documentation-QA checks produce zero findings against vendored
  upstream prose.
- [ ] An agent calling `WebFetch` on an already-vendored, fresh URL is
  redirected to the local path.
- [ ] `contracts/claude-code-hooks/` is managed by this subsystem, and its
  currently-firing staleness advisory is cleared.
- [ ] Every new handler ships with tests, an `explain-rule` entry, a
  `HANDLER_REFERENCE.md` entry and an `AcceptanceTest`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00326-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — Phases 1–3: the tree exists, provenance is enforced, capture works.
- Milestone B — Phases 4–5: staleness is measured and surfaced; agents are routed to local copies.
- Milestone C — Phases 6–7: the motivating case is migrated; docs and acceptance complete.
