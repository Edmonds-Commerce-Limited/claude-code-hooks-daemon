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

- [x] ✅ **Task 0.1**: Web-tool payloads captured by experiment (Claude Code
  v2.1.259 / daemon v3.61.0); capture re-disabled, raw payloads discarded.
  `WebFetch`'s `tool_response.result` is the fast model's **answer to the
  prompt**, not the page — no route exists from a `WebFetch` to the document
  it fetched. D2 confirmed by measurement, D15 upgraded to fact.
- [ ] ⬜ **Task 0.2**: Decide whether the vendored contract should record that
  real `PreToolUse` payloads carry `effort` and `prompt_id`, which its
  `input_example` omits (candidate finding logged in `PAYLOADS.md`). The
  per-event examples may be illustrative by design; either outcome closes
  the task.

### Phase 1: The remote tree and its provenance contract

- [x] ✅ **Task 1.1**: Schema in `remote_docs/provenance.py`: required
  `source_url` (https only), `fetched_at` (tz-aware ISO), `fidelity`,
  `source_sha256` (64 hex), `licence` (`unreviewed` sentinel, D13),
  `stale_after` (ISO date or `never`, D16); optional `upstream_version`,
  `fetch_method`, `retrieved_by`. Every field has a validator and a
  rejection test.
- [x] ✅ **Task 1.2**: `parse_provenance()` returns a typed `ParseResult`,
  never raising, and reports EVERY invalid field rather than the first.
  Reuses the shared splitter, promoted to a public `split_frontmatter()` so
  the project keeps exactly one frontmatter reader.
- [ ] ⬜ **Task 1.3**: Register the tree: `documentation.trees.remote`
  (default `remote-docs`), a `remote_docs_dir` axis and
  `is_remote_docs_path()` on `ProjectLayout`, and a config-derived step in
  `markdown_organization._check_builtin_paths` beside the agent and human
  trees (D12). **Done when** a `Write` to `remote-docs/x.md` is not denied
  by `R-MARKDOWN-WRONG-LOCATION` with no `extra_allowed_markdown_paths`
  entry in any project.
- [ ] ⬜ **Task 1.4**: Confirm ordinary docs-QA checks never see the tree. It
  sits outside both corpus-collected trees, so no `scope_exclude_globs`
  entry is needed (D10, amended); the remote checks walk it directly in
  Phase 3. **Done when** `docs-qa --sweep` over a fixture remote file
  reports zero findings from the existing eleven checks.
- [ ] ⬜ **Task 1.5**: Add a `remote-docs` directory role to
  `install/directory_role_rules.py` (globs from `layout.remote_docs_dir`)
  so every install deploys `.claude/rules/remote-docs.md`: never hand-author
  here, capture with the CLI, frontmatter is mandatory. **Done when**
  `sync_directory_role_rules` deploys it and the human-docs rule does not
  also match the tree.

### Phase 2: Capture and refresh CLI

- [ ] ⬜ **Task 2.1**: `bin/hooks-daemon remote-docs add <url>` — raw https
  fetch, hash, markdown conversion, provenance frontmatter, write to the
  derived `<domain>/<page-name>.md` path. Injected `fetch_fn` for
  testability, per `install/relay_deploy.py`. `licence` is filled from
  `documentation.remote.known_sources` (domain → licence) or set to
  `unreviewed`; `stale_after` from the resolved staleness policy. **Done
  when** the written file parses clean under the Task 1.2 parser with no
  manual edit.
- [ ] ⬜ **Task 2.2**: Path derivation from URL — deterministic, collision-free,
  filesystem-safe, and readable. The page name need not be the URL slug.
  **Done when** two distinct normalised URLs never derive the same path and
  one URL (after Task 5.1's normalisation) always derives one path.
- [ ] ⬜ **Task 2.3**: `remote-docs refresh <path|--all>` with the hash
  short-circuit: unchanged upstream bumps `fetched_at`/`stale_after` only
  and reports a no-op; changed upstream rewrites body and hash.
- [ ] ⬜ **Task 2.4**: `remote-docs list` and `remote-docs check` — read-only,
  CI-suitable: non-zero exit when any document is past `stale_after`; also
  lists `licence: unreviewed` documents without affecting the exit code
  (D7).
- [ ] ⬜ **Task 2.5**: No `Write` hook sees a CLI write, so run the captured
  body through `sensitive_content`'s own matcher (public patterns and secret
  word list) before writing. **Done when** a fixture page carrying a matching
  term is refused with the handler's index-only wording.

### Phase 3: The check family and its substrate

Checks are pure functions registered declaratively (`CheckSpec(check_id, stage, run)`); a new module is added to the registry with exactly two edits
in `docs_qa/checks/__init__.py`. Tasks 3.1–3.3 are substrate and ship
before 3.4–3.5, which depend on them.

- [ ] ⬜ **Task 3.1**: Port a `docs_qa/paths.py` path classifier modelled on
  `plan_qa/paths.py` (`classify(path) -> kind`), folding in the six
  duplicated `_matches_allowlist` copies so path scoping has ONE home.
  **Done when** `classify` returns `remote` for tree paths, `is_lintable_path`
  (the EDIT dispatch predicate and `docs-qa --lint`) accepts them, and every
  existing check skips `kind == remote` at EDIT and STAGED.
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
- [ ] ⬜ **Task 3.4**: The provenance check at EDIT and STAGED stages, with
  `Severity.BLOCK` for a *newly* invalid document (schema failure, `licence`
  absent). Note the two-key deny rule: BLOCK severity alone does not deny —
  the resolved `check_modes` entry must also be `block`, so ship the config
  default alongside the check. `licence: unreviewed` is ADVISE (D13).
- [ ] ⬜ **Task 3.5**: Respect the house severity convention — BLOCK only when
  this edit made things worse, ADVISE for unchanged-but-violating, silent
  when improving, and always ADVISE at SWEEP (no before/after exists there).
- [ ] ⬜ **Task 3.6**: Rule IDs, `explain-rule` text and `HANDLER_REFERENCE.md`
  entries. Note `explain-rule` text is not a table — it lives in `Rule(...)`
  objects in the PreToolUse handlers, one `Rule` per gate.
- [ ] ⬜ **Task 3.7**: Config: `documentation.trees.remote` plus a new
  `documentation.remote` block (`default_staleness`, `known_sources`). Each
  knob is a mandatory 3-place mechanical change (config `models.py` →
  `docs_qa` `policy.py` in three spots); `extra="forbid"` means the model edit
  cannot be skipped. `Finding` has **no line-number field**, so the
  provenance check names the offending frontmatter key in its message.

### Phase 4: Staleness

- [ ] ⬜ **Task 4.1**: Staleness evaluator supporting time TTL, version pin,
  hash revalidation and pinned/archival, with a project default
  (`documentation.remote.default_staleness`) and per-document `staleness`
  override. **Done when** it resolves every policy to a `stale_after` date
  (or `never`) with a table-driven test per policy.
- [ ] ⬜ **Task 4.2**: Staleness lives in the document as `stale_after`,
  written by `add` and `refresh` (D16). `check` compares it to today and is
  read-only; no command mutates a document to mark it stale. Point-of-use
  delivery is Task 5.3.
- [ ] ⬜ **Task 4.3**: SessionStart sweep reporting stale documents, modelled
  on `contract_staleness.py` including its cache and its self-install vs
  client-install distinction.
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
