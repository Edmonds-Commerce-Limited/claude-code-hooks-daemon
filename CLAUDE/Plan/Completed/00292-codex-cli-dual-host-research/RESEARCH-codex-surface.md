# Research: OpenAI Codex CLI's hooks/extension surface (as of 2026-08-30)

**Scope**: what Codex CLI's hooks system actually is today, from primary/near-primary
sources. Written for Plan 00292 (dual-host research). No code changes.

**Big caveat up front (read this before trusting any payload-schema detail below)**:
almost every fact below was obtained via the `WebFetch` tool, which does not return raw
page text — it summarizes fetched HTML through a small auxiliary model. That model's
training data is saturated with **Claude Code's own hook documentation** (the exact
product this research session itself runs inside, per this project's own `CLAUDE.md`).
Codex's hooks system is independently confirmed (see §2) to be a **deliberate,
acknowledged port of Claude Code's hook schema** — same field names
(`hookSpecificOutput`, `permissionDecision`, `hookEventName`), same event names
(`PreToolUse`, `PostToolUse`, `PermissionRequest`, `Stop`, `SessionStart`, …), same
`continue`/`decision`/`reason` vocabulary. That closeness is a genuine, sourced fact
(§2), but it ALSO means a summarizing model has every incentive to "fill in" Codex
details from its Claude Code knowledge when the source page is thin, truncated, or
paywalled behind a redirect it can't fully render. Treat every **verbatim-looking JSON
block** below as **plausible reconstruction, not confirmed byte-for-byte quotation** —
none of it was obtained via raw-source fetch (`raw.githubusercontent.com` fetches for
the two files that plausibly hold this, `docs/hooks.md` and `docs/config.md`, either
404'd or did not contain the passage). Recommend a follow-up pass that pulls the page
through `curl`/`gh` (not available to this research agent) or an authenticated fetch
before this schema is used to build anything.

## 1. Does Codex CLI have a hooks system at all? Yes — confirmed, not hypothetical

The URL the project owner mentioned, **`https://learn.chatgpt.com/docs/hooks`**, is
real and does document a hooks system. It is not a dead link and not a misremembering:

- `https://developers.openai.com/codex/hooks` (the canonical docs host) issues an HTTP
  **308 permanent redirect** to `https://learn.chatgpt.com/docs/hooks`, confirmed
  directly by `WebFetch` following the redirect chain. So `developers.openai.com` and
  `learn.chatgpt.com` are the same documentation set under two hostnames.
- Search results independently surface the same page at
  `https://developers.openai.com/codex/hooks` titled "Hooks | ChatGPT Learn", and a
  third-party mirror `https://doc.jarvisuni.com/openai/codex/hooks.html` titled "Hooks –
  Codex | OpenAI Developers", corroborating that this is a real, indexed, official page
  and not a one-off render artifact.
- A live GitHub issue on the `openai/codex` repo, **openai/codex#28437**, "Support
  PreToolUse permissionDecision: ask for native approval prompts" (opened **2026-06-16**
  per the fetched summary), discusses the hooks system's current behavior in detail and
  references an earlier, closed PR **#20702** that had explored the same feature. This
  is a primary-source GitHub artifact independent of the docs site and it treats hooks
  as an existing, shipped (if partial) feature, not aspirational.
- A GitHub Discussion, **openai/codex#2150** ("Hook would be a great feature"), opened
  **2025-08-11**, is the origin feature request. An OpenAI maintainer, `etraut-openai`,
  replied **2025-11-30** that a narrower "notification hook" already existed (see §5 on
  `notify`, which predates and is distinct from the general hooks system). A second
  maintainer, `asprecic`, replied **2026-03-11**: *"Experimentally merged into `v0.114`!!
  Get 0.114 version, Add `hooks.json` in `.codex`... Run
  `codex -c features.codex_hooks=true`"*, and said the initial implementation shipped
  with only `SessionStart` and `Stop` triggers, with more event types planned as the
  feature stabilized.

