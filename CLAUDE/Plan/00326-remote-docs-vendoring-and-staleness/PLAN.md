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
- A **provenance frontmatter schema** that is machine-checkable and travels
  with the document (fields listed in [CLAUDE/RemoteDocs.md](../../RemoteDocs.md)).
- A **capture and refresh CLI**, so the procedure lives in a script rather
  than in prose an agent re-derives each time.
- A **write-time gate** making a remote-tree file without valid provenance
  impossible to commit.
- **Staleness surfaced at the point of use** — a `stale_after` date in the
  document and an advisory when an agent reads a stale copy — as well as in
  the session-start sweep, with a content-hash short-circuit that makes
  revalidation cheap.
- **Routing**: an agent about to fetch a URL the project has already vendored
  is told about the local copy.
- ~~The existing `contracts/claude-code-hooks/` vendoring migrated onto this
  subsystem~~ — **dropped (D20)**: it vendors derived schemas, not documents,
  and its source doc is deliberately untracked.

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

Every decision and its reasoning lives in [DECISIONS.md](DECISIONS.md) —
D1–D20, including the four taken during implementation (D17–D20) that
superseded parts of the original design. The single load-bearing one:
**D3, the `fidelity` field**. Without it this is a cache; with it, a citable
corpus.

## Tasks

### Phase 0: De-risk before building

- [x] ✅ **Task 0.1**: Payloads captured (see [PAYLOADS.md](PAYLOADS.md)); the
  field is `tool_input.url`. `WebFetch`'s `tool_response.result` is the fast
  model's **answer to the prompt**, not the page — no route exists from a
  `WebFetch` to the document it fetched. D2 confirmed by measurement, D15
  upgraded to fact.
- [x] ✅ **Task 0.2**: Decided — yes, and the original finding was half
  wrong. `prompt_id` was already listed; only `effort` was missing, and it
  is documented upstream verbatim for exactly four events. Added to those
  four `input_example`s, sourced from the raw markdown as the refresh
  procedure requires — never from the observed payload alone, which would
  record an undocumented field as if documented.

### Phase 1: The remote tree and its provenance contract

- [x] ✅ **Task 1.1**: Schema in `remote_docs/provenance.py`; every field has
  a validator and a rejection test.
- [x] ✅ **Task 1.2**: `parse_provenance()` returns a typed `ParseResult`,
  never raising, reporting EVERY invalid field.
- [x] ✅ **Task 1.3**: Tree registered — `documentation.trees.remote`, a
  `remote_docs_dir` axis plus `is_remote_docs_path()` on `ProjectLayout`,
  and a config-derived allowance in `markdown_organization`.
  `is_docs_path()` deliberately does NOT claim the tree. Required fixing a
  latent `normalize_path` defect first (Task 1.6).
- [x] ✅ **Task 1.4**: Confirmed by test — a remote doc yields zero sweep
  findings, with a CONTROL test proving the same content in the human tree
  DOES trip them, so the exclusion is real rather than an empty sweep.
- [x] ✅ **Task 1.6**: Fixed `markdown_organization.normalize_path`, which
  matched project markers as bare SUBSTRINGS — `remote-docs/` collapsed to
  `docs/`. Markers now match only at a segment boundary. Found because Task
  1.3's first allowance test passed vacuously.
- [x] ✅ **Task 1.5**: `remote-docs` directory role ships, so every install
  deploys `.claude/rules/remote-docs.md`. A test asserts the human-docs rule
  does not also match the tree.

### Phase 2: Capture and refresh CLI

- [x] ✅ **Task 2.1**: `remote-docs add <url>` — fetch via an injected
  `fetch_fn`, RAW-bytes hash, provenance frontmatter, written to the derived
  path. The written file parses clean with no manual edit.
- [x] ✅ **Task 2.2**: Path derivation is `<host>/<path>.md`, deterministic,
  filesystem-safe, traversal-proof. Where the readable form is lossy a short
  URL digest disambiguates, so `?v=1` and `?v=2` cannot overwrite each
  other. An implied `index` is not lossy.
