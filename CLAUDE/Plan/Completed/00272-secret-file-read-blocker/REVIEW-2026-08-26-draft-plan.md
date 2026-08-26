# Plan 00272 Draft Review — 2026-08-26

Pre-execution plan-quality review by a dispatched code-reviewer sub-agent.
Verbatim report follows; each finding must be either folded into PLAN.md /
RESEARCH-read-routes.md / BRAINSTORM.md or explicitly rebutted there.

**Verdict: FIX FIRST.**

Well-structured draft. The research-first ordering is genuine rather than decorative (Task 1.8 makes two design elements conditional on research outcomes), the deny-by-default framing is correctly borrowed from `sed_blocker` rather than reinventing a bad-pattern list, the no-escape-hatch decision is grounded in Plan 00259 doctrine, and BRAINSTORM.md's "Honest limits" section is unusually candid.

Not ready to execute because of three substantive gaps — one of which could *increase* secret exposure on disk, and one of which invalidates a stated premise about PostToolUse.

## Critical

### 1. The daemon's own artefacts are an unlisted leak vector, and Task 1.6 would worsen it

`RESEARCH-read-routes.md` enumerates routes by which content reaches *agent context*, but never asks where the daemon itself writes content. That enumeration already exists in this repo and contradicts the plan's coverage claim.

`src/claude_code_hooks_daemon/utils/secret_redaction.py:1-30` documents four daemon-owned leak vectors (payload capture, router debug log, front-controller error log, transcript archives) and states the no-echo threat model explicitly. Critically, `daemon/payload_capture.py:101` redacts **only terms from the configured secret word list**:

```python
payload = redact_structure(hook_input, secret_terms) if secret_terms else hook_input
```

So for any route the plan classifies as (c) or (d) — the ones that succeed — the resulting PostToolUse payload carrying the vault password is written verbatim to `payload-capture/`. The plan ships a guard whose acknowledged residual-risk routes each write the secret to a daemon-owned file. That is a net worsening of the artefact footprint.

Task 1.6 compounds this by proposing the daemon read the secret into memory, without reconciling that against the module whose docstring is "there is exactly one code path that ever reads the raw terms."

**Remediation:** add a Phase 1 task enumerating daemon-owned outputs as a route class in its own right; add a Phase 4/6 task extending `redact_structure` (or excluding protected paths from capture) before any output-side layer is built. Task 1.6's answer must be written as an amendment to `secret_redaction.py`'s doctrine, not alongside it.

### 2. `updatedToolOutput` exists — the "PostToolUse is inherently too late" premise is wrong

`RESEARCH-read-routes.md:89-104` and `PLAN.md:105-108` both frame the output backstop as necessarily late: "PostToolUse fires AFTER the content is already in context — a deny is a failure report, not prevention."

The vendored contract at `contracts/claude-code-hooks/PostToolUse.json` lists `updatedToolOutput` and `updatedMCPToolOutput` among the hook-specific output fields. PostToolUse can **rewrite the tool result** before it reaches context. That converts the backstop from post-hoc scolding into actual redaction, and changes Task 1.6's cost/benefit entirely: secret-in-daemon-memory now buys prevention rather than a report.

It also shrinks the conceded class-(d) set. A pre-existing script that prints the secret is invisible at PreToolUse but its *output* is visible at PostToolUse and now rewritable — so the headline residual risk at `RESEARCH-read-routes.md:77` may be materially smaller than claimed.

**Remediation:** rewrite Tasks 1.1 and 1.6 around `updatedToolOutput`. Task 1.1's question becomes "can a PostToolUse handler substitute redacted output, and does Claude Code honour it for Bash." Re-derive the class-(d) list afterwards.

### 3. The trusted-consumer allowlist has a hole that defeats the guard

`BRAINSTORM.md:50-58` proposes allowlisting the Ansible family by command head with the path in flag position. But `ansible-vault view --vault-password-file .vault-pass secrets.yml` and `ansible-vault decrypt ...` are exactly that shape, and exist to **print decrypted secret material to stdout**. `ansible-playbook` with a `debug:` task does the same for vaulted vars.

Command-head allowlisting therefore sanctions the most direct disclosure path in the very tool family the plan exists to support. The guard would deny `cat .vault-pass` while permitting `ansible-vault view` — strictly worse for the user.

**Remediation:** make this a named Phase 2 decision item. The allowlist grammar needs subcommand awareness: permit `ansible-vault encrypt|rekey|create`, `ansible-playbook`, `ansible`; deny `ansible-vault view|decrypt|cat`. State in `get_claude_md()` that protecting the vault password file does not protect the vaulted *payload* — a separate decision.

## Important

### 4. Honesty about limits stops one step short — OS-level enforcement is documentation-only

The plan is admirably honest that this is defence in depth (`PLAN.md:30-32`, Decision 5, Non-Goals). But every reference to the real boundary — permissions, separate user, encryption at rest — appears as something to *document* (Tasks 1.7, 4.4), never to *ship*. Given the plan opens with "absolutely prevent", Goals at `PLAN.md:46-61` contain no deliverable that is actually a boundary.

