# Options: shapes of opencode support, and a recommendation (Plan 00549 Task 2.3)

Research only. This paper turns the Phase 1 and Phase 2 documents in this folder into candidate shapes of support,
compares them, and recommends a sequence. It does not re-research opencode; every opencode fact below is cited to the
input document that established it, and through it to the opencode clone at
`c93aaae37157d785f76a8e9a9243a6560e286468` (product version **OpenCode V2, 2.1.2**; the `github-v1.2.27` tag is not
the product version).

**Inputs and the short names used below.**

- SURFACE: `RESEARCH-opencode-extension-surface.md`
- ARCH: `RESEARCH-opencode-architecture.md`
- DUAL: `RESEARCH-dual-tool-repos.md`
- COUP: `RESEARCH-daemon-couplings.md` (the 41 couplings: R1-R10, B1-B31)
- AMD: `RESEARCH-claude-code-agents-md.md`
- SYNC: `RESEARCH-multi-agent-config-sync.md`
- MAP: `MAPPING-events.md`
- PLANWF: `ANALYSIS-plan-workflow.md`
- 00292: `../00292-codex-cli-dual-host-research/OPTIONS-abstraction.md` (the Codex precedent)
- PERF: `CLAUDE/Performance/README.md` (this repository's measured hook latencies)

**Owner constraints this paper is written against** (from the Task 2.3 brief):

1. opencode support is wanted, as a new epic.
2. `AGENTS.md` must be enforceable as the canonical instruction file.
3. Project config must stay in sync across agents.
4. Performance is a priority.
5. No silent fallbacks: when protection is not in force, something must say so, loudly.

Statements marked **INFERENCE** are this paper's reasoning from the inputs, not a fact read from source. Statements
marked **UNVERIFIED** are carried over from an input that could not verify them.

---

## 1. The facts that decide the shape

These five facts, all established upstream, constrain every option. They are restated so the options can be judged
against them.

1. **opencode has no out-of-process command hook.** `Config.Info` has no `hooks` key; the only blocking surface is an
   in-process TypeScript plugin (SURFACE §3; ARCH §2.3). The daemon's whole registration model (COUP R5: a host that
   execs `bash .claude/hooks/<event>` per event) has no opencode counterpart. Whatever we build for opencode, the
   attach point is a V2 `@opencode/plugin` module.
2. **Only `tool.execute.before` can fail.** It blocks by throwing (`Tool.Error`) and rewrites by mutating `input`;
   `permission.evaluate` can set `deny`; every other hook's failure type is `never` (MAP "How opencode is hooked";
   SURFACE §5). There is **no per-hook timeout**: a hung hook stalls the call indefinitely (SURFACE §5).
3. **The safety-guard half of the daemon ports; the autonomy half does not.** At the mechanism level, 108 of 187
   handlers (58%) map at FULL fidelity, 54 (29%) PARTIAL, 7 (4%) OBSERVE-ONLY (Stop) and 18 (10%) NONE (status line)
   (MAP Summary). About 10 of the 87 PreToolUse handlers are keyed on tools or inputs opencode lacks (MAP Summary).
   There is no stop veto, only an after-the-fact re-drive via `session.synthetic`/`prompt`, which does restart the
   loop (PLANWF §1 facts 1-2). There is no scheduler and no `/goal` (PLANWF §1 fact 3).
4. **opencode V2 reads `AGENTS.md` only.** It does not read `CLAUDE.md` at all, despite its docs; the only `.claude/`
   content it reads is `skills/` (DUAL §1 findings 1 and 3). Today an opencode session in a daemon-managed repository
   gets **no project instructions and none of the daemon's protections** (DUAL §1 finding 5). Claude Code reads
   `AGENTS.md` only as a fallback when no `CLAUDE.md` exists; the `CLAUDE.md` = `@AGENTS.md` shim is the one layout
   that restores full native behaviour, including `InstructionsLoaded` (AMD §4-§5).
5. **opencode churns its plugin contract.** v2.1 intentionally broke plugin contracts in a minor release; the website
   still documents the V1 API, which the V2 loader rejects (SURFACE §0, §7). A V1-shaped or out-of-date plugin
   **fails to load with only a log line** (SURFACE §5, "Errors in a plugin's async `setup` ... are logged"). That is
   the single biggest silent-fallback hazard in the whole design, and §4 addresses it directly.

---

## 2. The candidate shapes

Five shapes, refined from the brief's A-E. Two refinements matter:

- The **stop re-drive** belongs in the plugin (B), not in the external driver (C). A plugin already has
  `ctx.event.subscribe()` and the `session` domain API (ARCH §2.1), so re-driving a session needs no second process.
  C shrinks to what genuinely needs a process that outlives the opencode server: scheduling.