- [x] ✅ **Task 2.3**: `remote-docs refresh <--path|--all>` with the hash
  short-circuit — unchanged upstream moves the dates only. Refresh reads the
  URL from the file and carries the recorded `licence` across.
- [x] ✅ **Task 2.4**: `remote-docs list` and `check` — read-only,
  CI-suitable, exit 1 when a document is stale OR unreadable (silence must
  not mean "clean" over an unparseable corpus).
- [x] ✅ **Task 2.5**: `write_capture` takes an injected `content_guard`; the
  CLI wires in `SensitiveContentHandler.scan_text`, made public so there is
  one definition of "sensitive". A rejected capture writes nothing, the
  secret-word arm reports only an index, and an UNAVAILABLE guard is
  announced on stderr rather than silently skipping the scan.

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
  `stale_after` date (or `never`) at capture; hash revalidation is
  `refresh`'s `source_sha256` short-circuit. **Version pin is not built** —
  `upstream_version` is schema-ready but nothing populates or compares it,
  because no source vendored here publishes a version to pin to.
- [x] 🟩 **Task 4.2**: `stale_after` written by `add` and `refresh`, which
  re-derives the window from the document's own record so a widened or
  pinned window survives. Nothing mutates a document to mark it stale (D16).
- [x] 🟩 **Task 4.3**: `remote_docs_staleness` — SessionStart advisory for
  documents past `stale_after` or whose provenance no longer parses. Silent
  with no tree; listing capped with a total. **No version cache** unlike
  `contract_staleness`, which caches an external subprocess; this reads
  cheap local files that must not be served stale.
- [ ] ⬜ **Task 4.4**: Ensure a client project's remote tree is treated as
  project-owned — unlike the daemon's vendored contract, a client's
  vendored docs *are* theirs to refresh.

### Phase 5: Routing agents to the local copy

One PreToolUse handler carries both branches; Task 0.1 supplies the
`WebFetch` field name it reads.

- [x] 🟩 **Task 5.1**: `WebFetch` branch. Compares normalised `source_url`s
  (not derived paths, which are lossy). Vendored and fresh → deny with the
  local path; stale → allow, the fetch IS the refresh; unvendored on a
  **declared** domain → allow with the capture command; else silent (D19).
- [x] 🟩 **Task 5.2**: Resident guidance lives in `remote_docs_provenance`'s
  section (one section for one subject; the routing handler is exempt via
  `_EXEMPT_DESPITE_DENYING`, naming it). The index is generated to
  `.claude/REMOTE-DOCS.md` — **outside** the tree, because inside it would
  carry no `source_url` and the gate would deny it, and exempting a
  filename would hole the invariant. Regenerated by `add`/`refresh` and
  rendered from the tree, so a failed capture cannot make it claim a
  document that was never written.
- [x] 🟩 **Task 5.3**: `Read` branch — a stale document is allowed with an
  advisory naming `fetched_at`, `stale_after` and the refresh command, so
  the warning arrives WITH the content and cannot be skipped (D16). An
  `unreviewed` licence rides in the SAME advisory, and fires even when the
  document is fresh: it is a standing fact, not a staleness symptom, and
  the capture default IS the sentinel. Prefix test before any file I/O.

### Phase 6: Migrate the existing vendored contract (dogfood)

- [x] 🟩 **Task 6.1**: Compatibility confirmed, not migrated (D20). The
  schema expresses META's provenance fields including the
  `upstream_version` pin; `docs_bytes`/`event_count`/`refresh_procedure`
  are contract-specific and deliberately have no provenance equivalent.
- [x] 🟩 **Task 6.2**: **Superseded — `contract_staleness` stays** (D20). It
  compares an external tool's VERSION; `remote_docs_staleness` compares a
  date. Retiring it would lose a signal the other does not carry.
- [x] 🟩 **Task 6.4** (new): `remote-docs add --verbatim` forces the raw
  GET, because the contract refresh forbids a summarising fetch — a
  summarised fetch of that exact URL once fabricated an enum value. Also
  fixed the raw GET's `403` against real doc hosts (default urllib
  User-Agent).