There is a cheap shippable piece. Task 6.1 already proposes a gitignore hygiene advisory; extending it to check mode (`0600`? group/world-readable?) and owner costs almost nothing, uses the `FileMode` constants in `constants/permissions.py`, and matches the precedent in `utils/private_io.py`, whose docstring says "the redundancy is the point: neither layer is load-bearing on its own." That is exactly the framing this plan needs.

**Remediation:** extend Task 6.1 to a permissions/ownership advisory with remediation text; add a matching success criterion; state in the Overview that the handler is a detection-and-friction layer over an OS boundary the project must set independently.

### 5. The metadata helper can become an extraction oracle

The HMAC-vs-plain-hash analysis in `BRAINSTORM.md:108-128` is correct and Decision 2 lands right. Three misses:

- **Exact `size_bytes` is the single most valuable disclosure to an offline cracker** for a passphrase file, and the brainstorm dismisses bucketing as YAGNI. No legitimate use needs byte-exact length; "did it change" is answered by the digest. Default to a bucketed size; expose exact length behind the same flag as the plain hash.
- **The HMAC key file needs its own precondition.** A key in `untracked/` is worthless if group-readable; the helper should refuse to run rather than emit a digest under a compromised key.
- **Most importantly**: if Task 1.6's backstop needs "first/last N bytes or rolling hashes" (`RESEARCH-read-routes.md:98-100`) and any of that is reachable through the helper's CLI, an agent gains a byte-by-byte extraction oracle — repeated prefix queries recover the secret entirely. The backstop's internal digests and the helper's public digest must be architecturally separate, recorded as a decision rather than left to implementation.

## Important — Route-inventory gaps (finding 6)

Missing from the research table, several cheap to close:

- **Tool surfaces in `constants/tools.py`**: `LSP` (hover/documentSymbol return file text), `TaskOutput` (relays a subagent's output into the parent context — Task 1.2's subagent PreToolUse verification does *not* cover this relay), `Skill` (a skill body can read files).
- **Auto-inlining with no tool call at all**: a protected path reached by an `@`-import in `CLAUDE.md`, or matched by a `paths:` glob in `.claude/rules/*.md`, is inlined by Claude Code with no hook event. Class (d) by tool visibility, but unlike most (d) routes it is a *configuration* condition the daemon could check at session start — worth a row rather than a shrug.
- **Daemon handlers as readers**: `staged_lint_gate` surfaces "the first line of diagnosis" over staged files; `lint_on_edit` does the same on write. If a protected file is ever staged or edited, a linter diagnostic can quote a content line into context — the daemon leaking the secret through its own advisory. Protected paths need excluding from those handlers.
- **Persistent shell state** as one row rather than several: `exec 3<file`, `mkfifo` + background writer, tmux/screen, Claude Code's own cross-invocation Bash state. Generalises the "variable set in an earlier invocation" row at `RESEARCH-read-routes.md:60`.
- **Process substitution** (`<(cat f)`) appears at `BRAINSTORM.md:29` but never reaches the research inventory table.

## Minor

- **Cross-reference error**: the risks table at `PLAN.md:260` attributes the output-backstop decision to Task 1.5; the task list at `PLAN.md:105-108` assigns it to Task 1.6.
- **Malformed success criterion**: `PLAN.md:238-240` renders as a stray nested sub-bullet. Flatten it.
- **Task 1.1 names the expensive method first**: `contracts/claude-code-hooks/PostToolUse.json` already answers the payload-shape half of Task 1.1 and much of Task 1.3 authoritatively and for free — Plan 00271 vendored these precisely so this stops requiring a live capture. Cite the contracts first; reserve `debug_hooks.sh` for behaviour questions (does Claude Code honour `updatedToolOutput`?) rather than shape.
- **Measurability**: "shipped class-(c) heuristics behave as specified" (`PLAN.md:241-243`) has no referent until Phase 1 completes. Tie it to a per-route expected-verdict column in RESEARCH-read-routes.md so Task 7.1's acceptance tests have a table to assert against.
- **Scope**: three shippable units bundled (guard handler, CLI subcommand, SessionStart advisory). Each phase is gated so this is defensible, but if Phase 1 shows the guard alone is large, Phases 5 and 6 split cleanly into a follow-up.

## What is already right

Decision 5 makes research a genuine gate, and Task 1.8's requirement to retire contradicted decisions is the mechanism that makes it real. Deny-by-default correctly identifies that a reader-command list is unwinnable. Decision 3's refusal of an agent escape hatch is reasoned from the artefact-publishing precedent rather than asserted. The `worktree_create` symlink-seeding interaction (`PLAN.md:77-78`) is a subtle catch that would have caused a silent bypass. The `sensitive_content` relationship is correctly characterised as complementary, and the plan notices it *reverses* shipped guidance and needs a truth-changes manifest entry — the kind of thing that normally ships broken. Task grammar, status line, header fields and the README index row all comply.

## Suggested order

Fix findings 1, 2 and 3 before Phase 1 starts — each changes what Phase 1 is researching. Fold 4, 5 and 6 into Phase 1/Phase 2 as added tasks and decision items. Minor items are editorial.
