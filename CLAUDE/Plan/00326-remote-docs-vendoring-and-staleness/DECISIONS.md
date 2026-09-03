# Plan 00326 — Design decisions

The decisions PLAN.md is built on, with the reasoning that produced each.
Alternatives considered and rejected: [BRAINSTORM.md](BRAINSTORM.md).
Supporting evidence: [subagent-reports/](subagent-reports/).

| #   | Decision                                                                                                                                                          | Reasoning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Remote docs are a **third registered tree**, not a `docs/` subdirectory                                                                                           | `documentation.trees` already models documentation as named trees with distinct contracts (`agent: CLAUDE`, `human: docs`). A subdirectory of the human tree inherits rules written for prose this project owns, which then have to be excluded back out.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| D2  | **Raw fetch is the canonical capture path**; `WebFetch` output is `fidelity: summarised` at best                                                                  | A summarising fetch layer fabricated contract detail in this very repository during the Plan 00271 audit, inventing a `permissionDecision: "escalate"` value absent from the raw document.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| D3  | `fidelity` is a **required** frontmatter field                                                                                                                    | A summary quoted back as a citation is the exact failure this system exists to prevent. An optional field would be omitted precisely when it matters.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| D4  | `source_sha256` of the **raw** bytes is recorded                                                                                                                  | Makes "did it actually change?" answerable in one cheap fetch, and lets a matching hash refresh `fetched_at` for free. This short-circuit is what makes frequent revalidation affordable — the vendored contract's refresh procedure already relies on it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| D5  | Staleness is **visible in the document**, not only in a report                                                                                                    | The prior art's session-start-only advisory demonstrably rotted: it is firing right now (installed v2.1.259 vs audited v2.1.252) and has been skipped in favour of other work. Frontmatter travels with the file, so the warning can arrive at the point of use.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| D6  | Staleness policy is **per document with a project default**                                                                                                       | Time TTL always applies but is often wrong in both directions; version pinning is precise but only where a version exists; some snapshots are deliberately frozen evidence.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| D7  | The frontmatter gate **blocks**; the staleness signal **advises**                                                                                                 | Missing provenance is a fact, checkable offline, with no legitimate exception. Staleness is a judgement a human may knowingly accept.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| D8  | The existing vendored contract is **migrated onto** the subsystem                                                                                                 | A generalisation that cannot subsume its own motivating case is not general. Migration is the acceptance test for the whole plan.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| D9  | Build the check family **inside `docs_qa`**, but port two `plan_qa` primitives first                                                                              | The family needs `DocCorpus`, `ProjectLayout` and the `documentation:` config block, which only `docs_qa` has. But `plan_qa` has the two things a path-scoped family needs and `docs_qa` lacks: a `paths.py` path classifier, and a `document_rule_checks` multi-stage registration adapter. `docs_qa`'s scope logic is currently scattered across `is_in_scope` / `is_module_doc_path` / `is_lintable_path` / `matches_scope_exclude` plus six copies of `_matches_allowlist`, and that scatter has already caused one real drift bug (recorded in `is_lintable_path`'s own docstring).                                                                                                                                                                                                                                                                                                                                                                                   |
| D10 | Remote-tree files are **corpus-excluded but walked directly** by the remote-docs checks                                                                           | `scope_exclude_globs` drops a file from the corpus for *every* check, so using it to silence ordinary checks on upstream prose would equally blind the new remote-docs checks. `source-tree-markdown` already does its own pruned `os.walk` for exactly this reason, re-using the shared exclusion primitives rather than re-deriving them. **Amended below**: exclusion alone also removes the file from EDIT dispatch.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| D11 | The payload question is settled by **capture, not assumption**                                                                                                    | The vendored contract is organised per EVENT, not per TOOL, and documents no `WebFetch`/`WebSearch` payload at all; the daemon's schema types `tool_response` as deliberately shape-agnostic; no captured fixture exists anywhere in the repo. Guessing field names would build the routing layer on invented shape. **Narrowed below**: only the `tool_input` field names still gate anything.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| D12 | The tree is a **top-level `remote-docs/`**, registered as `documentation.trees.remote` (default `remote-docs`); never a `docs/` subdirectory                      | Three costs of `docs/remote/` are structural, not configurable. The deployed human-docs role rule (`.claude/rules/human-docs.md`, `paths: docs/**/*.md`) would inject "keep it terse, summarise, point into the agent tree" on every capture write — the opposite of verbatim capture — and rule-file globs cannot be negated. `ProjectLayout.is_docs_path` and corpus collection would classify the files as human prose, so every existing check and every future one would need excluding back out. And D1's own text already said "not a `docs/` subdirectory" — the path was never genuinely open. The one cost of a top-level path (a markdown-location allowance) disappears because `markdown_organization` already derives its `CLAUDE/` and `docs/` allowances from `documentation.trees` through `ProjectLayout`; a `remote` axis gives every project the allowance from the registration itself, with no `extra_allowed_markdown_paths` entry to keep in sync. |
| D13 | `licence` is a **required** field with an explicit `unreviewed` sentinel; **no blocking domain allow-list**; `unreviewed` advises                                 | D3's argument transfers whole: an optional licence field is omitted precisely when the material is dubious. D7's split sets the severity: an absent declaration is a fact (block); licence compatibility is a judgement a reviewer may knowingly accept (advise). A blocking allow-list would tax every first capture from a new domain, and would be bypassed by the same reviewer it is meant to protect. A `documentation.remote.known_sources` domain → licence map pre-fills the field so the judgement is recorded once per source rather than once per file.                                                                                                                                                                                                                                                                                                                                                                                                        |
| D14 | **No `WebSearch` advisory** (the drafted Task 5.4 is dropped)                                                                                                     | A query is not a URL, so matching is fuzzy and a false positive costs trust in every later advisory. The deterministic checkpoint already sits downstream: a search that leads to a vendored page ends in a `WebFetch`, which Task 5.1 intercepts by URL. Task 5.2's CLAUDE.md guidance and generated index cover "search the corpus first" without a hook. Revisit only on a field-observed miss.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| D15 | **No PostToolUse offer-to-vendor** (the drafted Task 5.3 is dropped, and no transcript fallback is built)                                                         | The contingency on the payload shape was a false dependency: no task needs the fetched content. D2 makes the CLI's own raw fetch the canonical capture, so a `WebFetch` payload could only ever yield `fidelity: summarised` material, and any route to it — the payload or `TranscriptReader.get_tool_result_text_by_id` — would be building the non-canonical path. The offer itself needs only the URL, which the PreToolUse branch (Task 5.1) already has; a second hint after the fetch would be two hints for one fetch.                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| D16 | Point-of-use staleness is a **`stale_after` frontmatter field plus a `Read`-time advisory**; `check` is read-only and nothing mutates a document to mark it stale | A `check` that writes a banner has the same rot as the report — the banner appears only if someone runs the command. A SessionStart handler mutating tracked files has no precedent and dirties the working tree on every session. A `stale_after` date computed at capture from the resolved policy makes staleness readable by any consumer (tool, `cat`, human) with no knowledge of the policy, and a PreToolUse `Read` advisory on the tree (prefix fast path, as `secret_file_guard` does) fires every time the file is read — the warning arrives with the content, so it cannot be skipped.                                                                                                                                                                                                                                                                                                                                                                        |

