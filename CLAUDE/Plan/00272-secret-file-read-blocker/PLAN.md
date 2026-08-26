# Plan 00272: secret file read blocker

**Status**: In Progress
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Absolutely prevent the CONTENTS of configured secret files (Ansible Vault
password files, the daemon's own `.claude/block-words.secret`, key material)
from ever being read or entering context via any route the daemon can see —
including Bash, interpreter one-liners, and indirect copies. The file's
PRESENCE and safe METADATA remain available: a new
`bin/hooks-daemon secret-meta <path>` helper returns existence, size, mtime,
permissions and a keyed digest, never content, so tooling like
`ansible-vault --vault-password-file` still works while no agent ever sees
the secret itself.

Honest framing up front: the handler is a DETECTION-AND-FRICTION layer over
an OS boundary (permissions, ownership, encryption at rest) the project must
set independently; the one cheaply shippable boundary piece is the
permissions hygiene advisory (Task 6.1).

The user directive is explicit: "we would need to catch any and all attempts
to read it, even via bash/python etc calls — need full research into this to
confirm what protections we can add." Phase 1 is therefore a dedicated
research phase, BEFORE any design commitment, whose deliverable
([RESEARCH-read-routes.md](RESEARCH-read-routes.md), scaffolded with the
route inventory) exhaustively classifies every read route by (a) hook
visibility, (b) reliably blockable, (c) heuristically blockable, or
(d) fundamentally unblockable at hook level — with live verification
(`scripts/debug_hooks.sh`, subagent probes), not assumptions. Its honest
conclusion: hook-level protection is DEFENCE IN DEPTH, not a sandbox; only
OS-level controls truly guarantee non-disclosure.

Anticipated primary mechanism (to be confirmed by the research): a terminal
PreToolUse gating handler (`secret_file_guard`, safety band) denying
Read/Write/Edit/Grep on protected paths and ANY Bash command whose text
references a protected path (after `~`/`$HOME`/variable heuristics) —
deny-by-default in the `sed_blocker` style — except a narrow allowlist:
existence semantics via the metadata helper, and trusted consumers with the
path in flag position. Plus the strongest feasible secondary layers the
research confirms (Write/Edit content scan for scripts naming protected
paths; possibly a PostToolUse output backstop). Complements
`sensitive_content` (write-direction, term-based); deep analysis in
[BRAINSTORM.md](BRAINSTORM.md).

## Goals

- A completed, verification-backed read-route classification covering every
  route in RESEARCH-read-routes.md — including daemon-owned outputs and the
  output-side rewrite question.
- No wired tool call returns protected-file content into context for every
  class-(b) route; class-(c) routes get the strongest feasible heuristics;
  class-(d) routes are plainly documented residual risk with the OS-level
  controls that close them.
- Presence and metadata stay usable via the `secret-meta` helper (sole
  sanctioned inspection route).
- Trusted consumers (Ansible family, `--vault-password-file`) keep working,
  extensible via config.
- Shipped default protected globs, default-on, additive with project globs.
- NO agent escape hatch — human config edit only (Plan 00259 doctrine).

## Non-Goals

- Not a sandbox: class-(d) routes (pre-existing scripts/binaries opening the
  file internally, string-assembled paths, non-daemon channels) are
  documented residual risks, not requirements.
- No dedicated deletion protection (falls out of deny-by-default; Decision 4).
- No exfiltration guard for content already in context.

## Context & Background

- `sensitive_content` (write-direction, term-based) and Plan 00252
  (staged-content term scan) are siblings, not overlaps.
- `worktree_create` seeds `.claude/block-words.secret` as a symlink —
  matching must cover symlink and realpath spellings.
- Current `sensitive_content` guidance invites opening the secret word list
  file; this plan reverses that (deny reason: ask the user) — a
  truth-changes manifest entry is required at release.
- Scope: three shippable units bundled (guard, `secret-meta` CLI, hygiene
  advisory); if Phase 1 shows the guard alone is large, Phases 5–6 split
  cleanly into a follow-up plan.
- The draft review
  ([REVIEW-2026-08-26-draft-plan.md](REVIEW-2026-08-26-draft-plan.md)) is
  folded in; finding detail lives in BRAINSTORM.md and
  RESEARCH-read-routes.md.

## Tasks

### Phase 1: Read-route research (deliverable: RESEARCH-read-routes.md complete)

- [ ] ⬜ **Task 1.1**: Output-side capability — vendored contracts FIRST
  (`contracts/claude-code-hooks/PostToolUse.json` lists `updatedToolOutput`,
  answering shape for free), then verify BEHAVIOUR live: does Claude Code
  honour `updatedToolOutput` for Bash, and does `tool_response` carry full
  stdout/stderr? If honoured, the backstop is REDACTION, not a late failure
  report — re-derive the class-(d) list on that basis (see
  RESEARCH-read-routes.md, output-side section)
- [ ] ⬜ **Task 1.2**: Verify subagent hook coverage live (spawned agent's
  Read/Bash hit the same PreToolUse chain) — confirm, do not assume; AND
  separately verify the `TaskOutput` relay surface, which the subagent
  probe does not cover
- [ ] ⬜ **Task 1.3**: Record payload shapes (contract files first, live
  capture only where contracts are silent) for Grep (output
  mode/path/root fields), Edit on a protected file (old_string echo-back /
  error leakage), NotebookEdit, WebFetch `file://`, MCP tool wiring, LSP
  (hover/documentSymbol return file text), Skill bodies that read files,
  Artifact `upload_asset`; plus the no-tool-call auto-inlining routes
  (`@`-imports, `.claude/rules/` `paths:` globs) as a session-start-checkable
  configuration condition
- [ ] ⬜ **Task 1.4**: Live aliasing probes against a dummy protected
  fixture: symlink, hardlink, `cp` to an unprotected path then read,
  variable-expanded path (`P=x; cat $P` same- and cross-invocation),
  `$(<file)` / `$(cat file)`, interpreter one-liners — record per probe
  whether the proposed matcher would catch it or provably cannot
- [ ] ⬜ **Task 1.5**: Classify every route in the inventory as
  (b)/(c)/(d) with visibility column filled; resolve the marked DECIDE
  items: later-turn variable indirection heuristic, bidirectional glob
  matching, find/xargs combos, directory-rooted content grep, git
  revision-syntax reads
- [ ] ⬜ **Task 1.6**: Decide the output-side backstop: is daemon-side
  reading of the secret (in-memory, never emitted/logged) acceptable? Weigh
  against Task 1.1 — if `updatedToolOutput` is honoured, the secret in
  daemon memory buys PREVENTION (redacted substitution), not a report. The
  answer MUST be written as an amendment to `utils/secret_redaction.py`'s
  "exactly one code path" doctrine, not alongside it; internal digests stay
  unreachable from the `secret-meta` CLI (Decision 6)
- [ ] ⬜ **Task 1.7**: Write the research conclusion — layer stack
  recommendation + residual risks only OS-level controls (permissions,
  separate user, sandboxing) can close
- [ ] ⬜ **Task 1.8**: Map each Technical Decision to the research findings
  it depends on; confirm, revise or retire every decision marked
  "provisional pending Phase 1" (the output-leak layer exists ONLY if Task
  1.1 shows PostToolUse sees stdout; the Bash-authored-script scan in Task
  4.3 exists ONLY if Task 1.3 confirms visibility)
- [ ] ⬜ **Task 1.9**: Enumerate DAEMON-OWNED outputs as a route class
  (payload capture, debug/error logs, transcript archives per
  `utils/secret_redaction.py`; `staged_lint_gate`/`lint_on_edit`
  diagnostics): confirm `daemon/payload_capture.py` captures a successful
  read's payload verbatim (it redacts only word-list terms) and record what
  Task 4.5 must close — the guard must not WORSEN the artefact footprint
  for its residual routes (see BRAINSTORM.md daemon-artefacts section)

### Phase 2: Design finalisation (human review of research + open questions)

- [ ] ⬜ **Task 2.1**: Resolve open questions with human against the
  completed research (default glob breadth incl. key material; keyed-HMAC
  vs opt-in plain hash; echo / git-commit-message exemption stance; which
  class-(c) heuristics to ship vs defer; secondary layers to include;
  final priority slot in 10–20 band). Named decision items: (a)
  **consumer-allowlist subcommand grammar** — deny `ansible-vault view|decrypt` (head-only allowlisting sanctions the most direct
  disclosure path; see BRAINSTORM.md trusted-consumer section); (b)
  **metadata disclosure** — bucketed `size_bytes` default and HMAC key-file
  mode precondition (see BRAINSTORM.md finding-5 section)
- [ ] ⬜ **Task 2.2**: Record decisions in Technical Decisions; update
  BRAINSTORM.md/RESEARCH doc where superseded

### Phase 3: TDD — matching core

- [ ] ⬜ **Task 3.1**: Failing tests for protected-path glob matching
  (defaults + config additive, canonicalisation of relative/`~`/`$HOME`
  spellings, symlink/realpath, worktree seeding case)
- [ ] ⬜ **Task 3.2**: Failing tests for Bash path-mention detection across
  the class-(b) and shipped class-(c) routes (direct readers, interpreter
  one-liners, cp/mv/ln/tar, substitution, sourcing, same-invocation
  variable indirection, glob-shaped mentions) and the exemptions
  (metadata helper; consumer + path_flags grammar)
- [ ] ⬜ **Task 3.3**: Implement matching utilities (reuse gitignore-glob
  machinery; constants per NO MAGIC)

### Phase 4: TDD — handler

- [ ] ⬜ **Task 4.1**: Failing tests for `SecretFileGuardHandler`
  (PreToolUseHandlerBase, GatingResult DENY, terminal, priority per Task
  2.1) across Read/Write/Edit/Grep/Bash (+ surfaces Phase 1 added); deny
  reason names the matched glob, never content, points at `secret-meta` +
  human-config-edit
- [ ] ⬜ **Task 4.2**: Implement handler; register HandlerID/Priority
  constants, wire into `handlers/pre_tool_use/__init__.py` and default +
  example configs
- [ ] ⬜ **Task 4.3**: Secondary layer per research: Write/Edit content
  scan denying authorship of scripts that reference a protected path
  (closes the write-then-execute route); include Bash-authored files if
  Phase 1 confirmed feasibility
- [ ] ⬜ **Task 4.4**: `get_claude_md()` guidance: deny-by-default framing,
  exemptions, the (b)/(c)/(d) honest-limits summary, no-escape-hatch
  statement, OS-level-controls pointer, and the vault-payload scope
  boundary (protecting the password file does not protect vaulted vars)
- [ ] ⬜ **Task 4.5**: Close the Task 1.9 daemon-artefact seam BEFORE any
  output-side layer: extend `redact_structure` (or exclude protected-path
  payloads from capture) so a residual-route read never lands verbatim in
  `payload-capture/` or logs; exclude protected paths from
  `staged_lint_gate`/`lint_on_edit` diagnostics

### Phase 5: TDD — metadata helper

- [ ] ⬜ **Task 5.1**: Failing tests for `secret-meta` core (exists/missing,
  bucketed size by default with exact size behind the plain-hash flag,
  mtime/mode, keyed HMAC digest with generated gitignored key, key file
  itself protected, refusal to emit a digest when the key file is
  group/world-readable, plain-hash flag per Task 2.1, and no CLI route to
  any backstop-internal digest — Decision 6)
- [ ] ⬜ **Task 5.2**: Implement helper as CLI subcommand + `utils/` core;
  JSON output; never prints content

### Phase 6: Hygiene checks

- [ ] ⬜ **Task 6.1**: Advisory (SessionStart or in-handler) that each
  protected path is gitignored, not git-tracked, AND has safe
  permissions/ownership (flag group/world-readable modes via
  `constants/permissions.py` `FileMode`; `chmod 600` remediation) — the one
  cheaply shippable OS-boundary piece (BRAINSTORM.md OS-boundary section);
  include the Task 1.3 auto-inlining config check if feasible
- [ ] ⬜ **Task 6.2**: Update `sensitive_content` guidance; stage
  truth-changes + config-changes manifests in `UNRELEASED/`

### Phase 7: Integration & acceptance

- [ ] ⬜ **Task 7.1**: `get_acceptance_tests()` using dummy fixture paths —
  never a real secret; cover one test per route class shipped
- [ ] ⬜ **Task 7.2**: Full QA (`./scripts/qa/llm_qa.py all`), daemon
  restart verification, dogfood with `.claude/block-words.secret` protected
- [ ] ⬜ **Task 7.3**: Client-mode verification (`dummy-client-repo.sh`);
  docs (`HANDLER_REFERENCE.md`, generate-docs)

## Dependencies

- Related: Plan 00252 (staged secret terms), Plan 00259 doctrine (no
  self-authorised disclosure), Plan 00242 (terminal-handler primitive — if
  it lands first, adopt its shape), Plan 00170/00172 (event wiring —
  relevant to MCP/WebFetch visibility)

## Technical Decisions

### Decision 1: Deny-by-default on path mention, narrow allowlist (provisional pending Phase 1)

**Context**: A bad-pattern list (cat/head/base64/python -c…) is unwinnable —
the reader list never ends.
**Decision**: Any Bash command referencing a protected path is denied unless
it is the metadata helper or an allowlisted consumer with the path in flag
position — the `sed_blocker` framing. Evasions and residual risks are
enumerated per-route in RESEARCH-read-routes.md, not hand-waved.
**Date**: 2026-08-26

### Decision 2: Keyed digest by default (proposed, awaiting human)

**Context**: A plain sha256 of a low-entropy secret is offline-crackable
from the transcript.
**Decision (proposed)**: HMAC-SHA256 with a generated, gitignored,
itself-protected per-project key; plain sha256 only behind
`allow_plain_hash: true`.
**Date**: 2026-08-26

### Decision 3: No escape hatch for agents

**Context**: Same class as artifact publishing — self-authorised disclosure.
**Decision**: No `MUST_..._BECAUSE`. A human edits config to lift it.
**Date**: 2026-08-26

### Decision 4: Deletion/copy protection not built separately (provisional pending Phase 1)

**Context**: `rm`/`cp` of a protected path already mentions the path.
**Decision**: Denied by Decision 1 as a side effect; no dedicated mechanism
(YAGNI). Writes to protected files denied too (no legitimate use).
**Date**: 2026-08-26

### Decision 5: Research before design commitment

**Context**: User directive requires confirming, not assuming, what
protections are possible ("catch any and all attempts … full research").
**Decision**: Phase 1 verifies hook visibility per route with
`debug_hooks.sh` and live probes; the shipped layer stack is chosen from the
completed classification. The honest framing — defence in depth, not a
sandbox; class-(d) routes closable only by OS-level controls — is a required
deliverable, stated in resident guidance.
**Date**: 2026-08-26

### Decision 6: Backstop digests architecturally separate from the helper's public digest

**Context**: Backstop prefix digests reachable via the `secret-meta` CLI
would be a byte-by-byte extraction oracle (BRAINSTORM.md finding-5 section).
**Decision**: The backstop's internal matching state and the helper's public
keyed digest are separate by design — no CLI, config or log route exposes
the former.
**Date**: 2026-08-26

### Decision 7: Shipped default globs include `*.secret*` (user directive)

**Context**: Mid-execution human directive: the initial default glob set must
cover any filename containing `.secret`.
**Decision**: Ship `*.secret*` as a default protected pattern alongside the
vault-password shapes and SSH key names. Conservative list:
`*.secret*`, `.vault-pass*`, `*.vault-password`, `*vault_pass*`,
`id_rsa`, `id_ed25519`. `*.pem`/`*.key` deliberately NOT shipped (public
certs share the extension — Task 2.1 open question stands for a human).
**Date**: 2026-08-26

### Decision 8: Pattern list uses the `mode: additive | replace` convention (user directive)

**Context**: Second mid-execution human directive: project extension must use
the established `command_hints`/`goal_injection` config style.
**Decision**: `options.mode: additive` (default) merges `protected_paths`
onto the built-in defaults; `replace` uses only the project list. An unknown
mode behaves as `additive` (fail-closed toward MORE protection, matching the
command_hints precedent).
**Date**: 2026-08-26

### Decision 9: Phase-2 recommendations adopted as recorded defaults

**Context**: Phase 2 named human-review items; the folded draft review already
carried recommendations, adopted here so implementation can proceed (a human
can revise any of them by config or follow-up).
**Decision**: (a) keyed HMAC-SHA256 digest by default, plain sha256 + exact
size only behind `allow_plain_hash: true`; (b) bucketed `size_bucket` by
default; (c) NO echo exemption and NO git-commit-message exemption (match on
shell WORD tokens only, so prose mentions rarely fire); (d) consumer
allowlist is subcommand-aware — `ansible-vault view|decrypt` DENIED, the rest
of the Ansible family allowed with the path in flag position; (e) priority 14
(safety band, alongside sensitive_content/security_antipattern).
**Date**: 2026-08-26

## Success Criteria

- [ ] RESEARCH-read-routes.md complete: every route has verified visibility,
  a (b)/(c)/(d) classification AND a per-route expected-verdict entry; all
  DECIDE items resolved; conclusion written
- [ ] Every class-(b) route denied live; class-(c) behaviour matches the
  expected-verdict column in RESEARCH-read-routes.md (Task 7.1 asserts
  against that table); class-(d) residual risk stated in resident guidance
  with OS-level mitigations named
- [ ] Permissions/ownership advisory fires on group/world-readable protected
  files with remediation text (Task 6.1)
- [ ] No residual-route read lands verbatim in payload capture or logs
  (Task 4.5)
- [ ] `secret-meta` returns metadata JSON with no content bytes;
  `ansible-vault --vault-password-file <protected>` consumer commands pass
- [ ] Deny reasons never include file content; verdict log clean
- [ ] No escape hatch exists
- [ ] 95%+ coverage, full QA green, daemon restart verified, client-mode
  verified

## Risks & Mitigations

| Risk                                                        | Impact | Probability | Mitigation                                                                        |
| ----------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------- |
| Research reveals a key surface is invisible (e.g. MCP)      | High   | Med         | Classify honestly as (d); document OS-level controls; do not overclaim            |
| False positives lock out legitimate consumer commands       | Med    | Med         | Consumer allowlist config; dogfood before release                                 |
| Agents read an unblocked evasion as permission              | High   | Med         | Guidance states deny-by-default policy and (b)/(c)/(d) limits explicitly          |
| Default globs too broad (e.g. `*.pem`) break real workflows | Med    | Med         | Ship a short conservative default list; Task 2.1 human review                     |
| Hash output leaks weak secrets                              | High   | Low         | Keyed HMAC default (Decision 2)                                                   |
| Output backstop needs daemon to read the secret             | Med    | Med         | Task 1.6 decides acceptability explicitly; backstop is optional, not load-bearing |
| Guard's residual routes leak into daemon artefacts          | High   | Med         | Task 1.9 enumerates; Task 4.5 closes the payload-capture/log seam first           |

## Delivery & Milestones

- Plan authored; brainstorm + research scaffold complete — ready for human
  review (uncommitted pending review, consistent with 00269/00270)
