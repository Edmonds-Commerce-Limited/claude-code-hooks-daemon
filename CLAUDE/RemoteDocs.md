# Remote docs: vendoring upstream documentation

The remote-docs tree holds documentation **captured from upstream and stored
locally**, so the project and its agents can read and grep it cheaply, offline,
and without a network round trip.

This file owns the depth for the tree's contract, its provenance schema, and
the fidelity rule. Per-handler options live in
[`docs/guides/HANDLER_REFERENCE.md`](../docs/guides/HANDLER_REFERENCE.md);
per-decision reasoning lives in the Plan 00326 folder.

## The rule in one sentence

**Every file in the tree declares where it came from, and never claims to be
more faithful to upstream than it is.**

## Why the tree is top-level

`remote-docs/` is a top-level directory, never `docs/remote/`. Three costs of
nesting it are structural rather than configurable:

- The deployed human-docs role rule (`docs/**/*.md`) instructs "keep it terse,
  summarise, point into the agent tree" — the exact opposite of verbatim
  capture — and rule-file globs cannot be negated.
- `ProjectLayout.is_docs_path` and docs-QA corpus collection would classify
  captured upstream prose as our own human-register documentation, so every
  existing check and every future one would need excluding back out.
- Registering it as its own axis (`documentation.trees.remote`) gives every
  project the markdown-location allowance from the registration itself, with no
  `extra_allowed_markdown_paths` entry to keep in sync.

The tree is **project-owned**: unlike the daemon's own vendored hook contract,
a project's vendored docs are theirs to refresh.

## The provenance schema

Every document opens with YAML frontmatter:

| Field              | Required | Meaning                                                     |
| ------------------ | -------- | ----------------------------------------------------------- |
| `source_url`       | yes      | Where it came from. Without this, nothing can be refreshed. |
| `fetched_at`       | yes      | When it was captured (ISO 8601, timezone-aware).            |
| `fidelity`         | yes      | `verbatim` \| `converted` \| `summarised` — see below.      |
| `source_sha256`    | yes      | Hash of the fetched bytes, so refresh can no-op.            |
| `licence`          | yes      | SPDX identifier, or the `unreviewed` sentinel.              |
| `stale_after`      | yes      | Date the freshness window expires, or the `never` sentinel. |
| `fetch_method`     | no       | Which fetcher produced it.                                  |
| `upstream_version` | no       | Version pin, where upstream publishes one.                  |

`stale_after` is a **date in the document**, not a policy someone must know
about: any consumer — a tool, `cat`, a human — can see it without understanding
the configuration that produced it.

## The fidelity rule

`fidelity` is what separates a citable corpus from a cache, and it is the field
a naive schema omits.

- **`verbatim`** — the stored bytes ARE the response body.
- **`converted`** — the text was extracted or normalised from the response
  (rendered DOM, HTML-to-markdown, reflowed).
- **`summarised`** — a model rewrote it. Never quotable as upstream.

**No component may claim a fidelity on another's behalf.** The fetcher declares
its own, and `capture()` records what it is told rather than assuming. A
browser capture records `converted` even when upstream served markdown and the
text looks untouched, because it passed through an extraction step.

This is not theoretical caution. During the Plan 00271 hook-contract audit, a
**summarising fetch layer fabricated** a `permissionDecision: "escalate"` value
that appears nowhere in the raw text. A fabricated value vendored with
`fidelity: verbatim` would be enforced against the daemon as if documented.

Work that must quote upstream exactly should demand raw bytes:

```bash
bin/hooks-daemon remote-docs add <url> --verbatim
```

## Capture, never authoring

```bash
bin/hooks-daemon remote-docs add <url>       # capture a page
bin/hooks-daemon remote-docs list            # what do we hold?
bin/hooks-daemon remote-docs check           # what needs attention?
bin/hooks-daemon remote-docs refresh --all   # re-fetch everything
```

`add` prefers `agent-browser read` when a usable `agent-browser` is on `PATH`,
because it negotiates `Accept: text/markdown`, retries with `.md`, and consults
the nearest ancestor `llms.txt` — better source material for vendoring
documentation than whatever bytes a server hands an anonymous client. Without
it, capture falls back to a plain HTTPS GET and says so.

Note `agent-browser read <url>` does **not** execute JavaScript; it is an HTTP
fetch plus extraction. A client-side-rendered page still captures thinly.

`refresh` re-fetches from the recorded `source_url`, carries the licence review
across, and no-ops when `source_sha256` is unchanged — only `fetched_at` and
the recomputed window move.

**Hand-editing a vendored document is blocked**, because rewording it silently
falsifies its recorded `fidelity`.

## The generated index

`.claude/REMOTE-DOCS.md` lists every vendored document with its source URL and
dates, so one grep answers "do we already have docs for X?". It is regenerated
on every `add` and `refresh`, and rendered from the tree — a failed capture
cannot make it claim a document that was never written.

It lives **outside** the tree deliberately: inside, it would carry no
`source_url` of its own and the provenance gate would deny it, and exempting a
filename from that gate would hole the invariant.

## What enforces this

| Surface                                | Enforces                                                                                                 |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `remote_docs_provenance` (PreToolUse)  | No `Write`/`Edit` into the tree without valid provenance. **Blocks.**                                    |
| `remote_docs_commit_gate` (PreToolUse) | No `git commit` staging an unattributed document, whatever route it took to disk. **Blocks.**            |
| `remote_docs_routing` (PreToolUse)     | Routes a `WebFetch` to a fresh vendored copy; warns at `Read` time about a stale or unreviewed document. |
| `remote_docs_staleness` (SessionStart) | Reports documents past `stale_after` or with unparseable provenance. **Advises.**                        |

**Why the split blocks and advises differently:** missing provenance is a
FACT — checkable offline, with no legitimate exception. Staleness is a
JUDGEMENT a human may knowingly accept: an upstream that has not changed in a
year is not a problem, and a pinned archival snapshot is stale on purpose.

**The Bash-write route is covered, but not at write time.** A heredoc or
redirect into the tree never reaches `remote_docs_provenance`, which keys on
`Write`/`Edit`. The commit gate judges the git index instead, so such a
document cannot enter history; the session-start sweep reports one sitting in
the working tree. What genuinely remains uncovered is the window between a
Bash write and the next commit or session.

## Configuration

```yaml
documentation:
  trees:
    remote: remote-docs        # tree location
  remote:
    default_staleness_days: 90 # freshness window applied at capture
    known_sources:             # domain -> licence
      docs.python.org: PSF-2.0
      docs.example.com: unreviewed
```

`known_sources` does two jobs. It pre-fills the `licence` field so the review
is recorded once per SOURCE rather than once per file, and it **declares which
domains are documentation sources** — which is what scopes the capture nudge.
A `WebFetch` to a declared domain that is not yet vendored gets a hint to
capture it; every other domain is left silent, because an advisory that is
usually wrong is one people learn to skim past.

Declaring nothing turns nudging off without disabling routing to copies you
already hold. Host matching is exact, never a suffix.
