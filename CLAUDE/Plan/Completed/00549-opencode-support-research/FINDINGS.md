# FINDINGS: opencode support (Plan 00549 Task 3.1)

The owner-facing synthesis of this plan folder. It answers, compares, records what is decided, and proposes the epic.
Detail lives in the supporting documents; each finding points at the section that holds its evidence.

**Baseline.** opencode clone at `c93aaae37157d785f76a8e9a9243a6560e286468`, product version **OpenCode V2 2.1.2**
(the `github-v1.2.27` tag is not the product version; SURFACE §0). Claude Code **2.1.308** for the `AGENTS.md` probes
(AMD §1). Fact-checked: 33 verified, 1 refuted and fixed, 1 unverifiable without a live run
(`subagent-reports/261022-fact-check-research-sonnet.md`).

**Short names.** SURFACE `RESEARCH-opencode-extension-surface.md`; ARCH `RESEARCH-opencode-architecture.md`; DUAL
`RESEARCH-dual-tool-repos.md`; COUP `RESEARCH-daemon-couplings.md`; AMD `RESEARCH-claude-code-agents-md.md`; SYNC
`RESEARCH-multi-agent-config-sync.md`; MAP `MAPPING-events.md`; PLANWF `ANALYSIS-plan-workflow.md`; OPTIONS
`OPTIONS-support.md`; RULINGS `subagent-reports/261022-open-questions-advice-fable.md`; VS
`RESEARCH-opencode-vs-codex.md` (Codex CLI `rust-v0.163.0` / clone `b337fe06`); MH `ANALYSIS-multi-harness-mode.md`.

---

## 1. Executive answer

1. **Can we support opencode?** Yes, for the safety-guard half of the daemon; the autonomy half degrades. 108 of 187
   handlers have a full-fidelity mechanism and 162 (87%) have at least a partial one (MAP Summary).
2. **Does it have hooks?** Not command hooks. It has **in-process TypeScript plugins** (V2 `@opencode/plugin`) with
   typed, mutable hook events. Its website still documents the V1 API, which the V2 loader rejects (SURFACE §0, §2).
3. **What can the daemon hook into?** `tool.execute.before` (the only hook that can block, and it can rewrite),
   `permission.evaluate` (deny/allow), `session.context` (inject on every model step), `session.prompt`,
   `session.compaction`, `shell.create.before`, and an observe-only event bus. There is **no stop veto**, only a
   re-drive after idle, and no scheduler (MAP "How opencode is hooked"; PLANWF §1).
4. **Can we force the plan workflow?** Partly now, without a plugin: git hooks, agent permissions, provisioned
   commands. Edit-time guards need the plugin. Stop gates become re-drives. Crons need a plugin scheduler or an
   external driver (PLANWF §5).
