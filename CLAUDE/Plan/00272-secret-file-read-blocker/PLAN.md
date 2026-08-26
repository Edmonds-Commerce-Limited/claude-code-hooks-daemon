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

- [x] ✅ **Task 1.1** (desk-check done 2026-08-26; behaviour deferred-live):
  Output-side capability — vendored contracts FIRST
  (`contracts/claude-code-hooks/PostToolUse.json` lists `updatedToolOutput`,
  answering shape for free — CONFIRMED, plus `updatedMCPToolOutput`). The
  BEHAVIOUR half (does Claude Code honour `updatedToolOutput` for Bash, does
  `tool_response` carry full stdout/stderr) is NOT answerable from a subagent
  or the contract — the `input_example` `tool_response` is a Write case only.
  Remains [DEFERRED-LIVE]; shipped v1 correctly ships no output-side backstop.
  See RESEARCH-read-routes.md "Task 1.1 desk-check".
- [x] ✅ **Task 1.2** (proven live 2026-08-26): Subagent PreToolUse coverage
  CONFIRMED — this spawned subagent's own first Bash call (creating the
  fixture at its literal protected path) was DENIED by `secret_file_guard`,
  reinforced by ~10 further denied Bash/Read/Edit probes. The `TaskOutput`
  relay surface is UNVERIFIABLE FROM WITHIN A SUBAGENT and is recorded as a
  main-thread-only check (likely class-(d), not a PreToolUse tool call). See
  RESEARCH-read-routes.md "Task 1.2 result".
- [ ] 🔄 **Task 1.3** (Grep-tool/Edit desk-answered; LSP/Skill/MCP/WebFetch/
  NotebookEdit/upload_asset + auto-inlining remain live-deferred): Edit on a
  protected file DENIED at PreToolUse (old_string never echoes back — probe
  #11). `Grep` tool could not be driven from this subagent (not in its
  toolset) — direct-path Grep is desk-covered by the guard's `path` field.
  The remaining surfaces (NotebookEdit, WebFetch `file://`, MCP wiring, LSP
  hover/documentSymbol, Skill bodies, Artifact `upload_asset`) and the
  no-tool-call auto-inlining routes (`@`-imports, `.claude/rules/` `paths:`
  globs) need a live main-session capture and stay open.
- [x] ✅ **Task 1.4** (live probes done 2026-08-26): Aliasing probes against
  the dummy fixture recorded per-route in RESEARCH-read-routes.md "Live probe
  results". Key outcomes: symlink read DENIED (realpath-resolved — better than
  predicted); hardlink read and pre-existing copy read ALLOWED and leaked the
  marker (class-(d) confirmed); same-invocation var, command substitution, and
  interpreter one-liners all DENIED; and a NEW class-(c) gap found —
  `dummy.vault-p*` trailing-wildcard glob token is allowed and leaks.
- [x] ✅ **Task 1.5**: Classify every route in the inventory as
  (b)/(c)/(d) with visibility column filled; resolve the marked DECIDE
  items: later-turn variable indirection heuristic, bidirectional glob
  matching, find/xargs combos, directory-rooted content grep, git
  revision-syntax reads
- [x] ✅ **Task 1.6**: Decide the output-side backstop: is daemon-side
  reading of the secret (in-memory, never emitted/logged) acceptable? Weigh
  against Task 1.1 — if `updatedToolOutput` is honoured, the secret in
  daemon memory buys PREVENTION (redacted substitution), not a report. The
  answer MUST be written as an amendment to `utils/secret_redaction.py`'s
  "exactly one code path" doctrine, not alongside it; internal digests stay
  unreachable from the `secret-meta` CLI (Decision 6)
- [x] ✅ **Task 1.7**: Write the research conclusion — layer stack
  recommendation + residual risks only OS-level controls (permissions,
  separate user, sandboxing) can close
- [x] ✅ **Task 1.8**: Map each Technical Decision to the research findings
  it depends on; confirm, revise or retire every decision marked
  "provisional pending Phase 1" (the output-leak layer exists ONLY if Task
  1.1 shows PostToolUse sees stdout; the Bash-authored-script scan in Task
  4.3 exists ONLY if Task 1.3 confirms visibility)
