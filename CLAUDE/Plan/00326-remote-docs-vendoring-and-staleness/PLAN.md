# Plan 00326: remote docs vendoring and staleness

**Status**: Not Started
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
  tree** with its own contract, distinct from the agent (`CLAUDE/`) and human
  (`docs/`) trees, and excluded from documentation QA checks written for prose
  this project authors and can fix.
- A **provenance frontmatter schema** — `source_url`, `fetched_at`,
  `fidelity`, `source_sha256`, plus optional `upstream_version`, `staleness`
  and `licence` — that is machine-checkable and travels with the document.
- A **capture and refresh CLI** that fetches raw, hashes, converts to
  markdown, and writes the frontmatter, so the procedure lives in a script
  rather than in prose an agent re-derives each time.
- A **write-time gate** that makes a file in the remote tree without valid
  provenance frontmatter impossible to commit.
- **Staleness surfaced at the point of use** (in-band in the document) as
  well as in the session-start sweep, with per-document policy and a
  content-hash short-circuit that makes revalidation cheap.
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
- Not a replacement for `WebSearch`; discovery stays a network operation.

## Key design decisions

The eleven decisions this plan rests on, each with its reasoning, live in
[DECISIONS.md](DECISIONS.md). The four that most shape the work:

- **D2/D3** — raw fetch is the canonical capture path, and every document
  records a `fidelity` field. Without these this is a cache; with them it is
  a citable corpus.
- **D5** — staleness is surfaced *in the document*, because the equivalent
  session-start advisory in this repo demonstrably rotted.
- **D10** — path exclusion is global across checks, so it cannot by itself
  give docs QA a remote-docs subset; per-check path scoping does not exist
  today and is new capability.
- **D11** — the web-tool payload shape is settled by capture, not assumption.

## Open questions

- **Does the PostToolUse payload for `WebFetch` carry the fetched content, or
  only status/metadata?** Not answerable from the vendored contract, which is
  organised per EVENT not per TOOL and documents no web-tool payload at all;
  the daemon's own schema types `tool_response` as a deliberately
  shape-agnostic object. No captured fixture exists. **Task 0.1 settles it
  empirically** — it is a ~2-minute experiment and it gates Task 5.3 only.
  Fallback if the response is status-only:
  `TranscriptReader.get_tool_result_text_by_id(tool_use_id)`, which pairs the
  `tool_use_id` PostToolUse *does* carry to its result text.
- Should vendored third-party prose be **domain-allow-listed** to keep
  licence-incompatible material out of the repository, or is a `licence`
  field and reviewer judgement sufficient?
- Does the remote tree belong at `docs/remote/` (discoverable, but inside the
  human tree) or at a top-level `remote-docs/` (clean inheritance)? D1 settles
  the *registration*; the *path* is still open — but the cost side is now
  known: `docs/remote/` needs **no** markdown-location config, since
  `markdown_organization` does a plain prefix test on `docs/` with no
  allowlist beneath it. Only a new *top-level* directory would trip
  `R-MARKDOWN-WRONG-LOCATION`.

## Tasks

### Phase 0: De-risk before building

- [ ] ⬜ **Task 0.1**: Settle the `WebFetch`/`WebSearch` payload question by
  experiment, not by assumption. Enable `daemon.payload_capture` for
  `PreToolUse`/`PostToolUse`, restart the **daemon** (not Claude Code),
  perform one `WebFetch` and one `WebSearch`, and read
  `untracked/payload-capture/PostToolUse.jsonl`. Record the verbatim
  `tool_input` and `tool_response` shapes in a supporting document —
  they are currently undocumented anywhere in this repository, and every
  routing task depends on the field names.
- [ ] ⬜ **Task 0.2**: Feed the result back into the vendored contract if the
  web tools prove to have documented payload shapes worth recording.

### Phase 1: The remote tree and its provenance contract

- [ ] ⬜ **Task 1.1**: Define the frontmatter schema as a typed, validated
  structure — required (`source_url`, `fetched_at`, `fidelity`,
  `source_sha256`) and optional (`upstream_version`, `staleness`,
  `licence`, `fetch_method`, `retrieved_by`) fields, with `fidelity`
  constrained to `verbatim | converted | summarised`.
- [ ] ⬜ **Task 1.2**: Implement the provenance parser, reusing
  `utils/markdown_format.py::_split_frontmatter` rather than adding a
  second frontmatter reader. Malformed frontmatter must be a typed
  result, never an exception that escapes.
- [ ] ⬜ **Task 1.3**: Register the remote tree in configuration
  (`documentation.trees.remote`) with its path, resolving the open
  question on `docs/remote/` vs `remote-docs/`.
- [ ] ⬜ **Task 1.4**: Keep ordinary docs-QA checks off vendored upstream prose
  **without** blinding the remote-docs checks to it. `scope_exclude_globs`
  drops a file from the corpus for *every* check, including new ones, so it
  cannot do this alone. Follow the proven `source-tree-markdown` pattern:
  exclude the remote tree from the corpus, and have the remote-docs checks
  do their own pruned walk over it (`os.walk` with in-place `dirnames[:]`
  pruning, re-using the shared exclusion primitives rather than
  re-deriving them).
- [ ] ⬜ **Task 1.5**: Add an `extra_allowed_markdown_paths` entry **only if** a
  top-level path is chosen over `docs/remote/` — a `docs/` subdirectory needs
  no allowance.

### Phase 2: Capture and refresh CLI