5. **One repo, both tools?** Yes, with `AGENTS.md` as the only instruction file (owner's direction), behind an
   explicit opt-in `multi_harness` mode; projects that do not opt in see zero change (MH §2.3, §3.2). **Today an
   opencode session in a daemon-managed repo gets no instructions and no guards**: opencode V2 reads `AGENTS.md`
   only, never `CLAUDE.md`, despite its docs (DUAL §1 findings 1, 5).
6. **Does Claude Code read `AGENTS.md` without `CLAUDE.md`?** Yes, from 2.1.277; the owner's understanding is right,
   and an AGENTS-only repo works. **What works:** root load at launch, nested load on Read and `@`-mention (2.1.290+),
   `@` imports, subagents. **A user `~/.claude/CLAUDE.md` does NOT switch it off**, even for repos under `$HOME`
   (new probe H1). **What is lost:** nested load on Write/Edit/Bash (SOURCE-DERIVED, not observed), the
   `InstructionsLoaded` hook (no handler uses it today), `--add-dir`. **What silently switches it off:** any
   `CLAUDE.md`/`.claude/CLAUDE.md`/`CLAUDE.local.md` in the repo or above it (incl. `~/CLAUDE.md`, H2), a user or
   managed `claude-md` mode, `/init` or `/memory` creating a `CLAUDE.md` (docs only, not probed), versions before
   2.1.277 (2.1.281 on Bedrock/Vertex/gateways). Fragile, not broken: every trigger is a file, setting or version the
   daemon can read at SessionStart and report loudly, and the nested gap is closable by a daemon handler (unprobed)
   (MH §1.3, §2.2).
7. **Codex vs opencode; does OpenAI lock you in?** No. "Sign in with ChatGPT" for third-party tools (launched about
   2026-09-29) is built into opencode core, and Plus/Pro usage counts against the same Codex allowance (Plus/Pro-only
   eligibility is from search extracts, UNVERIFIED; treat Team as unsupported). Anthropic is the opposite: Claude
   subscription login in third-party tools is prohibited by its terms and removed from opencode; opencode reaches
   Claude by API key only. Codex itself is Apache-2.0 but OpenAI-shaped: non-OpenAI providers only via the Responses
   API (VS §1.4). **For the daemon, Codex is the easier second host**: stable, default-on command hooks that near-port
   Claude Code's schema, `apply_patch` matched as `Write|Edit`, and a real `Stop` veto. Source-read only, no live run
   (VS §3.1).
8. **SOTA for config in sync?** `AGENTS.md` (Linux Foundation AAIF) for instructions, Agent Skills for skills, and
   generators (rulesync, ruler) for the rest. **Nobody enforces the canonical file or hook semantics** at edit time.
   That gap is this daemon's opening (SYNC §1, §6).

---

## 2. Same vs different (opencode V2 2.1.2 against Claude Code)

| Dimension         | opencode                                                        | Claude Code                                     | Verdict                                |
| ----------------- | --------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------- |
| Licence           | MIT, open source                                                | Proprietary                                     | Different                              |
| Process model     | One shared background HTTP server per user; thin clients        | One process per session                         | **Fundamentally different**            |
| Models            | 35+ providers                                                   | Anthropic models only                           | Different                              |
| Hook model        | In-process TS plugins, typed mutable events                     | Out-of-process commands, JSON on stdin/stdout   | **Fundamentally different**            |
| Blocking a tool   | `tool.execute.before` throws; `permission.evaluate` denies      | `PreToolUse` deny                               | Same capability                        |
| Stop gate         | None; re-drive after idle via `synthetic`/`prompt`              | `Stop` `decision:"block"`                       | **Weaker in opencode**                 |
| Context injection | `session.context` on every step; survives compaction            | `SessionStart`/`UserPromptSubmit` context       | Stronger in opencode                   |
| Hook timeout      | None; a hung hook stalls the call                               | Per-hook timeout                                | Different; the plugin must impose one  |
| Permissions       | Ordered rule lists; **default allow all**; config deny is final | allow/ask/deny; default asks for edits and Bash | Same concept, opposite default         |
| Sub-agents        | `subagent` tool; persistent child sessions                      | `Task`/`Agent`; sidechains                      | Same capability, different shape       |
| Plan mode         | A `plan` agent with edit permissions                            | A permission mode plus `ExitPlanMode`           | Same goal, different mechanism         |
| Instructions      | `AGENTS.md` only (plus `instructions` globs)                    | `CLAUDE.md` tree; `AGENTS.md` as fallback       | Different; meet only at `AGENTS.md`    |
| Shared config     | Reads `.claude/skills` and `.agents/skills` only                | `.claude/*`                                     | Skills are the one shared format       |
| Tool names        | `shell`, `edit`, `write`, `patch`, `subagent`, `question`       | `Bash`, `Edit`, `Write`, `Task`, ...            | Different; needs a map; `patch` is new |
| Transcripts       | SQLite, event-sourced                                           | JSONL per session                               | Different; parsers do not port         |
| Status line, cron | None found in core, schema or cli; plugin/TUI not checked       | Both                                            | Not found in opencode (UNVERIFIED)     |
| MCP, headless SDK | Built in; open HTTP/OpenAPI server                              | Built in; `claude -p`, Agent SDK                | Same                                   |
| API stability     | V2.1 broke plugin contracts in a minor release                  | Stable hook protocol, copied by other tools     | **opencode churns**                    |

Full 26-row comparison: ARCH §8. Three-way table with Codex CLI: VS §2.2. Where Codex sharpens the picture (source at
`b337fe06`, no live run): it sits on Claude Code's side of every **Fundamentally different** row above (one process
per session, out-of-process command hooks with Claude-shaped JSON, real `Stop`/`SubagentStop` veto, per-hook timeout,
JSONL rollouts), and differs in small, precise ways: no `ask` from hooks, `allow` valid only with `updatedInput`,
nullable `transcript_path`, edits only via `apply_patch` (the same envelope as opencode's `patch`, so one parser serves
both), reads via the shell, hooks run only after the user trusts the exact definition, an OS sandbox as a stronger
floor, and a 32 KiB default `AGENTS.md` cap (VS §2.1, §3.1).