- [x] ✅ **Task 1.9**: Enumerate DAEMON-OWNED outputs as a route class
  (payload capture, debug/error logs, transcript archives per
  `utils/secret_redaction.py`; `staged_lint_gate`/`lint_on_edit`
  diagnostics): confirm `daemon/payload_capture.py` captures a successful
  read's payload verbatim (it redacts only word-list terms) and record what
  Task 4.5 must close — the guard must not WORSEN the artefact footprint
  for its residual routes (see BRAINSTORM.md daemon-artefacts section)

### Phase 2: Design finalisation (human review of research + open questions)

- [x] ✅ **Task 2.1** (via mid-execution user directives + adopted recommendations, Decisions 7-9): Resolve open questions with human against the
  completed research (default glob breadth incl. key material; keyed-HMAC
  vs opt-in plain hash; echo / git-commit-message exemption stance; which
  class-(c) heuristics to ship vs defer; secondary layers to include;
  final priority slot in 10–20 band). Named decision items: (a)
  **consumer-allowlist subcommand grammar** — deny `ansible-vault view|decrypt` (head-only allowlisting sanctions the most direct
  disclosure path; see BRAINSTORM.md trusted-consumer section); (b)
  **metadata disclosure** — bucketed `size_bytes` default and HMAC key-file
  mode precondition (see BRAINSTORM.md finding-5 section)
- [x] ✅ **Task 2.2**: Record decisions in Technical Decisions; update
  BRAINSTORM.md/RESEARCH doc where superseded

### Phase 3: TDD — matching core

- [x] ✅ **Task 3.1**: Failing tests for protected-path glob matching
  (defaults + config additive, canonicalisation of relative/`~`/`$HOME`
  spellings, symlink/realpath, worktree seeding case)
- [x] ✅ **Task 3.2**: Failing tests for Bash path-mention detection across
  the class-(b) and shipped class-(c) routes (direct readers, interpreter
  one-liners, cp/mv/ln/tar, substitution, sourcing, same-invocation
  variable indirection, glob-shaped mentions) and the exemptions
  (metadata helper; consumer + path_flags grammar)
- [x] ✅ **Task 3.3**: Implement matching utilities (reuse gitignore-glob
  machinery; constants per NO MAGIC)

### Phase 4: TDD — handler

- [x] ✅ **Task 4.1**: Failing tests for `SecretFileGuardHandler`
  (PreToolUseHandlerBase, GatingResult DENY, terminal, priority per Task
  2.1) across Read/Write/Edit/Grep/Bash (+ surfaces Phase 1 added); deny
  reason names the matched glob, never content, points at `secret-meta` +
  human-config-edit
- [x] ✅ **Task 4.2**: Implement handler; register HandlerID/Priority
  constants, wire into `handlers/pre_tool_use/__init__.py` and default +
  example configs
- [x] ✅ **Task 4.3** (Write/Edit content scan on script extensions; Bash-authored files deferred with Task 1.3): Secondary layer per research: Write/Edit content
  scan denying authorship of scripts that reference a protected path
  (closes the write-then-execute route); include Bash-authored files if
  Phase 1 confirmed feasibility
- [x] ✅ **Task 4.4**: `get_claude_md()` guidance: deny-by-default framing,
  exemptions, the (b)/(c)/(d) honest-limits summary, no-escape-hatch
  statement, OS-level-controls pointer, and the vault-payload scope
  boundary (protecting the password file does not protect vaulted vars)
- [x] ✅ **Task 4.5** (approach: EXCLUDE, not redact — see Decision 10): closed
  the Task 1.9 daemon-artefact seam. `daemon/payload_capture.capture_payload`
  gained a `protected_patterns` param; when `hook_input` names or Bash-mentions
  a protected path (via the SAME `secret_file_matching` primitives the guard
  uses), the WHOLE event is excluded from the capture file rather than written
  at all — redaction only removes known TERMS, and a protected path's globs
  say nothing about its content, so there is nothing safe to write back for
  the matched event. Wired at the one call site (`daemon/server.py`) via a new
  cached cross-handler resolver, `secret_file_matching.resolve_configured_patterns()`.
  `lint_on_edit`/`staged_lint_gate` now skip a protected path before running
  any lint command, closing the syntax-error-quotes-source-line route.