## D17 — the enforcement surfaces are handlers, not a `docs_qa` check family

**Supersedes the structural half of D9, and makes D10's amendment moot.**
Taken during implementation, on evidence the earlier decision did not have.

D9 chose to build the remote-docs checks inside `docs_qa`, because that is
where `DocCorpus`, `ProjectLayout` and the `documentation:` config block
live. Implementing Phases 1 and 2 showed the premise does not hold:

- **The write-time gate needs no corpus.** It judges ONE file's content at
  write time, which is exactly a `PreToolUse` handler's job. Routing it
  through `docs_qa` means first solving D10's dispatch problem — the EDIT
  handler keys on `is_lintable_path`, which is derived from corpus scope,
  and the remote tree is deliberately outside it.
- **The staleness sweep needs no corpus either.** `store.check_staleness`
  already walks the tree directly and parses provenance, which is all the
  sweep reports on.
- **The corpus arguments were about avoiding a second scope predicate**, but
  D12 removed the need for one: a top-level tree is never corpus-collected,
  so nothing has to be excluded back out. Task 1.4 proves this by test.

So the ports D9 recommended — `docs_qa/paths.py` and a
`document_rule_checks` adapter — would be paid for entirely by this plan and
used by nothing in it. They remain a good idea for `docs_qa`'s own sake and
should be filed separately rather than smuggled in here.