- **Fail-loud is not an option; it is a cross-cutting requirement.** 00292 reached the same conclusion for Codex
  (its Option D, "ship the degradation mode alongside it from day one", 00292 lines 452-458). Here it is designed
  into each shape (§4) rather than offered as a sixth option.

### Option A: tool-neutral layer first

**What it is.** Protections and guidance that work for every agent and for humans, with no opencode integration:

1. **Git hooks for the commit gates.** Provision `core.hooksPath` hooks (`pre-commit`, `commit-msg`) that call the
   same logic the daemon's PreToolUse commit gates call today. The cheapest moves are already CLIs: `plan-qa --check-staged` / `--lint`, `docs-qa`, `issue-validity` (PLANWF §4 table; `bin/hooks-daemon --help` lists
   `plan-qa`, `docs-qa`, `issue-validity`). Conflict markers, staged lint and the sensitive-content added-line scan
   are pure functions over staged content but have no CLI entry point yet (PLANWF §4 row 4).
2. **`AGENTS.md` canonical.** The daemon provisions `AGENTS.md` as the shared file and a `CLAUDE.md` shim whose first
   line is `@AGENTS.md`, followed by Claude-only extras (AMD §5 design 1; DUAL §4 strategy A; SYNC §7 I1).
3. **The daemon's generated guidance moves to `AGENTS.md`.** `ClaudeMdInjector` (COUP B12) gains an `AGENTS.md`
   target with host-neutral tool vocabulary (COUP B3; SYNC §7 I2).
4. **Drift and canonical-file enforcement.** SYNC §7 E1-E5: an edit-time deny of writes to shim/generated files
   naming the canonical source (E1); a content guard keeping Claude-only constructs out of `AGENTS.md` (E2); a
   SessionStart drift report in the `deployed_artefact_drift` style (E3); a commit gate (E4); and the git-hook / CI
   backstop for any agent (E5). AMD §5 design 2 lists the exact checks (a)-(e): an `AGENTS.md` invisible to Claude
   Code, a `CLAUDE.md` that does not import its sibling, shim divergence, a committed `CLAUDE.local.md`, files above
   the git root.

**Delivers.** The owner's `AGENTS.md`-canonical requirement in full for Claude Code (edit-time and commit-time) and
at commit time for every other tool. Instructions reach opencode for the first time. The commit gates become
dual-enforced under Claude Code (PLANWF §4: "Under Claude Code the commit gates become dual-enforced").

**Couplings covered.** B11 (plan workflow assets, now enforced at commit for every tool), B12 (guidance channel),
B3 (neutral wording), and part of B13 (skills are already shared through `.claude/skills`, DUAL §1 finding 3).
3 primary of 41.

**Handler fraction.** About 8-9 handlers' logic re-hosted at commit time (the `*_commit_gate` family, the sensitive
content commit scan, staged lint, closing keyword, remote-docs provenance; DUAL §7), about 5% of 187, **but for
every agent and every human**. Plus the guidance for all of them. None of the 87 PreToolUse edit-time guards.

**Cost and complexity.** Small to medium. Mostly assembly of existing pieces: the gate logic, `ClaudeMdInjector`,
`deployed_artefact_drift`, `validate_instruction_content` (SYNC §7 building blocks). New work: CLI entry points for
the three gates that lack them; a hook installer that respects an existing `core.hooksPath` or pre-commit framework;
the neutral-vocabulary renderer; migration tooling for nested `CLAUDE.md` files (this repository has 12, AMD §5
design 5).

**Risk.** Low on host churn: git hooks and `AGENTS.md` are the most stable surfaces in the whole space; AGENTS.md is
stewarded by the Linux Foundation's AAIF (SYNC §1 finding 1). Two real risks:

- **Size.** This repository's `CLAUDE.md` is 118,604 bytes, mostly the generated section. Codex truncates
  instructions silently at 32 KiB (SYNC §6 point 5). Moving the section into `AGENTS.md` unchanged would be truncated
  for Codex and expensive for everyone. The section needs a compact neutral form with depth behind
  `bin/hooks-daemon explain-rule` and a skill (SYNC §7 I2 raises the same point).
- **Behaviour change for existing Claude Code clients.** Rewriting a client's instruction layout is a migration, not
  an upgrade side effect. It must be opt-in per project, with an explicit migrate command.

**Performance.** Commit hooks add the gate cost once per commit, outside the tool-call hot path. The `plan-qa --check-staged` path is already run per commit today via PreToolUse; under Claude Code it would now run twice
(PreToolUse plus git hook). **INFERENCE:** dedupe by having the PreToolUse gate stamp the staged tree hash it
approved and the git hook skip a matching hash.