### Phase 5: TDD — metadata helper

- [x] ✅ **Task 5.1**: Failing tests for `secret-meta` core (exists/missing,
  bucketed size by default with exact size behind the plain-hash flag,
  mtime/mode, keyed HMAC digest with generated gitignored key, key file
  itself protected, refusal to emit a digest when the key file is
  group/world-readable, plain-hash flag per Task 2.1, and no CLI route to
  any backstop-internal digest — Decision 6)
- [x] ✅ **Task 5.2**: Implement helper as CLI subcommand + `utils/` core;
  JSON output; never prints content

### Phase 6: Hygiene checks

- [x] ✅ **Task 6.1** (permissions/ownership half shipped earlier in
  `secret-meta` output — `permissions_ok` + chmod 600 hint; the deferred
  SessionStart half shipped now, then fixed a review round — see
  Decision 11): new `SecretFileHygieneCheckerHandler`
  (`handlers/session_start/secret_file_hygiene_checker.py`, priority 62,
  default-enabled) enumerates every path matching the effective
  `secret_file_guard` globs via `git ls-files` (tracked, untracked-visible,
  untracked-ignored — three index reads, deterministic, no filesystem walk),
  and advises — never blocks — when a matched path is not gitignored, is
  git-tracked, or is group/world-readable (`mode & FileMode.GROUP_OTHER_MASK`).
  Outside a git repository (or when `git` is unavailable), gitignore/tracked
  checks are skipped as meaningless and only permissions are checked via a
  bounded fallback walk, which states explicitly in the advisory when its
  cap was hit rather than presenting a truncated scan as a clean one.
  Metadata only: no file content is ever opened. The Task 1.3 auto-inlining
  config check (`@`-imports, `.claude/rules/` `paths:` globs) is NOT included
  here: it is a distinct configuration-condition check unrelated to
  protected-file hygiene, and bundling it would have doubled this handler's
  scope for no shared code; left as a candidate for its own follow-up plan.
- [x] ✅ **Task 6.2**: Update `sensitive_content` guidance; stage
  truth-changes + config-changes manifests in `UNRELEASED/`

### Phase 7: Integration & acceptance

- [x] ✅ **Task 7.1**: `get_acceptance_tests()` using dummy fixture paths —
  never a real secret; cover one test per route class shipped
- [x] ✅ **Task 7.2**: Full QA green on main after merge (25/25); daemon
  restart verified RUNNING; live dogfood verified — Read, Bash `cat`, and
  `secret-meta` all behaved as designed against `.claude/block-words.secret`
- [x] ✅ **Task 7.3**: Client-mode verification (`dummy-client-repo.sh`
  create → cli status RUNNING → destroy) passed on main; docs
  (`HANDLER_REFERENCE.md`) shipped with the branch

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

### Decision 10: Task 4.5 closes the payload-capture seam by EXCLUSION, not redaction