What this costs: the remote-docs rules do not get `check_modes` severity
tuning for free, and a project wanting to soften the gate configures the
handler instead. That is the ordinary handler contract, and D7 already says
this gate blocks rather than advises, so the tuning was never load-bearing.

## Amendments to D1–D11

- **D1 (under-applied, not wrong)** — its text already excluded a `docs/`
  subdirectory; PLAN.md nevertheless listed the path as open, and
  BRAINSTORM's triage line placed the tree at `docs/remote/`. D12 makes the
  implication explicit. BRAINSTORM is superseded on that line, as its own
  header says it is wherever the two disagree.
- **D10 (omission)** — "corpus-excluded but walked directly" is half the
  story. The EDIT handler dispatches on `is_lintable_path`, which is derived
  from corpus scope, so an excluded path never reaches the frontmatter gate
  at all; and `staged_context` applies no scope, so the ordinary checks
  would judge upstream prose at commit time. Task 3.1's `classify()` must
  therefore both admit `remote` paths to EDIT/STAGED dispatch and exclude
  them from every existing check. Without this the single highest-value rule
  (BRAINSTORM D4) never fires. With a top-level path (D12) the corpus
  exclusion itself is structural — the tree is never collected — so no
  `scope_exclude_globs` entry exists to drift.
- **D11 (narrowed)** — capture still settles the `tool_input` field names,
  which Task 5.1 keys on; the `tool_response` content question no longer
  gates any task (D15).

## Config the decisions imply

```yaml
documentation:
  trees:
    agent: CLAUDE
    human: docs
    remote: remote-docs        # D12 — new axis, default shown
  remote:                      # new block
    default_staleness: 90d     # D6/D16 — resolved into stale_after at capture
    known_sources: {}          # D13 — domain -> licence, pre-fills the field
  qa:
    check_modes:
      remote-provenance: block # D7 — the two-key deny rule needs this default
```

No `extra_allowed_markdown_paths` entry and no `scope_exclude_globs` entry:
both allowances derive from the tree registration.

## Consequences worth restating

**D2 + D3 together are the point of the system.** Without them this is a
cache; with them it is a citable corpus. The distinction only survives if
`fidelity` is recorded at capture time by the tool that did the capturing —
a field a human fills in afterwards records an intention, not a fact. D13
extends the same reasoning to `licence`.

**D5 is a response to observed failure, not a preference.** The design that
would otherwise be natural — a session-start staleness sweep — is precisely
the design already shown to rot in this repository. D16 is the mechanism
that honours it without a second thing that can rot.

**D10 is the non-obvious one.** The intuitive reading of "give docs QA a
remote-docs subset delineated by path" is that path exclusion already
provides it. It does not: exclusion is global across checks, and there is no
per-check path scoping anywhere in `docs_qa` today. Adding one is a genuinely
new capability, and D9 puts it in the one place where it need only be
threaded once — which is also where the D10 amendment is fixed.