- [ ] ⬜ **Task 6.3**: Fold `HOOK-CONTRACT-REFRESH.md`'s procedure into the
  CLI where it is mechanisable, keeping the verification steps that must
  stay human/agent-judged, and clear the currently-firing staleness
  advisory (v2.1.252 → v2.1.259).

### Phase 7: Documentation and acceptance

- [x] 🟩 **Task 7.1**: `CLAUDE/RemoteDocs.md` (schema, fidelity rule, what
  enforces it, the known Bash-write gap), plus the role-summary row and
  per-role section in `CLAUDE/DirectoryRoles.md` and the `CLAUDE/CLAUDE.md`
  routing row.
- [x] 🟩 **Task 7.2**: `docs/guides/REMOTE_DOCS.md` — terse, human-register,
  pointing into the agent tree for depth (R3), plus the `docs/CLAUDE.md`
  routing row.
- [x] 🟩 **Task 7.3**: All three handlers declare `AcceptanceTest`s,
  including a near-miss ALLOW case each where they can deny.
- [x] 🟩 **Task 7.4**: `CLAUDE/UPGRADES/config-changes/v3.61.0.yaml` — all
  five new keys, each `dormant: true` because nothing activates until a
  project captures its first document.

## Success Criteria

- [x] A markdown file in the remote tree without valid provenance frontmatter
  cannot be written via `Write`/`Edit` (`remote_docs_provenance`) and cannot
  pass the commit gate (`remote_docs_commit_gate`, which judges the index so
  a Bash-authored file is caught too).
- [x] `remote-docs add <url>` produces a file whose frontmatter records source
  URL, fetch time, raw content hash, fidelity, licence and `stale_after`,
  with no manual editing.
- [x] `remote-docs refresh` on unchanged upstream content performs no rewrite
  beyond `fetched_at`/`stale_after`, and says so.
- [x] A stale document announces its staleness **in its own contents**, and
  an agent reading it through `Read` is told so at that moment.
- [x] Ordinary documentation-QA checks produce zero findings against vendored
  upstream prose.
- [x] An agent calling `WebFetch` on an already-vendored, fresh URL is
  redirected to the local path.
- [ ] ~~`contracts/claude-code-hooks/` is managed by this subsystem~~ —
  **superseded by D20**: the contract vendors 33 derived schemas, and its
  source doc is deliberately fetched to an untracked path, so there is
  nothing for this subsystem to manage. Clearing its staleness advisory
  needs a verified extraction audit and is left as its own work — upstream
  HAS changed (`e2462deb…` vs META's `d514bf57…`).
- [x] Every new handler ships with tests, an `explain-rule` entry, a
  `HANDLER_REFERENCE.md` entry and an `AcceptanceTest`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00326-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — Phases 1–3: the tree exists, provenance is enforced, capture works.
- Milestone B — Phases 4–5: staleness is measured and surfaced; agents are routed to local copies.
- Milestone C — Phases 6–7: docs and acceptance complete. Phase 6's migration
  was **reassessed rather than performed** (D20): the vendored contract has
  nothing this subsystem can manage.

**Shipped**: four handlers (`remote_docs_provenance`, `remote_docs_routing`,
`remote_docs_commit_gate`, `remote_docs_staleness`), the `remote-docs`
CLI (`add`/`list`/`check`/`refresh`, with `--verbatim`), the generated
index, `documentation.trees.remote` + `documentation.remote`, agent- and
human-tree documentation, and the v3.61.0 config-changes manifest.

**Deliberately still open, neither blocked nor forgotten:**

- **Task 3.8** — record the fetcher's reported `source` so a capture of a
  markdown-serving site can claim `verbatim` honestly. Safe to defer: the
  current behaviour UNDER-claims (`converted`), and `--verbatim` already
  covers work that must quote exactly. Changes the `FetchFn` contract at
  every call site, which is why it is not smuggled in here.
- **Task 6.3** — fold the mechanisable half of the hooks-contract refresh
  into the CLI, and clear the firing staleness advisory. The second half
  needs a verified section-by-section extraction audit against the raw
  markdown; rushing it is precisely the fabrication failure the procedure
  exists to prevent, so it wants its own plan rather than a tail-end task
  here.