**Context**: `redact_structure` removes known TERMS (the `sensitive_content`
secret word list) from a payload before it is written. A protected path's
GLOB tells us a file must never be read — it says nothing about what that
file's content actually contains, so there is no term to redact even when a
residual route slips a mention past the guard's deny rule.
**Decision**: `daemon/payload_capture.capture_payload` gained a
`protected_patterns` parameter; when the incoming `hook_input` names or
Bash-mentions a matching path (checked with the SAME `secret_file_matching`
primitives the guard itself uses — single source of truth, so this can never
disagree with what the guard would have denied), the WHOLE event is dropped
from the capture file rather than partially written. `lint_on_edit` and
`staged_lint_gate` are closed the same way: a protected path is skipped
before any lint command runs, because a syntax-error diagnostic can quote the
offending source line verbatim.
**Boundary (code review)**: `_touches_protected_path` inspects `tool_input`
fields (`file_path`/`notebook_path`/`path`/`command`) ONLY — it does not
recurse into arbitrary nested structures the way `redact_structure` does.
This matches every route the guard itself inspects (Task 4.1's field set), so
it closes exactly the seam Task 1.9 identified; a hypothetical future field
carrying a bare path outside those keys would need the same field added here
AND to the guard first, since the guard's own coverage is the ceiling this
seam-closer tracks.
**Residual gap (code review, accepted)**: `lint_on_edit`/`staged_lint_gate`
now SILENTLY skip a protected-path file rather than linting it — a
`*.secret*`-named source file (a real, if narrow, possibility given
Decision 7's intentionally broad default) is therefore never syntax-checked
by either surface, with no advisory noting the skip. This is the accepted
cost of the fix: linting it would risk exactly the diagnostic-quotes-source
leak the fix exists to close (a syntax error can echo the offending line),
and an advisory naming the skipped file adds no actionable content beyond
"this path is protected" (already known from `secret_file_guard`'s own
deny). A future enhancement could emit a content-free advisory ("N protected
file(s) excluded from lint") if the silent gap proves confusing in practice.
**Date**: 2026-08-26

### Decision 11: code-review fix round on Tasks 4.5/6.1 — findings and one rebuttal

**Context**: a code review of the worktree branch returned REQUEST CHANGES
with three mandatory findings and six advisory ones.

**Fixed (mandatory)**:

1. `secret_file_hygiene_checker`'s unfiltered `os.walk` + 5,000-entry cap
   could exhaust the cap inside an unrelated large subtree before ever
   reaching a protected file, silently reporting the tree clean. Replaced
   with `git ls-files` (three cheap index reads: `--cached`, `--others --exclude-standard`, `--others --ignored --exclude-standard`) as the
   primary route — deterministic, no walk. A non-git directory falls back to
   the bounded walk for PERMISSIONS ONLY (gitignore/tracked checks are
   meaningless there), and a hit cap is now stated explicitly in the
   advisory rather than silently reported as clean.
2. `resolve_configured_patterns`'s `except (OSError, RuntimeError)` did not
   catch `yaml.YAMLError` (malformed YAML) or pydantic's `ValidationError`
   (a `ValueError` subclass, schema-invalid config) — both propagated into
   `LintOnEditHandler`/`StagedLintGateHandler` callers. Widened to
   `(OSError, RuntimeError, ValueError, yaml.YAMLError)`, `import yaml`
   moved to module top-level (a lazy import inside the `try` would leave the
   `except` tuple's own `yaml.YAMLError` reference unbound on a failure
   before the import line ran — caught in a follow-up coordinator note, not
   the original review, and fixed the same way).
3. Added tests for the resolver's try: block against a REAL config file
   (mode: replace + custom protected_paths) — which caught a genuine bug:
   `Config`'s own `coerce_handler_configs` validator turns every handler
   entry into a `HandlerConfig` instance, not a plain dict, so the
   `isinstance(handler_cfg, dict)` guard always failed and the resolver had
   NEVER actually read a real project config, only ever the shipped
   defaults. Fixed to check `isinstance(handler_cfg, HandlerConfig)` and use
   `.options`. Added an equivalence test between the resolver and the
   guard's registry-injected `_patterns()` for the same `mode`/
   `protected_paths` pair.

**Rebutted**: the review's PREFERRED fix for finding 3 was having
`secret_file_guard` delegate to `resolve_configured_patterns()` so there is
only one resolution route. Not done: the guard's options arrive through the
registry's generic `setattr` injection (`registry.py`'s `register_all`),
which is the SAME mechanism every handler in the daemon uses and which also
applies tag filtering and `daemon.exclude_paths` inheritance the resolver
does not replicate. Delegating one handler to instead read raw YAML directly
via `resolve_configured_patterns()` would (a) diverge from that shared
convention for no other handler, (b) silently stop responding to the
registry-injection pattern every existing unit test for the guard already
relies on (`handler._mode = ...`, `handler._protected_paths = ...`
`setattr`-style, per Tasks 4.1–4.4), and (c) risk drift from the tag/exclude
inheritance the registry provides. The two routes are not actually
redundant — they read the SAME config through two different, already-tested
mechanisms — so the equivalence test (proving they compute the same answer
for the same inputs) is the correct fix, not architectural unification.

**Fixed (advisory, cheap)**:

- Added `FileMode.GROUP_OTHER_MASK`, a purpose-named alias for the existing
  `DAEMON_UMASK` bit pattern, used by the hygiene checker's permission test.
- Non-git directories: `_scan_repo` now detects git failure ONCE (any of the
  three `ls-files` calls returning non-zero) and returns `None`, at which
  point gitignore/tracked checks are skipped entirely (not run and reported
  false) and only permissions are checked, with an explicit "not a git
  repository" notice.
- Added `ProjectContext.is_initialized()`, a public classmethod, and moved
  `secret_file_matching.py`'s own check onto it.
- Recorded the lint-skip residual gap in Decision 10 above (a protected
  `.py`/`.sh`/etc. file is now silently never lint-checked) rather than
  adding an advisory line — reasoned there as an accepted cost.
- Stated the `_touches_protected_path` tool_input-field-only boundary in
  Decision 10.
- Registered the new handler in `daemon/init_config.py`'s generated template
  (parity with `skill_opportunity_detector`) and staged
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/vUNRELEASED.yaml` with a
  `recommended: true` entry (new default-enabled handler, per RELEASING.md
  Step 7). This worktree branched before main's own Task 6.2 commit added a
  `vUNRELEASED.yaml` with several other entries; the two will need merging
  (not rebasing) when this branch lands — a plain content merge, since both
  sides only ADD list entries.

**Not rebutted, not yet done**: none — every mandatory and advisory finding
above was either fixed or has a recorded reason it was not.
**Date**: 2026-08-26

### Decision 12: close the class-(c) trailing-wildcard glob gap (G2) by literal-edge overlap, not full glob intersection

**Context**: the live probe (see the "Live probe results" table in
RESEARCH-read-routes.md, row G2) found that `cat dummy.vault-p*` LEAKED a
protected file matched by `*.vault-password`, while the near-identical
`cat <dir>/*.vault-password` (G1) was correctly denied. The existing
glob-token heuristic (`_token_literal_residue` + a single `fnmatch` check
against each pattern's literal stem) requires the token's residue to be a
literal SUBSTRING of the stem — true for G1 (whole suffix literally present)
but false for G2, because the pattern's own arbitrary leading `*` means the
real file's `dummy` prefix has no counterpart in the stem at all.

**Options considered**:

1. Filesystem `glob.glob()` expansion of the token against the real cwd.
   Rejected: cwd is not passed into `find_protected_mention` (would widen
   the contract for every caller); also non-deterministic.
2. Full two-pattern glob LANGUAGE INTERSECTION (both token and stem as
   globs, ask whether any string satisfies both). Rejected: for two
   unconstrained `*`s an intersection can always be built by splicing
   arbitrary filler between two literal fragments — `dummy.txt*` intersects
   `*.vault-password` via the filename `dummy.txt.vault-password`, so it
   would flag the required-ALLOWED negative control.
3. **Chosen — literal-edge overlap** (`_glob_token_overlaps_stem`,
   `_suffix_prefix_overlap_length`): the token's literal residue and the
   pattern's literal stem must share a DIRECT boundary — the residue's
   suffix equals the stem's prefix (or vice versa, for the mirrored
   leading-wildcard-token case) with no filler spliced in between. This is
   exactly the shape of a genuine truncation: a real filename is
   `<arbitrary><fixed>`, and truncating it mid-`<fixed>` produces a token
   whose literal tail IS the leading part of `<fixed>`, by construction —
   not a coincidental resemblance manufactured by inserting text nothing
   attests to.

**Threshold**: overlap must be >= `_MIN_GLOB_OVERLAP_CHARS` (2) characters.
A 1-character overlap is measurably too common in ordinary vocabulary to be
worth flagging, and 2 is the smallest overlap a LEADING-wildcard shipped
stem ever needs for a real truncation (`dummy.v*` needs exactly the 2-char
`.v` overlap against `.vault-password`). This is not a special case tuned to
one input: `d*` (asked for explicitly during this fix's TDD) cannot reach 2
characters of overlap against ANY shipped stem, by construction — its own
literal residue is a single character — so it stays allowed as accepted
residual, the same way an unrelated `dummy.txt*` stays allowed because no
shipped stem shares a boundary with `.txt`.

**Addendum — over-blocking regression, same day**: the FIRST cut ran the
overlap test against EVERY stem, including exact-filename stems
`id_rsa`/`id_ed25519`. Those have no leading wildcard, so their edge chars
coincidentally overlap common tokens (`sample*`, `grid*`, `valid*`,
`android*`, `raid*`, `hybrid*`, `id*` were all wrongly denied). Root cause:
overlap is only meaningful for a **leading**-wildcard pattern — an
exact-filename or start-anchored pattern (`.vault-pass*`) has no arbitrary
prefix to hide behind, so a genuine truncation of THOSE is already a literal
prefix of the stem, caught by the pre-existing substring+fnmatch check.
**Fix**: gate the overlap branch on `pattern.startswith("*")`. `id_rs*` and
`id*` (real truncations of `id_rsa`) still deny via that untouched path.

**Verified**: leading-wildcard truncations (`dummy.vault-p*`,
`dummy.vault-*`, `dummy.v*`) and a leading-wildcard reverse-only case
(`*passXXX`) stay DENIED; `id_rs*`/`id*` stay DENIED via substring+fnmatch;
`d*`, `dummy.txt*`, the coordinator's FP list, and `.secret`-stem controls
(`start*`, `reset*`, `.ssh*`, `market*`) stay ALLOWED — 96 tests green.

**Also fixed in this pass** (same probe report, "Allowlist/secret-meta
sequencing fragility" finding): `secret_file_guard`'s `get_claude_md()` now
tells agents to run `secret-meta` and an allowlisted consumer command as
their OWN standalone Bash statement — the exemption in
`is_exempt_invocation` only ever covered a single command, and chaining
`; echo done` after it (fail-closed, correct) was previously undocumented,
reading as a broken helper rather than a stated constraint.

**Date**: 2026-08-26

## Success Criteria

- [ ] RESEARCH-read-routes.md complete: every route has verified visibility,
  a (b)/(c)/(d) classification AND a per-route expected-verdict entry; all
  DECIDE items resolved; conclusion written
- [ ] Every class-(b) route denied live; class-(c) behaviour matches the
  expected-verdict column in RESEARCH-read-routes.md (Task 7.1 asserts
  against that table); class-(d) residual risk stated in resident guidance
  with OS-level mitigations named
- [x] Permissions/ownership advisory fires on group/world-readable protected
  files with remediation text (Task 6.1)
- [x] No residual-route read lands verbatim in payload capture or logs
  (Task 4.5)
- [ ] `secret-meta` returns metadata JSON with no content bytes;
  `ansible-vault --vault-password-file <protected>` consumer commands pass
- [ ] Deny reasons never include file content; verdict log clean
- [ ] No escape hatch exists
- [ ] 95%+ coverage, full QA green, daemon restart verified, client-mode
  verified — the current worktree session verified unit+integration tests
  (12327 + 1722 passed) and per-file ruff/black/mypy/bandit/magic-values
  green; `./scripts/qa/llm_qa.py all` could not run in this worktree (no
  bootstrapped venv at `untracked/venv*` here — self-install venvs are
  project-path-slug-keyed and this worktree has none); ONE integration test
  (`test_every_earning_handler_has_a_section_in_claude_md`) requires an
  actual daemon restart to regenerate `CLAUDE.md` and is deferred to the main
  session, which also owns the daemon-restart + client-mode verification

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