**D15 removes a whole class of handler.** Nothing in this plan reads a web
tool's `tool_response`, so the only new hook surface is one PreToolUse
handler with two branches (`WebFetch`, `Read`), and Phase 0 shrinks to
confirming two input field names.

## D20 — `--verbatim` is demandable, and Phase 6 is narrower than drafted

Three findings, taken while assessing Phase 6 against the real vendored
contract rather than against the plan's description of it.

**1. Verbatim had to become demandable.** D18 made `agent-browser` the
default, which records `fidelity: converted`. But
`docs/guides/HOOK-CONTRACT-REFRESH.md` has a non-negotiable rule — RAW fetch
only — because during the Plan 00271 audit a summarising fetch of that exact
URL FABRICATED a `permissionDecision: "escalate"` value appearing nowhere in
the raw text. For that work "close enough" is the failure mode. The corpus
never lied (`converted` said so), but there was no way to *demand* the
response body. `remote-docs add --verbatim` now forces the raw GET, probes
no browser, and issues no fallback warning — using the GET is the CHOICE
there, not a degradation.

**2. The raw GET was broken against real documentation hosts.** It sent
the default `Python-urllib/3.x` User-Agent and got `403 Forbidden` from
code.claude.com — the very host the contract procedure fetches, which works
because it uses `curl`. So the documented procedure worked while our
fetcher did not. Now sends an honest identifying User-Agent (not a browser
impersonation: a host that wants to refuse automated capture should be able
to) and an `Accept` preferring markdown.

**3. Phase 6's migration is mostly inapplicable, and this is the finding
rather than a failure.** The vendored contract is 33 hand-derived JSON
schemas; `META.json` records the provenance of the SOURCE DOC they were
derived from, and that doc is deliberately fetched to an untracked path
each refresh rather than stored. So:

- **Task 6.1 is a compatibility check, not a migration.** The provenance
  schema does express META's provenance fields — `docs_url` → `source_url`,
  `fetch_date` → `fetched_at`, `docs_sha256` → `source_sha256`,
  `last_audited_claude_code_version` → `upstream_version`, confirming the
  version-pin field is the right shape. `docs_bytes`, `event_count` and
  `refresh_procedure` have no provenance equivalent and should not get one:
  they are contract-specific, not provenance.
- **Task 6.2 should NOT retire `contract_staleness`.** It answers "has
  Claude Code moved on since we audited?" — a VERSION comparison against an
  external tool. `remote_docs_staleness` answers "is this document past its
  date?". Retiring the former would lose a signal the latter does not
  carry. Version-pin staleness is exactly the Task 4.1 gap left
  schema-ready and unimplemented.
- **Vendoring the 317 KB source doc into git is not obviously right** and
  is left to a human: the refresh procedure deliberately fetches it to
  `untracked/`, and only its hash is durable.

**Live finding worth acting on separately:** the current upstream hash is
`e2462deb…`, META records `d514bf57…`. Upstream has changed since the
2026-09-01 audit. Bumping the version without performing the verified
extraction is precisely what the procedure forbids, so this is reported,
not done.

**Evidence for the deferred Task 3.8.** The `agent-browser` capture of that
URL produced a sha256 IDENTICAL to the raw GET (`e2462deb…`), with
`source: accept-markdown` — upstream served markdown and the browser passed
it through unchanged. So `converted` is over-cautious for that source, and
recording `source` would let a capture claim `verbatim` honestly when it is
one. Measured on one URL, so treat it as evidence rather than a rule.

## D19 — the capture nudge is scoped to DECLARED documentation domains

**Amends Task 5.1**, which said an unvendored URL gets "a capture hint"
unconditionally once the tree exists.

Unconditional is wrong, and the reason is the advisory-decay problem. Most
`WebFetch` calls are not documentation: a GitHub issue, a Stack Overflow
answer, a status page, a blog post. A hint on all of them is wrong most of
the time, and an advisory that is usually wrong is one people learn to skim
past — at which point it also stops working for the cases where it was
right.