---

## 3. Key findings per area

- **Extension surface.** One blocking hook, rewrite through mutation, no external-process hooks, registration order
  matters, a failed plugin load is only logged (SURFACE §2-§5, §7).
- **Event mapping.** Per-event verdicts for all 34 catalogued events; tool and field map; `patch` needs a parser for
  every write guard; four places opencode is stronger (MAP Tables 1-3, Summary).
- **Daemon couplings.** 41 couplings (R1-R10, B1-B31). Option B covers 23; six are declared unsupported (status line,
  Claude plugins, Anthropic pricing, usage pause, teammates, Claude-only tools) (COUP Counts, top 10; OPTIONS §3).
- **Architecture.** A shared long-lived server means the plugin must route by project and sessions must be keyed by
  `sessionID`, not peer pid or transcript path (ARCH §1.2, §8.1; OPTIONS §2 B).
- **Plan workflow.** Provisionable now vs needs plugin vs needs driver vs impossible, ranked (PLANWF §5). A synthetic
  message does restart the loop, so a stop re-drive is possible; re-drive timing is untested and it can restart the
  loop (PLANWF §1 fact 1, Gaps).
- **Dual-tool repos.** What each tool reads, collisions (agents' frontmatter is incompatible; a loose
  `.claude/skills/CLAUDE.md` becomes a phantom skill in opencode; both derived from code reading, not observed by
  running opencode), and the item-by-item list for this repo (DUAL §2-§5, §8).
- **Claude Code and `AGENTS.md`.** Equivalence table from about 40 local probe runs (no model calls) plus source and
  docs rows; AMD recommended the shim in every directory (symlinks also work but fail on Windows), and the Write, Edit
  and Bash nested loads are source-derived, not observed (AMD §4, §5.1, §6). Superseded by the owner's direction:
  AGENTS-only is the mode's default, the shim a declared alternative (MH §2.3; §4 Q1.3).
- **Config-sync SOTA.** rulesync and ruler generate; hook registration is translated, hook semantics are not; nobody
  gates an agent editing a generated file (SYNC §1, §4, §6).
- **Performance.** A resident plugin removes the per-event process spawn; INFERENCE: expected faster than Claude Code's 4.3 ms
  relay path, to be measured (OPTIONS §2 B "Performance").
- **Fail-loud.** Every handler is enforced, degraded or unsupported per host, visibly. A missing plugin is designed to
  be loud via an `ask` permission baseline that only the plugin can relax; unproven until plan 0 (OPTIONS §4).

---

## 4. Decisions taken, and the one open question

Decided (CLEAR rulings, RULINGS; engineering decisions, OPTIONS §6). Rows marked owner-directed were amended after the
owner's follow-up on the opt-in `multi_harness` mode (MH §4); Q2, Q3, Q4 and M3 are unchanged:

| #      | Decision                                                                                                                                                                                                                                                                                                                                                            |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1     | **Amended (owner-directed, MH §4):** enabling `multi_harness` mode is the only route; `multi-harness enable` is that command (dry run by default, `--apply` to act, a `disable` inverse); this repo first                                                                                                                                                           |
| Q1.2   | **Retracted (owner-directed):** new installs are unchanged (`CLAUDE.md`); the installer offers the mode, never defaults to it; `layout: claude-md-only` dropped (mode off is that)                                                                                                                                                                                  |
| Q1.3   | **Rewritten (owner-directed):** `instruction_layout: agents-only` (default in the mode: no CLAUDE files anywhere, Claude-only content in `.claude/rules/`, nested Write/Edit gap closed by a daemon handler) or `shim` (declared alternative). Never mixed. H1: user `~/.claude/CLAUDE.md` is harmless; H2/g2/i: ancestor `CLAUDE.md` and `CLAUDE.local.md` are not |
| Q1.4   | **Rewritten:** Claude-only content stays in the shim (S) or moves to `.claude/rules/hooks-daemon.md` / project rule files (A); one token-list classifier                                                                                                                                                                                                            |
| Q1.5   | **Rewritten (owner-directed):** checks run **only** when the mode is on; off = zero output. Per-layout check table in MH §3.3 (incl. ancestor, `CLAUDE.local.md`, `instructionFiles` mode and version checks)                                                                                                                                                       |
| Q1.6-7 | Unchanged, plus: Claude-only remainder of the guidance goes to `.claude/rules/hooks-daemon.md` (A); the command also refuses on an unplaceable classifier result and a dirty tree                                                                                                                                                                                   |
| Q2     | rulesync is an optional detected integration (`generate --check` only), never a dependency or a recommendation; the daemon's own renderer (D1) comes first                                                                                                                                                                                                          |
| Q3     | The daemon does not read opencode's `service.json` password in this epic; the question returns to the owner only with the external driver                                                                                                                                                                                                                           |
| Q4     | Target is **guarded** opencode sessions, with Stop at declared "degraded: re-drive" fidelity; unattended is a go/no-go after plan 6, on evidence                                                                                                                                                                                                                    |
| M1     | Git hooks: local `core.hooksPath` only, chain existing husky/pre-commit. **Amended (owner-directed):** part of the mode, offered by `multi-harness enable`, never installed with the mode off; the "commit gates are Claude-Code-only" line shows only in the mode                                                                                                  |
| M2     | Fail closed on an unsupported opencode version; pin a range; a Routine tracks opencode releases. Proposed extension to Codex, pinned to stable `rust-v*` tags (VS §3.3 item 5)                                                                                                                                                                                      |
| M3     | Bun/TypeScript toolchain: CI only, confined to the plugin and its contracts, never on clients                                                                                                                                                                                                                                                                       |
| M4     | **Amended (owner-directed):** `hosts` lives inside the `multi_harness:` block (`claude-code` implicit and irremovable; `codex` may be listed before an adapter exists, reported as "instructions but no guards"); a top-level `hosts:` is a config error; the "no opencode protection" line fires only in the mode                                                  |
| D      | Translation lives in Python; plugin is a dumb pipe; V2 plugin API only; discovery file for the socket; general config generator (D3) rejected                                                                                                                                                                                                                       |

**Open, for the owner (non-blocking): M5, naming and positioning.** Is the product (a) "a Claude Code hooks daemon that
also covers opencode", or (b) "a multi-host enforcement daemon", with a rename and repositioning as a later epic of its
own? (b) would also bring SYNC §7 E6 into scope (publishing the canonical event/decision model). **Adviser default if
no answer: (a), E6 out of scope.** Nothing in the epic waits on this. New data points: Codex as a third host, and
the owner's own term "multi harness", both lean towards (b)'s vocabulary without requiring the rename (VS §3.3 item 7;
MH §4).

---

## 5. Epic proposal: candidate plans, in order

Sequence from OPTIONS §5, adjusted by the rulings and the owner's follow-ups (MH; VS §3.3). Plans 0, 1 and 2 can start
in parallel; the spike gates 3 onwards. Everything below except plan 1's CLI entry points deploys only into a project
with `multi_harness.enabled: true`; a non-opted project gets zero change (MH §3.2).