- [ ] ⬜ **Task 2.1**: `bin/hooks-daemon remote-docs add <url>` — raw https
  fetch, hash, markdown conversion, provenance frontmatter, write to the
  derived `<domain>/<page-name>.md` path. Injected `fetch_fn` for
  testability, per `install/relay_deploy.py`.
- [ ] ⬜ **Task 2.2**: Path derivation from URL — deterministic, collision-free,
  filesystem-safe, and readable. The page name need not be the URL slug.
- [ ] ⬜ **Task 2.3**: `remote-docs refresh <path|--all>` with the hash
  short-circuit: unchanged upstream bumps `fetched_at` only and reports a
  no-op.
- [ ] ⬜ **Task 2.4**: `remote-docs list` and `remote-docs check` (staleness
  report, non-zero exit when stale), suitable for CI.
- [ ] ⬜ **Task 2.5**: Route captured content through a path that the existing
  secret-scanning surface can see, so an authenticated page's contents
  cannot be vendored unexamined.

### Phase 3: The check family and its substrate

Checks are pure functions registered declaratively (`CheckSpec(check_id, stage, run)`); a new module is added to the registry with exactly two edits
in `docs_qa/checks/__init__.py`. Two `plan_qa` primitives that `docs_qa`
lacks are worth porting *before* adding an eleventh scattered scope
predicate.

- [ ] ⬜ **Task 3.1**: Port a `docs_qa/paths.py` path classifier modelled on
  `plan_qa/paths.py` (`classify(path) -> kind`), folding in the six
  duplicated `_matches_allowlist` copies so path scoping has ONE home. This
  is also the cheapest place to thread per-check path scoping, which does
  not exist today.
- [ ] ⬜ **Task 3.2**: Port a `document_rule_checks`-style registration adapter
  (`docs_qa/checks/common.py`) so one rule function serves multiple stages,
  instead of the `_run_edit`/`_run_staged`/`_run_sweep` triplication now
  repeated across all eleven check modules.
- [ ] ⬜ **Task 3.3**: Add frontmatter to `DocRecord`, **bump
  `_CACHE_SCHEMA_VERSION` (2 → 3)**, and wire extraction into *both*
  `build_and_save_corpus` and `refresh_own_record` — they build `DocRecord`
  independently and must stay in sync. Without the version bump a warm cache
  silently serves records with the new field empty and every dependent check
  reports clean.
- [ ] ⬜ **Task 3.4**: The provenance check itself, at EDIT and STAGED stages,
  with `Severity.BLOCK` for a *newly* invalid document. Note the two-key
  deny rule: BLOCK severity alone does not deny — the resolved
  `check_modes` entry must also be `block`, so ship the config default
  alongside the check.
- [ ] ⬜ **Task 3.5**: Respect the house severity convention — BLOCK only when
  this edit made things worse, ADVISE for unchanged-but-violating, silent
  when improving, and always ADVISE at SWEEP (no before/after exists there).
- [ ] ⬜ **Task 3.6**: Rule IDs, `explain-rule` text and `HANDLER_REFERENCE.md`
  entries. Note `explain-rule` text is not a table — it lives in `Rule(...)`
  objects in the PreToolUse handlers, one `Rule` per gate.
- [ ] ⬜ **Task 3.7**: Any new config knob is a mandatory 3-place mechanical
  change (`config/models.py` → `docs_qa/policy.py` in three spots);
  `extra="forbid"` means the model edit cannot be skipped. Also note
  `Finding` carries **no line-number field** — `path` is a bare relative-path
  string — so a per-line citation needs either a new field or a message
  convention.

### Phase 4: Staleness

- [ ] ⬜ **Task 4.1**: Staleness evaluator supporting time TTL, version pin,
  hash revalidation and pinned/archival, with a project default and
  per-document override.
- [ ] ⬜ **Task 4.2**: In-band staleness banner — `remote-docs check` marks a
  stale document in its own frontmatter/body so any agent reading it sees
  the warning at the point of use (D5).
- [ ] ⬜ **Task 4.3**: SessionStart sweep reporting stale documents, modelled
  on `contract_staleness.py` including its cache and its self-install vs
  client-install distinction.
- [ ] ⬜ **Task 4.4**: Ensure a client project's remote tree is treated as
  project-owned — unlike the daemon's vendored contract, a client's
  vendored docs *are* theirs to refresh.

### Phase 5: Routing agents to the local copy

- [ ] ⬜ **Task 5.1**: PreToolUse handler on `WebFetch`: URL already vendored
  and fresh → deny with the local path; vendored but stale → allow (the
  fetch is the refresh); not vendored → allow with a capture hint.
- [ ] ⬜ **Task 5.2**: `get_claude_md()` guidance so agents learn the corpus
  exists without per-session prompting, plus a generated index so one
  grep answers "do we already have docs for X?".
- [ ] ⬜ **Task 5.3**: *(Contingent on the open question)* PostToolUse
  offer-to-vendor after a `WebFetch`. Drop this task if the payload does
  not carry fetched content.
- [ ] ⬜ **Task 5.4**: Decide whether `WebSearch` warrants an advisory at all —
  a query is not a URL, so matching is fuzzy and the false-positive cost
  may exceed the benefit.

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
  contract, the schema and the fidelity rule.
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
  URL, fetch time, raw content hash and fidelity, with no manual editing.
- [ ] `remote-docs refresh` on unchanged upstream content performs no rewrite
  beyond `fetched_at`, and says so.
- [ ] A stale document announces its staleness **in its own contents**, not
  only in a report.
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