**Fail-loud behaviour.** Git hooks fail closed by construction (non-zero exit aborts the commit). The silent hole is
`--no-verify` and an unset `core.hooksPath`; close it with a SessionStart/startup check that reports "git hooks not
installed" for every host the daemon knows about, a `{shell, "git commit*--no-verify*", deny}` rule in
`opencode.json` (PLANWF §4 limits), and CI as the backstop (DUAL §7). If the daemon's venv is missing, the hook must
exit non-zero naming the repair command, never skip.

### Option B: opencode bridge plugin plus a daemon host adapter

**What it is.** 00292's Option A (host adapter at the front controller), applied to opencode, with the forwarder
replaced by an in-process plugin because there is no command hook (§1 fact 1).

- **The plugin (TypeScript, thin).** A V2 Promise plugin `{ id, setup }` deployed at
  `.opencode/plugins/hooks-daemon/` and registered in `opencode.json` `plugins` (SURFACE §1.1, §1.4). It registers
  `tool.execute.before`, `tool.execute.after`, `permission.evaluate`, `session.prompt`, `session.context`,
  `session.compaction`, `shell.create.before` and a filtered `event.subscribe` (SURFACE §3 bridge 1). It forwards
  each to the daemon socket and applies the verdict: throw to deny, mutate to rewrite, splice into `system[]` to
  inject (MAP Table 2). It also runs the Stop re-drive: on `session.execution.succeeded` for a top-level session it
  asks the daemon, and on a block it calls `session.synthetic` with the reason, keeping its own re-entry counter in
  place of `stop_hook_active` (MAP Stop row; ARCH §2.1).
- **The host adapter (Python, in the daemon).** The daemon learns a `host` field on the request envelope
  (`server.py:2507-2508` reads `event`/`hook_input` today, COUP R4). For `host: opencode` it translates the payload
  into the dict keys handlers already read (COUP R2, `protocol.py` `HookInputField`), maps tool names and input fields
  (MAP Table 3: `shell`→`Bash`, `write`/`edit`→`Write`/`Edit`, `subagent`→`Task`, `question`→`AskUserQuestion`), and
  answers with a host-neutral verdict (decision, reason, context, updated input) instead of Claude Code wire JSON
  (COUP R3). **Engineering decision:** translation lives in Python, not TypeScript, so the mapping is tested by the
  existing QA stack and the plugin stays a dumb pipe that rarely needs to change when the daemon does.
- **The `patch` parser.** opencode's `patch` tool has no Claude Code equivalent (MAP Table 3). Every write guard
  (TDD, QA suppression, sensitive content, error hiding, comment changelog) needs per-file `content`/`new_string`
  synthesised from the patch before it covers all opencode file mutations (MAP Summary; COUP B2). This is the largest
  single adapter item.
- **Identity re-keying.** The disclosure tracker keys on `transcript_path` as the per-agent identity (COUP R7). The
  opencode analogue is the session ID, with child sessions for sub-agents (ARCH §3.3). Session thread grouping uses
  the hook process's `SO_PEERCRED` pid (COUP B21; `src/claude_code_hooks_daemon/utils/session_thread_group.py:469`
  `peer_pid_of`). **INFERENCE:** under a plugin every request comes from the one long-lived opencode server pid, so
  that grouping must re-key on `sessionID` for this host or it will merge every session into one.
- **Project routing.** One opencode server can serve many projects (ARCH §1.2, §8.1 point 2). The plugin routes by
  `ctx.location` to that project's daemon. **Engineering decision:** the daemon writes its socket directory to a
  discovery file at start, and the plugin reads it, rather than re-implementing `init.sh`'s hostname-suffix path
  logic (`_get_hostname_suffix`, COUP B25) in TypeScript, where it would drift.

**Delivers.** Edit-time enforcement of the safety-guard layer inside opencode: destructive git, sed, pipe, secrets,
TDD, QA suppression, plan-number and plan-journal guards, sensitive content, the commit gates (as PreToolUse on
`shell`). Per-step guidance injection through `session.context`, which is stronger than Claude Code's because it
survives compaction (MAP SessionStart row). Sub-agent report checks by rewriting the child's output before the parent
sees it (MAP SubagentStop row). The stop-explanation contract at re-drive fidelity. With Option A's E1/E2 handlers,
`AGENTS.md`-canonical enforcement becomes edit-time in opencode too.