**Plan 0: spike, two legs (small, throwaway).** *opencode leg:* a live opencode 2.1.x server with a minimal V2 plugin
talking to a stub socket; settles the opencode unknowns in §6 and measures plugin-to-daemon latency against the 4.3 ms
relay. *Codex leg* (cheap: no Bun, no TypeScript): a pinned Codex stable release with a command hook to the daemon
socket; confirms `apply_patch` `Write|Edit` matching, `Stop` block continuation, trust-review friction and
`additionalContext` spilling behave as the source reads (VS §3.3 item 1). Deliverable: findings note and a go/no-go per
host for plan 3 onward. *Depends on:* nothing. *Evidence:* every B-risk listed as UNVERIFIED in OPTIONS §2 B "Open
unknowns", fact-check claim 35, VS Gaps.

**Plan 1: tool-neutral commit gates (Option A, git half; small-medium).** CLI entry points for the conflict-marker,
staged-lint and sensitive-content commit scans (CLI entry points were not checked for the other gates; plan-qa and
issue-validity are the confirmed CLIs); a `core.hooksPath` installer that is
offered only by `multi-harness enable` and chains existing frameworks (M1); a staged-tree-hash stamp so Claude Code
does not run gates twice; a "git hooks not installed" startup report (in the mode only); `--no-verify` deny in
provisioned `opencode.json` (and the Codex equivalent once plan 4b exists); a hook
that exits non-zero naming the repair when the venv is missing. *Depends on:* nothing. *Evidence:* no git hooks
installed today and every commit gate is a Claude-only `PreToolUse` (DUAL §1 finding 5, §7; PLANWF §4).

**Plan 2: the opt-in `multi_harness` mode (Option A, instruction half; medium; owner-directed).** In this order (MH §3):

1. **Config block and zero-change contract.** `multi_harness: {enabled, hosts, instruction_layout, agents_md_max_bytes}`
   with M4's `hosts` inside it; a top-level `hosts:` fails config load. New handlers registered disabled and gated on
   the flag. An integration test installs with the mode off and asserts a byte-identical tree and SessionStart output
   against the previous release (MH §3.1-§3.2).