So the project declares which domains are documentation sources, and only
those are nudged. Everything else is left alone entirely.

**The declaration reuses `documentation.remote.known_sources`** rather than
adding a parallel list. A domain you have recorded a licence for IS a domain
you vendor from, and two lists meaning nearly the same thing drift apart —
the failure this project's SSoT rules exist to prevent. To declare a source
before its licence is reviewed, record the `unreviewed` sentinel as the
value; that is already a legal licence string and already triggers the
review advisory.

**Declaration governs NUDGING, not ROUTING.** A URL we already hold a fresh
copy of is still denied with the local path even if its domain was never
declared — we demonstrably have the document, so the declaration adds
nothing. The two concerns are separate: routing is about a copy that exists,
nudging is about one that should.

The host match is EXACT, never a suffix: `docs.example` must not match
`evil-docs.example`. Declaring nothing opts out of nudging entirely without
disabling routing, so the feature has an off switch that is not the
handler's `enabled` flag.

## D18 — capture through `agent-browser read`, with a probed binary and an HTTPS fallback

**Amends D2**, which named a raw HTTPS GET as the canonical capture. The GET
remains the fallback and remains the only fetcher that may claim `verbatim`.

`agent-browser read <url>` is preferred because it is *documentation-aware*
in a way a generic GET is not: it negotiates `Accept: text/markdown`, retries
the URL with `.md` appended, and consults the nearest ancestor `llms.txt`
before falling back to text extracted from HTML. Vendoring docs as markdown
is the whole point of the tree, so a fetcher that asks for markdown beats one
that takes whatever a server hands an anonymous client. Measured here: a docs
page captured 317 KB of structured markdown via `read`, against raw HTML via
the GET.

Three findings shaped the implementation, each of which contradicted an
initial assumption:

- **`read <url>` does NOT render JavaScript.** It is an HTTP fetch plus
  extraction. The first version of this work justified the default by
  claiming it rendered JS-heavy sites; that was wrong. Rendering requires
  `open` first, which is a different shape and is not what this does. A
  client-side-rendered page still captures thinly, and that limit is
  recorded rather than papered over.
- **The binary is not always spelled `agent-browser`.** Environments that
  mandate an explicit browser mode ship suffixed wrappers and make the bare
  name exit non-zero while leaving it on `PATH`. Presence therefore cannot
  decide usability. A cheap `--version` probe can, costs no browser launch,
  and keeps this environment-agnostic: candidates are tried in order and the
  first that actually runs is used, so a plain upstream install picks
  `agent-browser` and a mode-enforcing one picks a wrapper, with no
  detection of either.
- **A read starts a real browser process.** Without an explicit
  `close --all` every capture leaks one until an idle timeout fires.

**Fidelity is `converted`, never `verbatim`.** The content is extracted and
normalised rather than returned as the response body, so claiming verbatim
would be the precise overclaim D3 exists to prevent — even when upstream
served markdown and the text looks untouched. `fetch_method` records which
binary produced it, and records the one that actually ran rather than the
first candidate, because provenance naming a tool that never executed is
worse than none.

**Losing the browser degrades, it does not fail.** No usable binary — absent
or present-but-unusable, treated identically — falls back to the GET and
prints a warning naming `agent-browser` and `PATH`. The warning is
deliberately free of any container or project layout, because this daemon
installs into arbitrary projects and advice that names one environment's
Dockerfile is wrong everywhere else. Only the fetching actions (`add`,
`refresh`) resolve a fetcher, so `list` and `check` never warn about a tool
they were never going to use.

**Deferred, not dropped:** `read --json` also reports a `source`
(`accept-markdown`, `html-fallback`, ...), which is a sharper provenance
signal than the binary name — it distinguishes upstream's own markdown from
our extraction of their HTML. Recording it would change the `FetchFn`
contract from `str -> bytes` everywhere, so it is left for a later task
rather than smuggled in here.