**Couplings covered.** 23 primary of 41: R1, R2, R3, R5 (registration becomes the `plugins` entry), R6 (the plugin
replaces the forwarder family), R7 (identity part only), R9, R10 (the relay is not used; its fail-closed carve-out
moves into the plugin), B1 (a new `contracts/opencode-plugin/` set, copying the vendored-contract pattern), B2, B4
(re-drive), B8 (partial), B9 (`question` tool, plus `{question, *, deny}` for unattended projects, PLANWF §3), B10
(switched off for this host), B20 (partial), B21, B22, B23, B24 (partial, via `session.retry` / step failures),
B28, B29, B30 (an opencode acceptance harness), B31 (the plugin's own timeout).

**Handler fraction.** Mechanism exists for 162 of 187 handlers (FULL plus PARTIAL, 87%; MAP Summary). The realistic
first tranche, the safety layer, is about 94 handlers (87 PreToolUse less about 10 tool-specific, plus 16 PostToolUse
and 1 PermissionRequest), about 50%, plus the context-only SessionStart and UserPromptSubmit handlers once their
Claude-setup checks (`hook-registration-checker`, `ccy-supervisor-integrity`, ...) are marked not-applicable for
this host (MAP SessionStart row).

**Cost and complexity.** Large: the biggest item in the epic. Concentrated in known files, as 00292 found for Codex:
`core/event.py`, `core/hook_result.py` (a host-neutral verdict path beside the ~450-line Claude serializer),
`constants/events.py` (a per-host capability table), `constants/tools.py`, the patch parser, the identity re-key,
`install/*` (deploy the plugin), a plugin of a few hundred lines of TypeScript, and an acceptance harness that drives
a real opencode server. A second toolchain (Bun/TypeScript) enters the repository's QA.

**Risk.**

- **Plugin API churn (high).** v2.1 broke plugin contracts in a minor release (SURFACE §7 stability key). Pin a
  supported opencode version range; vendor the plugin contract as `contracts/opencode-plugin/` with a staleness check
  (copying B1's `contract_staleness` pattern); run the acceptance harness against the pinned version in CI.
- **Docs are wrong (medium).** The website documents V1 (SURFACE §0). Every contract fact must come from the
  pinned source, never from the docs.
- **Open unknowns (medium).** UNVERIFIED in the inputs and decisive for B: what a rejected non-`execute.before` hook
  does to a turn (SURFACE §5); whether Bun's `node:net` Unix sockets work in a plugin (SURFACE §3); whether every
  mutating tool calls `permission.assert` (needed for §4's fail-closed baseline); whether plugin-sent `synthetic`
  messages re-enter `session.prompt` (MAP UserPromptSubmit row, a loop risk); re-drive timing (PLANWF Gaps). A
  spike resolves these before the build (§5 step 0).
- **Competing plugins.** rulesync emits its own `.opencode/plugins/rulesync-hooks.js` (SYNC §1 finding 3, §7 S1).
  Callbacks run in registration order (SURFACE §5), so another plugin can mutate input after the daemon approved it.
  **INFERENCE:** the daemon's plugin must register last for `execute.before` (or re-check the final input), and the
  startup report should list other loaded plugins (`ctx.plugin.list`, SURFACE §1.4).

**Performance.** This is where opencode can be *faster* than Claude Code.

| Path                               | Measured or expected p50                                                    | Source                                 |
| ---------------------------------- | --------------------------------------------------------------------------- | -------------------------------------- |
| Claude Code, Python transport, e2e | 32.1 ms (34.1 ms in the relay comparison)                                   | PERF lines 155, 94                     |
| Claude Code, Rust relay, e2e       | 4.3 ms                                                                      | PERF line 94                           |
| Daemon dispatch alone              | 1.8 ms (38 handlers) to 10.2 ms (80 handlers)                               | PERF line 49                           |
| opencode plugin → socket → daemon  | **expected** dispatch plus well under 1 ms of transport; no process spawned | INFERENCE, to be measured in the spike |

The plugin is already resident in the server process, so the per-event process spawn that dominates Claude Code's
cost (PERF: "the irreducible per-event floor is ~2 ms bash + ~18 ms CPython interpreter start") disappears. Three
performance traps, each an engineering decision rather than an owner question:

1. **`session.context` fires on every model step** (ARCH §2 row 6). Asking the daemon each step would add a hop per
   step for no change. The plugin caches the guidance per session and re-fetches only when the daemon's guidance
   version changes (returned on every verdict, or pushed through plugin RPC, SURFACE §3 bridge 3).
2. **The event bus carries about 110 event types** (SURFACE §7). The plugin filters in-process and forwards only the
   handful that have handlers; forwarding everything would recreate the status-line CPU problem.
3. **No host timeout** (§1 fact 2). The plugin imposes the same budget the relay does today (`hooks_relay.rs` 45 s
   cap, 10 s handoff, COUP B31), so a hung daemon costs a bounded delay and a loud failure, never a stalled session.

**Fail-loud behaviour.** See §4; B is where it is hardest and where most of the design effort goes.

### Option C: external driver for the autonomy layer

**What it is.** A daemon-side client of the opencode server's HTTP/SSE API. It attaches through
`$XDG_STATE_HOME/opencode/service.json`, which holds the server URL and a private password readable by any process
of the same user (ARCH §1.2). It owns what must outlive one opencode server process: a scheduler for
`persistent_crons` and failsafe ticks (with zero-token `[awaiting-human]` suppression done daemon-side), stand-in
ticks, and re-briefing a coordinator after a server restart (PLANWF §5 C.1-C.2). It could also stand in for the ccy
PTY supervisor (COUP B7) by sending `/goal`-equivalent prompts through the API instead of typing into a TUI.

**Refinement.** The stop re-drive is *not* in C (it is in B, above). PLANWF §5 A.6 also offers a cheaper
scheduler with no driver at all: an OS timer running headless `opencode run` ticks. C is only worth building if the
owner wants opencode sessions to be as autonomous as Claude Code sessions under ccy.

**Couplings covered.** B5 (crons), B6 (`/goal`), B7 (supervisor), and hardening of B4. 3 primary of 41.

**Handler fraction.** About 6%: the 7 Stop handlers' inputs (`session_crons`, the failsafe tick) plus the cron
pieces of SessionStart, PostToolUse and UserPromptSubmit (COUP B5).

**Cost and complexity.** Medium. A long-lived async HTTP/SSE client inside the daemon, reconnect logic, and a
scheduler. It duplicates nothing in Claude Code's path, so it is pure addition.

**Risk.**

- **Trust.** Reading `service.json` gives the daemon the password to drive every session of that user's opencode
  server, not just this project's (ARCH §1.2). That is a real privilege expansion and is the one owner decision in C.
- **Event loss.** Each SSE subscriber has a 4,096-event buffer and overflowing it **ends the subscription**
  (ARCH §1.3). A driver must detect the end, reconnect and reconcile from the API, or it silently stops scheduling.
- **Races.** Out-of-process permission replies race the human UI (SURFACE §3 bridge 2), so C must never be the
  permission path; B is.
- Some session routes are under `/api/experimental/` (SURFACE §7).

**Performance.** Off the tool-call hot path entirely. A persistent SSE connection per opencode server; negligible.

**Fail-loud behaviour.** A driver that loses its connection must say so in the next session it can reach (a
`session.context` banner via the plugin) and in `bin/hooks-daemon status`; a scheduler that is not running is
exactly the "silent" failure the owner forbids.

### Option D: config generation and sync

**What it is.** Keeping agents, commands, skills, MCP servers and permissions in sync across tools, separate from
instruction files (which Option A owns). Three sub-shapes (SYNC §7 S1-S4):

- **D1, daemon-native generator, narrow scope.** The daemon renders only what it deploys itself:
  `.opencode/agents/*.md` from `.claude/agents` (incompatible frontmatter, DUAL §3.2), `.opencode/commands/`
  (`plan-new`, `journal`, `issue-sdlc`, `plan-qa`, PLANWF §3), its `opencode.json` keys (`plugins`, `permissions`
  translated from daemon-managed deny rules, `instructions`), and a per-host config-dir twin of
  `utils/claude_config.py` (COUP B15). It reuses the md5 ownership ledger in `client_owned_assets.py` with a second
  namespace (DUAL §6 items 3, 8).
- **D2, rulesync as the project's generator, daemon as enforcer.** rulesync covers eight feature types across about
  60 tools, merges only its own keys into `opencode.json` and `.claude/settings.json`, and has `generate --check`
  (SYNC §4). The daemon detects a `.rulesync/` tree and runs `generate --check` as a SessionStart report and a commit
  gate (SYNC §7 E3-E4). It never writes `.rulesync/` content.
- **D3, a general daemon-owned sync tool for all project config.** Rejected below.

**Delivers.** The owner's "project config kept in sync across agents". D1 alone keeps the daemon's own assets in
sync; D2 extends that to the project's own artefacts without the daemon owning a generator.

**Couplings covered.** B13, B15, B26, and the config half of R5. 3 primary of 41.

**Handler fraction.** 0: this is provisioning, not handlers. It changes what the agent *knows* and what opencode's
own permission engine denies before any plugin runs.

**Cost and complexity.** D1 small to medium (renderers plus ledger namespace). D2 small (detect, run, report). D3
large and open-ended: rulesync releases near-daily (SYNC §4, v40.1.0 on 2026-10-22); re-implementing that is scope
creep beyond a hooks daemon (SYNC §7 S2).

**Risk.** D1: frontmatter dialects drift per opencode release; the vendored-contract pattern covers it. D2: a Node
dependency on clients that want it, and rulesync's opencode hooks plugin competes with ours (SYNC §7 S1; see B's
competing-plugin risk).

**Performance.** Generation runs at install, upgrade and on demand; drift checks at SessionStart and commit. No hot
path.

**Fail-loud behaviour.** Generated files out of date are reported (SessionStart) and denied at commit (E4), never
silently regenerated over a human edit. A generated file edited by an agent is denied at edit time (E1).

### Option E: do nothing, Claude Code only

**What it is.** Document that the daemon protects Claude Code sessions only, and that an opencode session in a
daemon-managed repository runs with no instructions and no guards (DUAL §1 findings 1 and 5).

**Delivers.** Nothing new. Zero cost, zero churn exposure.

**The honest case for it.** opencode's plugin contract is the least stable surface in the space (§1 fact 5); its
autonomy layer lacks the stop veto and scheduler the daemon's unattended loop is built on (§1 fact 3); and a
"Claude Code protocol monoculture" is forming (Factory Droid, Crush, Pool; SYNC §1 finding 4), so the daemon already
covers more than Claude Code without opencode.

**Why it does not hold.** The owner has asked for the epic. More concretely, E leaves today's silent hole in place:
a developer who opens this repository in opencode gets no instructions and no guards, and nothing tells them. That
contradicts constraint 5 even if no opencode support is ever built. Option A's first increment fixes that hole for
the cost of a startup check and a git hook.

---

## 3. Cross-option comparison

| Dimension                        | A: tool-neutral                       | B: bridge plugin + adapter                   | C: external driver                     | D1/D2: config sync            | E: nothing  |
| -------------------------------- | ------------------------------------- | -------------------------------------------- | -------------------------------------- | ----------------------------- | ----------- |
| Couplings (primary, of 41)       | 3 (B3, B11, B12)                      | 23                                           | 3 (B5, B6, B7)                         | 3 (B13, B15, B26)             | 0           |
| Handlers brought to opencode     | ~5% of logic, commit-time, every tool | ~50% first tranche; 87% have a mechanism     | ~6% (stop and cron inputs)             | 0 (provisioning)              | 0           |
| Benefits Claude Code users too   | Yes (dual enforcement, AGENTS.md)     | Indirectly (host-neutral core)               | No                                     | Yes (sync checks)             | n/a         |
| Covers tools other than opencode | Yes, every tool and humans            | No                                           | No                                     | D2 yes                        | n/a         |
| Owner's AGENTS.md requirement    | Delivers it                           | Extends it to edit-time in opencode          | No                                     | Complements it                | No          |
| Owner's config-sync requirement  | Instructions only                     | No                                           | No                                     | Delivers it                   | No          |
| Cost                             | Small-medium                          | Large                                        | Medium                                 | D1 small-medium, D2 small     | None        |
| Churn exposure                   | Low (git, AGENTS.md)                  | High (V2 plugin API)                         | Medium (HTTP API, experimental routes) | Medium (frontmatter dialects) | None        |
| Hot-path latency                 | None (commit time)                    | Expected better than Claude Code's relay     | None                                   | None                          | n/a         |
| Worst silent-failure mode        | Hooks not installed / `--no-verify`   | Plugin fails to load (logged only)           | SSE subscription ended on overflow     | Generator never run           | Whole thing |
| Mitigation (§4)                  | Startup check, CI, shell deny rule    | Permission baseline that asks without plugin | Reconnect + banner + `status`          | Drift report + commit gate    | —           |

Couplings that no option covers, and should be declared unsupported for opencode rather than emulated: R8 (status
line: no external status-line surface, ARCH §8 row 17), B16 (Claude Code plugins), B17 (Anthropic model and pricing
vocabulary; rebuild later against opencode's per-session cost if wanted, ARCH §8 row 24), B18 (usage pause: no Claude
subscription telemetry), B19 (teammates), B27 (Claude-only tools). 6 of 41. The remaining 3 (R4, B14, B25) are
host-neutral and need no work. Total: 3 + 23 + 3 + 3 + 6 + 3 = 41.

---

## 4. Fail-loud design (cross-cutting, required in every shape)

The owner's constraint, restated as a testable rule: **for every host, every handler is in exactly one of three
states, and the state is visible: enforced, degraded (with the degradation named), or unsupported (named).** A
handler that silently does nothing is a defect.

1. **Per-host capability table.** Extend `src/core/decision_capability.py` and `REFUSAL_CAPABLE_EVENTS`
   (`hook_result.py:127-160`, COUP R3) with a host dimension. Each handler declares what it needs (block, rewrite,
   inject, stop veto, transcript, crons). At daemon start, for each host it serves, the daemon computes the three
   lists and publishes them through `bin/hooks-daemon status`, the generated guidance section, and a `session.context`
   line in opencode. This is 00292's Option D, made concrete with the vocabulary the codebase already has.
2. **Daemon down or unreachable (plugin path).** `tool.execute.before` throws a `Tool.Error` naming the condition and
   the repair command: fail closed, as the relay's fabricated deny does today (`hooks_relay.rs:222-260`, COUP R10).
   On `ECONNREFUSED` the plugin starts the daemon once (the `ensure_daemon` equivalent, COUP B25) and denies the
   current call with "daemon starting, retry", mirroring `daemon_loading_stdout` (COUP R1). The non-failable hooks
   (`execute.after`, `session.context`, `session.prompt`) catch everything (an unhandled rejection is an Effect
   defect with UNVERIFIED consequences, SURFACE §5) and inject a visible "guards inactive: <reason>" line instead.
3. **Plugin not loaded at all (the hazard in §1 fact 5).** A plugin that fails to load cannot report its own
   failure. **Engineering decision:** the provisioned `opencode.json` sets a permissions baseline of `ask` for the
   mutating actions (`shell`, `edit`), and the plugin's `permission.evaluate` turns those asks into `allow` (or `deny`)
   when, and only when, the daemon is reachable and the verdict for that call is known. Without the plugin, every
   shell command and edit prompts the human: loud, never silent. `permission.evaluate` can loosen `ask` but not a
   config `deny` (SURFACE §4), which is why the baseline is `ask`, not `deny`. Two caveats: it covers only tools that
   call `permission.assert` (UNVERIFIED as complete; MAP Table 2 "ask" row), and in headless `opencode run` an ask
   blocks the run, which is the fail-closed behaviour wanted. The spike (§5 step 0) must verify both.
4. **Unsupported opencode version.** The plugin checks the server version at `setup` against the pinned range. Out of
   range: fail closed on `execute.before` with a message naming the supported range and an explicit opt-in key in
   `hooks-daemon.yaml`; with the opt-in set, run and inject a persistent "untested opencode version" line. Never a
   quiet best effort.
5. **Commit-time gates.** A git hook that cannot find the daemon's venv exits non-zero with the repair command. A
   repository whose hooks are not installed is reported at every daemon start and by the opencode plugin's session
   banner.
6. **External driver (C).** A dropped SSE subscription or a stopped scheduler appears in `status` and in the next
   reachable session's context.

---

## 5. Recommendation and sequencing

**Recommendation: A first, then B for the safety layer, with D1 alongside B and D2 as an optional integration. Defer
C until the owner wants unattended opencode sessions. Declare the six unportable couplings unsupported for opencode.**

Reasoning from the evidence:

- **A is the only shape that delivers the owner's AGENTS.md requirement, benefits Claude Code users immediately, and
  covers every tool.** It also closes today's silent hole (DUAL §1 finding 5) before any opencode code exists. It
  carries the least churn risk. It is the natural first plan because B, C and D all assume `AGENTS.md` as the
  guidance channel.
- **B is where the daemon's value is.** The safety-guard layer ports at full fidelity (MAP Summary), and the plugin
  path is expected to be faster than Claude Code's (§2 B, Performance). SYNC §6 point 1 identifies "one handler, one
  decision, enforced identically" across tools as the gap nobody fills; B is the daemon filling it for a second
  host. B is large and exposed to churn, so it starts with a spike and a pinned version.
- **00292's conclusion carries over, with one difference.** 00292 recommended "build toward A, gated behind D, but do
  not start now", because Codex's tool coverage was incomplete (00292 lines 461-466). opencode's blocking surface is
  complete for tools (`execute.before` sees every tool including MCP and Code Mode inner calls, MAP PreToolUse row),
  so the "wait for coverage" argument does not apply. The churn argument does, and pinning answers it.
- **D3 is rejected.** A general daemon-owned sync tool would re-implement rulesync's moving target (SYNC §4). The
  daemon's differentiator is enforcement (SYNC §1 finding 6, §6 point 3), not generation.
- **C is deferred, not rejected.** The stop re-drive, the one autonomy feature most worth having, moves into B.
  C's remaining value (crons, `/goal`, the supervisor) only matters for unattended opencode operation, and it carries
  the one trust decision in this paper.

**Sequence (each step a candidate plan for the epic; sizes relative):**

0. **Spike (small, throwaway).** A live opencode 2.1.x server with a minimal V2 plugin that talks to a stub socket.
   Resolve the UNVERIFIED items B depends on: Bun Unix-socket I/O from a plugin; plugin-to-daemon latency (p50, p95)
   against PERF's 4.3 ms relay figure; what a rejected non-tool hook does to a turn; whether every mutating tool calls
   `permission.assert` (§4 item 3); whether plugin `synthetic` messages pass through `session.prompt` (loop risk);
   re-drive timing; whether a project-local plugin is instantiated per location; child-session `session.created`
   filtering on `parentID`. Output: a findings document and a go/no-go for step 2.
1. **Tool-neutral layer (Option A), small-medium.** In order: CLI entry points for the three gates without one; git
   hook provisioning that respects existing `core.hooksPath` and pre-commit frameworks; the "hooks not installed"
   startup report; `AGENTS.md`-canonical provisioning with `CLAUDE.md` shims, opt-in per project, plus a migrate
   command; the AMD §5 checks (a)-(e) as E1/E2/E3/E4 handlers; the compact neutral form of the generated section with
   a size budget. Dogfood in this repository, including its 12 nested `CLAUDE.md` files.
2. **Host abstraction in the daemon (B, Python half), large.** Envelope `host` field; host-neutral verdict
   response; per-host capability table and the three-state report (§4 item 1); tool name and field maps; the `patch`
   parser; identity re-keyed from `transcript_path` to a host-supplied agent key; session grouping by `sessionID` for
   plugin hosts; the socket discovery file. All testable without opencode, and it leaves Claude Code behaviour
   unchanged.
3. **opencode bridge plugin (B, TypeScript half), medium.** The plugin, the §4 fail-closed paths and permission
   baseline, version pinning, `contracts/opencode-plugin/` with a staleness check, an acceptance harness against a
   pinned opencode in CI, guidance via `session.context` with caching. Safety layer only.
4. **Config generation (D1), small-medium, can run alongside step 3.** Render `.opencode/agents`, `.opencode/commands`
   and the daemon's `opencode.json` keys; per-host config-dir twin; ownership ledger namespace. Add D2 (detect
   rulesync, run `generate --check`, report and gate) as a small follow-on.
5. **Autonomy at re-drive fidelity (B), medium.** Stop and SubagentStop re-drive in the plugin with its own re-entry
   counter; sub-agent report rewrite; the stop-explanation contract; compaction re-brief. Each handler's degraded
   state is declared in the capability table.
6. **External driver (C), only on the owner's go-ahead.** Scheduler, failsafe ticks, `/goal` equivalent.

---

## 6. Decisions taken here (an engineer can rule; listed so they are not re-litigated)

01. Translation of payloads, tool names and verdicts lives in the daemon (Python), not the plugin.
02. The plugin targets the V2 Promise API only; V1 is not supported (the V2 loader rejects it, SURFACE §0).
03. The stop re-drive lives in the plugin, not an external driver.
04. The plugin finds the daemon through a discovery file the daemon writes, not by recomputing `init.sh` paths.
05. Daemon unreachable means fail closed on `execute.before` and a visible banner elsewhere; plugin absent means every
    mutating tool asks, via the `ask` permission baseline.
06. An unsupported opencode version fails closed unless an explicit opt-in key is set.
07. The generated guidance section moves to `AGENTS.md` in a compact neutral form with depth behind `explain-rule`,
    under a size budget that respects Codex's 32 KiB cap.
08. The daemon does not become a general config generator (D3 rejected); it renders only what it deploys (D1) and
    checks rulesync when present (D2).
09. R8, B16, B17, B18, B19 and B27 are declared unsupported for opencode, not emulated.
10. `.claude/` stays the daemon's own install root on every host (COUP B14); only host-discovered paths move.

---

## 7. Open questions for the owner

Only questions an engineer cannot settle: priorities, trust and scope.

1. **Migration policy for `AGENTS.md`-canonical.** Should the daemon *migrate* existing client `CLAUDE.md` content
   into `AGENTS.md` (opt-in per project, with a migrate command), or only provision the layout for new projects and
   enforce it where a project has chosen it? This changes every client's instruction files, so it is the owner's
   call.
2. **rulesync.** Is rulesync acceptable as the *recommended* generator for project-wide config sync (a Node
   dependency on clients that opt in, D2), or should project-wide sync stay out of the daemon's scope apart from the
   daemon's own assets (D1 only)?
3. **Trust for the external driver (C).** Is the daemon allowed to read opencode's `service.json` password, which
   lets it drive every session on that user's opencode server, not only this project's? If not, C reduces to OS-timer
   headless `opencode run` ticks.
4. **Autonomy ambition under opencode.** Is the target "opencode sessions are guarded" (steps 0-5), or "opencode
   sessions run unattended like ccy-supervised Claude Code" (adds step 6 and accepts re-drive rather than veto
   semantics as permanent)?

---

## Gaps

- No live opencode run was made for this paper; every performance figure for the plugin path is an expectation, to be
  measured in step 0.
- Handler fractions inherit MAP's per-event counts and its "about 10 of 87" PreToolUse estimate, which was by
  inspection rather than a per-handler trace. The commit-time "8-9 handlers" figure for Option A is from DUAL §7's
  gate list, not a registry query.
- The `session_thread_group` re-keying conclusion is an inference from `peer_pid_of` and the shared-server model;
  the module was not read in full.
- `packages/plugin/src/effect/PLAN.md` (the V2 plugin design plan, flagged unread in SURFACE Gaps) may announce hook
  renames that bear on B's churn risk. It should be read in step 0.