2. **Compact neutral guidance.** Shrink the generated `<hooksdaemon>` section (118,604-byte `CLAUDE.md` today) to a
   compact, host-neutral form under the size budget (below Codex's 32 KiB cap), depth behind `explain-rule` and a
   skill. The injector refuses, never truncates, if it would not fit. Done before any migration, or the dogfood proves
   nothing (RULINGS Q1.6; OPTIONS §2 A "Size").
3. **Layout per MH §2.3.** `agents-only` by default: shared guidance into `AGENTS.md`, the Claude-only remainder into a
   generated `.claude/rules/hooks-daemon.md`, installer's `CLAUDE/Plan/CLAUDE.md` becomes `AGENTS.md`. `shim` as the
   declared alternative for teams on old/Bedrock versions or with a `~/CLAUDE.md`. Never mixed (Q1.3).
4. **Layout checks** (MH §3.3 table; SessionStart error and commit gate): tracked CLAUDE files (A); unimported or
   unshimmed siblings and shared content in a shim (S); untracked `CLAUDE.local.md`/`CLAUDE.md`; CLAUDE files above the
   git root; a `claude-md`/`managed-only` `instructionFiles` mode; version < 2.1.290 and the disabling env vars; size
   budget; generated-file drift. Errors that turn instructions off are loud in the banner and `status`, not advisories.
   No silent compensation unless `on_fallback_disabled: inject` is set (MH §3.6).
5. **Editing guards:** (A) deny creating any CLAUDE file, naming the right target; (S) deny shared content in a shim
   and edits to generated files; (both) the Claude-only content guard on `AGENTS.md` (SYNC §7 E1-E2), one token-list
   classifier shared with the command; `validate_instruction_content` extended to `AGENTS.md`. Whether `/init` and
   `/memory` write through the tools (and so hit the guard) is UNVERIFIED; the SessionStart and commit checks catch
   them otherwise.
6. **Nested gap closure (A):** a PostToolUse handler on Write/Edit (and single-file Bash reads) attaching unseen
   `AGENTS.md` files as `additionalContext`, with a per-session given set cleared on compaction; plus an
   `InstructionsLoaded`-based load confirmation via the rules file. Designs only, unprobed (MH §3.4, §5).
7. **`multi-harness enable` / `disable`** (replaces `migrate-agents-md`): dry run by default, `--apply` to act; moves
   shared content to `AGENTS.md`, Claude-only content to `.claude/rules/` (A) or the shim (S); offers M1 git hooks and
   per-host renders; refuses on `CLAUDE.local.md` (A), an ancestor `CLAUDE.md` (A), a budget breach, an unplaceable
   classifier result or a dirty tree; never drops content; never run by an upgrade (Q1, Q1.7; MH §3.5).
8. **Dogfood** in this repository, including its 12 nested `CLAUDE.md` files (the two under `.claude/` become
   `.claude/rules/` files or `README.md`, not `AGENTS.md`; MH §3.4 item 5), before offering it to clients.

*Depends on:* nothing (plan 1 is independent). *Evidence:* opencode reads only `AGENTS.md` (DUAL §1); AGENTS-only works
in Claude Code and every failure trigger is detectable (MH §1.3, §2.2; probes H1, H2); nobody enforces the canonical
file (SYNC §6).

**Plan 3: host abstraction in the daemon (Option B, Python half; large).** Designed for **N hosts**, not opencode alone:
request-envelope `host` field; host-neutral verdict beside the Claude serializer; per-host capability table with the
enforced/degraded/unsupported report in `status` and guidance, including Codex's `ask→?` and `allow`-requires-rewrite
cells; `hosts` values `claude-code`, `opencode`, `codex` (M4); tool-name and field maps; one `apply_patch`-envelope
parser for opencode `patch` and Codex `apply_patch`; identity re-keyed from `transcript_path` (nullable in Codex) and
peer pid to a host-supplied session key; socket discovery file. Codex is the first non-Claude consumer in its tests,
being reachable with no new transport. Claude Code behaviour unchanged. *Depends on:* plan 0 go. *Evidence:* COUP R2-R4,
R7, B2, B21; MAP Table 3; OPTIONS §4 item 1; VS §3.2.

**Plan 4b: Codex adapter (Option B, transport half for Codex; small-medium). Proposed to run before plan 4.** Generate
`.codex/hooks.json` pointing at the existing forwarder; a Codex serializer (emit nothing rather than a bare `allow`;
declare whether a Claude-side `ask` degrades to `deny` or to the approval policy); a fail-loud "hook trust pending"
report; `workspace-write` plus an approval policy as the baseline; declared degradations (no `ask`, hosted tools
unhooked, Read-keyed handlers become shell-command handlers, no status line per 00292, not re-checked). Before plan 4
because it delivers a second host sooner at lower risk and validates plan 3's neutrality before any TypeScript work.
*Depends on:* plan 3 only. *Evidence:* VS §2.1, §3.1, §3.3 item 3.

**Plan 4: opencode bridge plugin (Option B, TypeScript half; medium).** V2 Promise plugin registering the hooks listed
in OPTIONS §2 B; fail closed when the daemon is unreachable; the `ask` permission baseline for a missing plugin;
version-range pin with opt-in override (M2); its own timeout; registers last on `execute.before` and names competing
plugins; per-session guidance cache for `session.context`; `contracts/opencode-plugin/` with staleness check; an
acceptance harness against pinned opencode in CI, Bun confined to CI (M3); plus the M2 Routine re-running it per
opencode release. Safety layer only (~94 handlers). *Depends on:* plans 0 and 3. *Evidence:* SURFACE §2-§5; MAP
Summary; OPTIONS §2 B, §4.

**Plan 5: config rendering (Option D1, then D2; small-medium, alongside plan 4).** Render `.opencode/agents` from
`.claude/agents`, `.opencode/commands` (`plan-new`, `journal`, `issue-sdlc`, `plan-qa`), the daemon's own
`opencode.json` keys (plugin entry, translated deny rules); a per-host config-dir twin; md5 ownership ledger
namespace; never regenerate over a human edit; a Codex target (`.codex/hooks.json`, `config.toml` sandbox, approval and
`project_doc_max_bytes` keys; VS §3.2); renders only for hosts listed in `hosts`. Follow-on D2: detect `.rulesync/`, run `rulesync generate --check` at
SessionStart and commit; report loudly if the binary is missing (Q2). *Depends on:* plan 2 (guidance channel), plan 4
for the plugin entry. *Evidence:* DUAL §3.2, §6; PLANWF §3; SYNC §4, §7.

**Plan 6: autonomy at re-drive fidelity (Option B; medium).** Stop and SubagentStop re-drive in the plugin with its
own re-entry counter; sub-agent result rewrite; stop-explanation contract; compaction re-brief; each degraded state
declared. Ends with the findings note that decides unattended operation (Q4.3). For Codex, autonomy is mostly a port
(real `Stop`/`SubagentStop` veto with `stop_hook_active`); the re-drive design stays opencode-only (VS §3.3 item 6).
*Depends on:* plan 4 (opencode), plan 4b (Codex). *Evidence:*
PLANWF §1 facts 1-2, §2.4; MAP Stop and SubagentStop rows.

**Plan 7 (not proposed now): external driver (Option C).** Daemon-owned crons, failsafe ticks, `/goal` equivalent.
Only on the owner's go after plan 6, together with the `service.json` trust decision (Q3, Q4). *Evidence:* OPTIONS
§2 C; PLANWF §5 C.

---

## 6. Known unknowns (for plan 0, the spike)

All UNVERIFIED in the inputs; no live opencode or Codex run was made in this plan.

01. Bun `node:net` Unix-socket I/O from inside a V2 plugin, and the plugin-to-daemon latency (p50, p95)
    (SURFACE §3; OPTIONS §2 B).
02. What a rejected or failing non-`execute.before` hook does to a turn (SURFACE §5; ARCH Gaps).
03. Whether every mutating tool calls `permission.assert`, which the `ask` fail-closed baseline relies on (OPTIONS §4
    item 3; MAP Table 2).
04. Whether plugin-sent `synthetic` messages re-enter `session.prompt` (a re-drive loop risk), and re-drive timing
    (MAP Gaps; PLANWF Gaps).
05. Whether a project-local plugin is instantiated per location on a shared server; child-session filtering on
    `parentID` (OPTIONS §5 step 0).
06. Subdirectory sessions and edit-permission resources; the `{shell, "*>*", deny}` rule; `default_agent` with a mode
    file (PLANWF Gaps).
07. Whether the V2 plugin design plan (`packages/plugin/src/effect/PLAN.md`) announces hook renames (SURFACE Gaps;
    OPTIONS Gaps).
08. Whether the live opencode website has been updated past the V1 plugin docs (SURFACE §0).
09. Codex leg: the hook behaviours in VS §3.1 (all source-read); plan-mode enforcement, Windows hooks, rollout schema
    stability, the shared `app-server-daemon` mode, the undocumented `Pre`/`PostModelRequest` events, and whether a
    Responses-API gateway can serve Claude models (VS Gaps).
10. Claude Code side (not for the spike, but open; needs a model, so not probed): nested `AGENTS.md` on Write/Edit/Bash
    in an AGENTS-only repo (expected absent, SOURCE-DERIVED); root `AGENTS.md` after `/compact` (expected present,
    SOURCE-DERIVED); what `/init` writes, and whether `/init` and `/memory` create `CLAUDE.md` through the tools or
    natively; HTML-comment stripping and `claudeMdExcludes` on `AGENTS.md` (AMD §6; MH §1.3, §5). **Auth-free method:**
    point `ANTHROPIC_BASE_URL` at a local stub server that logs request bodies and returns canned replies; the body
    shows which instruction text reached the model (UNVERIFIED that `-p` accepts it with `ANTHROPIC_API_KEY=dummy`;
    MH §1.4 item 2). Also open: the MH §3.4 nested-attach handler and `InstructionsLoaded` verification (MH §1.4 item
    5). Settled by probe H1: a user `~/.claude/CLAUDE.md` does not disable `AGENTS.md`.