**Version/date anchor (best available)**: general lifecycle hooks were experimentally
merged in **Codex CLI v0.114** (maintainer comment dated **2026-03-11**), gated behind
`codex -c features.codex_hooks=true` (equivalently `[features] hooks = true` /
`codex_hooks = true` in `config.toml`, per multiple fetches — the exact flag name was
not obtained byte-for-byte identically across sources, see caveat above). It launched
with a **minimal event set** (`SessionStart`, `Stop`) and has been expanding since. As of
the June 2026 issue (#28437) the event set clearly includes at least `PreToolUse`,
`PermissionRequest`, and others (§3) — so the taxonomy grew substantially between March
and June 2026. **No source seen states hooks have graduated out of experimental/beta
status**, and the feature is reported (via search snippet, not independently confirmed)
as disabled on Windows.

## 2. Relationship to Claude Code's hook system: explicit, acknowledged compatibility

This is the most load-bearing and best-corroborated finding, because it is stated by
more than one independent source rather than resting on a single fetch:

- Issue #28437's own summary describes Codex parsing "Claude-compatible fields like
  `continue: false`" alongside its native fields — i.e. Codex's maintainers themselves
  frame parts of the schema as intentionally Claude-Code-compatible.
- A search-result snippet (from `zhu424.dev`, a third-party "Agent Hooks" reference
  site, not independently fetched in full) describes Codex's hooks as "almost a direct
  port of Claude Code's, using the same JSON-on-stdin protocol, same exit codes, same
  `additionalContext` shape, and same `hookSpecificOutput` structure," and specifically
  says `PreToolUse` is normalized into a shared `PermissionRequest` event so Codex can
  "reuse the same permission route used by Claude."

**Confidence**: medium-high that this compatibility framing is real (it's corroborated
across the docs-site fetch, the GitHub issue, and an independent third-party source that
each converge on the same handful of shared field names), but the **precise mechanics**
of "PreToolUse normalized into PermissionRequest" were not verified against Codex's own
source code (not accessible to this fetch-only research pass) and should be treated as
a third-party characterization, not a primary-source quote.

## 3. Event taxonomy (what can be hooked) — as reported, with source tiers

No single fetch produced a stable, complete, internally-consistent event list across all
sources — different fetches of the same nominal page returned different subsets (10
events, 11 events, "6 core events" per the zhu424.dev snippet). Reporting the union with
provenance:

| Event | Seen in |
|---|---|
| `SessionStart` | docs page (multiple fetches), maintainer comment (first-ever event, v0.114), zhu424.dev snippet |
| `SessionEnd` | docs page fetch only |
| `PreToolUse` | docs page, issue #28437, zhu424.dev snippet |
| `PostToolUse` | docs page, zhu424.dev snippet, agenticcontrolplane.com article |
| `PermissionRequest` | docs page, issue #28437, zhu424.dev snippet |
| `PreCompact` / `PostCompact` | docs page fetch only |
| `UserPromptSubmit` | docs page, zhu424.dev snippet |
| `SubagentStart` / `SubagentStop` | docs page fetch only |
| `Stop` | docs page (also the second-ever event, v0.114), zhu424.dev snippet |

Treat only `SessionStart`, `Stop`, `PreToolUse`, `PermissionRequest`, `PostToolUse`,
`UserPromptSubmit` as reasonably well corroborated (2+ independent-ish sources each).
`SessionEnd`, `PreCompact`/`PostCompact`, `SubagentStart`/`SubagentStop` rest on a single
docs-page fetch and, per the caveat in the header, could be summarizer contamination
from Claude Code's actual event list (which has exactly this shape). **This is the
single most important thing to re-verify with a raw-text fetch before relying on it.**

## 4. Registration / config format — as reported

Multiple fetches agree on the broad shape, with source-tier caveats as above:

- Hooks live in a `hooks.json` file, or inline `[hooks]` TOML table in `config.toml`.
- Discovered at multiple layers that merge (reported ordering: user `~/.codex/`, repo
  `.codex/`, plugin-bundled `hooks/hooks.json`, and an enterprise-only
  `requirements.toml` layer) — "higher layers don't replace lower ones" per one fetch.
- Structure is `Event → matcher group (regex on tool name, etc.) → handler list`, each
  handler `{"type": "command"|"mcp_tool", "command": "...", "timeout": ..., "async": ...}`.
- An enterprise/admin override exists: `allow_managed_hooks_only = true` in
  `requirements.toml` restricts to managed hooks only — this specific fact was
  independently confirmed on **two separate fetches of two different URLs**
  (`learn.chatgpt.com/docs/hooks.md` and `raw.githubusercontent.com/openai/codex/main/docs/config.md`),
  which is the strongest corroboration of any single config detail in this report.
- A trust/review gate exists for non-managed hooks: Codex reportedly hashes a hook's
  definition and requires explicit trust via a `/hooks` command before first run;
  `--dangerously-bypass-hook-trust` is named as a CLI escape hatch in one fetch. Single
  source; not independently corroborated.

## 5. `notify` — a separate, older, narrower mechanism

`notify` is **not** the general hooks system and predates it:

- Per maintainer `etraut-openai` (2025-11-30, in discussion #2150), a "notification
  hook" already existed **before** general hooks shipped (v0.114 was March 2026).
- Per a docs-page fetch (`learn.chatgpt.com/docs/config-file/config-advanced`): `notify`
  is a `config.toml` key that runs an external program on specific Codex-emitted
  events — reported to currently fire only on `"agent-turn-complete"`. Example shape:
  `notify = ["python3", "/path/to/notify.py"]`, and the script receives one JSON
  argument with fields including `type`, `thread-id`, `turn-id`, `cwd`,
  `input-messages`, `last-assistant-message`.
- The same fetch reports the docs text itself drawing the distinction: `notify` is for
  "webhooks, desktop notifiers, CI hooks" (fire-and-forget, no return value consulted),
  whereas the hooks system is described as in-process lifecycle handlers whose return
  value Codex acts on. **This is a notify-only vs. blocking-capable distinction that
  matters for the plan's question** — see §6.
- A separate search snippet states `.codex/config.toml` at the **project-local** level
  has `notify` deliberately ignored by Codex for security reasons — only the user-level
  `~/.codex/config.toml` `notify` is honored. Single source, not independently verified.
- `approval_policy` values reported (single fetch, low confidence on exact enum):
  `"untrusted"`, `"on-request"`, `"never"`, plus a `{ granular = {...} }` object form
  that can allow/reject categories like `request_permissions` and `skill_approval`. The
  fetch explicitly says the source page **did not** spell out how `approval_policy`
  relates to the hooks-based `PermissionRequest` event — this relationship is an open
  question (see below).

## 6. Can a hook block/deny an action, or is it notify-only? — Blocking exists, with a live gap

This is the plan's critical question. The evidence says: **yes, Codex hooks are
designed to be able to deny/block, not merely observe** — but with a specific,
documented, currently-unsupported edge:

- `PreToolUse` hooks are reported to support a `permissionDecision` field with values
  `"allow"`, `"deny"`, `"ask"` (mirroring Claude Code). **`"deny"` is corroborated as
  actually enforced** — three separate fetches (the docs page, the GitHub issue
  #28437 summary, and the agenticcontrolplane.com article) independently state that a
  `deny` response blocks the tool call.
- **`"ask"` is explicitly reported as NOT currently supported**, and this is the single
  best-sourced granular fact in this whole report because it comes from a live,
  numbered GitHub issue rather than a docs-page summary: issue #28437's own title is
  "Support PreToolUse permissionDecision: **ask** for native approval prompts," i.e. the
  issue exists precisely because today, per the issue text, *"Codex currently parses
  `permissionDecision: "ask"`, but treats it as unsupported"* and errors with
  `"PreToolUse hook returned unsupported permissionDecision:ask"`. The issue proposes
  (not yet shipped, as of the fetch) that `ask` should trigger a native approval prompt,
  `deny` should keep blocking, and `allow` should not bypass Codex's own sandbox/network/
  policy checks regardless of what the hook says.
- `"allow"` behavior is reported inconsistently across sources: one search snippet
  claims Codex "reserves `permissionDecision: allow` for hook responses that also
  provide `updatedInput`" (i.e. allow is meaningful mainly as a companion to rewriting
  the tool call), while the agenticcontrolplane.com article instead says flatly "the
  only decision Codex acts on is `deny`" and that `allow`/`ask`/`updatedInput` are
  "parsed but rejected." **These two claims are in direct tension** and this research
  pass could not resolve which is current — plausibly because the two sources describe
  different Codex versions (the feature was actively changing through mid-2026) rather
  than because one is simply wrong. A follow-up should pin an exact Codex version and
  re-check.
- `PostToolUse` is reported (docs-page fetch, single source) to support
  `"decision": "block"` + `"reason"`, which replaces the tool's result with feedback —
  i.e. it cannot undo a side effect already performed, but can block what the model sees
  as the outcome, matching Claude Code's own `PostToolUse` semantics.
- `PermissionRequest` is reported (docs-page fetch, single source) to support a
  `{"decision": {"behavior": "allow"|"deny", "message": "..."}}` shape, with "any deny
  wins" when multiple hooks fire.
- `UserPromptSubmit` and `Stop`/`SubagentStop` are reported (docs-page fetch, single
  source) to support `"decision": "block"` + `"reason"` as well, for refusing a prompt
  or forcing/declining continuation respectively.
- The August-2026 "recent release notes" search snippet adds one more corroborating
  data point for blocking-with-verdict semantics (not just notify): it describes a fix
  where "background sessions waiting silently when a `PermissionRequest` or `PreToolUse`
  hook prints an invalid answer" now surface a named schema error instead of hanging —
  implying Codex genuinely parses and acts on a structured verdict from these hooks
  (there would be nothing to validate if it were notify-only).

**Bottom line on the plan's central question**: Codex CLI's hooks are **verdict-based,
not notify-only**, for at least `PreToolUse`, `PermissionRequest`, `PostToolUse`,
`UserPromptSubmit`, and `Stop`. The clearest, best-sourced limitation is that
`PreToolUse`'s three-way `allow`/`deny`/`ask` verdict is only two-thirds implemented
today: `deny` works, `ask` explicitly errors out (per an open GitHub issue as of
2026-06-16), and `allow`'s exact semantics are contested between sources.

## 7. Approval-policy extension points beyond hooks

Only lightly surfaced in this pass: `approval_policy` (`untrusted` / `on-request` /
`never` / granular object, per §5) appears to be a **separate, coarser** mechanism from
the hooks' `PermissionRequest` event, but no source explained how the two compose (e.g.
does a granular `approval_policy` entry pre-empt `PermissionRequest` hooks, or do hooks
run first and `approval_policy` handle whatever they don't decide?). **Open question —
not answered by this research pass.**

## 8. What was NOT independently verified (explicit gaps)

- No raw/byte-exact JSON schema was obtained for any hook's input or output payload —
  every "verbatim-looking" block returned by `WebFetch` should be treated as the
  summarizer's reconstruction (see header caveat), not a copy-paste quote.
- `docs/hooks.md` at `raw.githubusercontent.com/openai/codex/main/` returned **404** —
  if such a file exists in the repo it is at a different path or filename; this was not
  resolved (a repo tree listing would settle it but wasn't fetched).
- The exact feature-flag key (`features.codex_hooks` vs. `features.hooks`) was reported
  inconsistently across fetches and not confirmed against a single authoritative source.
- Whether hooks have exited "experimental" status as of 2026-08-30 is unknown — no
  source seen states a graduation date, and the feature was still gated behind a flag
  and missing `ask` support as of the June 2026 issue.
- Windows support status ("disabled on Windows" per one search snippet) is single-source
  and unverified.
- This report did not check `openai/codex` release notes / CHANGELOG.md directly for a
  dated, versioned list of hook-related changes (attempted via search only; no fetch of
  an actual CHANGELOG entry succeeded) — a genuinely useful follow-up.

## Sources

- https://developers.openai.com/codex/hooks (redirects 308 to the URL below; confirmed live)
- https://learn.chatgpt.com/docs/hooks — the project-owner-named URL; confirmed to exist and document the hooks system described in §§3-6
- https://learn.chatgpt.com/docs/hooks.md — markdown variant of the same page, fetched separately for §§3-4, §6
- https://learn.chatgpt.com/docs/config-file/config-advanced — `notify` and `approval_policy`, §5
- https://github.com/openai/codex — repo root (README fetch found no hooks mention in the top-level README itself)
- https://raw.githubusercontent.com/openai/codex/main/docs/config.md — corroborates the `allow_managed_hooks_only` detail; no `notify` section found in the fetched content
- https://github.com/openai/codex/blob/main/docs/hooks.md — returned HTTP 404 at time of fetch
- https://github.com/openai/codex/issues/28437 — "Support PreToolUse permissionDecision: ask for native approval prompts", opened 2026-06-16; primary source for §2, §6's `ask`-unsupported finding
- https://github.com/openai/codex/discussions/2150 — "Hook would be a great feature", opened 2025-08-11; maintainer comments dated 2025-11-30 (`etraut-openai`) and 2026-03-11 (`asprecic`, v0.114 experimental merge) — primary source for §1's version anchor
- https://agenticcontrolplane.com/blog/codex-cli-hooks-reference — third-party article, published 2026-04-30, updated 2026-08-27; cites `https://developers.openai.com/codex/agent-approvals-security` as canonical (not independently fetched by this research pass) and itself warns against relying on third-party reproductions of the schema
- Search-result snippets only (not independently fetched, lower confidence, attributed inline above): zhu424.dev "Agent Hooks / Codex" page; doc.jarvisuni.com mirror pages
