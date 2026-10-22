# FINDINGS: opencode support (Plan 00549 Task 3.1)

The harness refused a Write to the canonical `FINDINGS.md` path, so this is the fallback location. Move it to
`../FINDINGS.md` when landing it; the relative pointers below assume that location.

The owner-facing synthesis of this plan folder. It answers, compares, records what is decided, and proposes the epic.
Detail lives in the supporting documents; each finding points at the section that holds its evidence.

**Baseline.** opencode clone at `c93aaae37157d785f76a8e9a9243a6560e286468`, product version **OpenCode V2 2.1.2**
(the `github-v1.2.27` tag is not the product version; SURFACE §0). Claude Code **2.1.308** for the `AGENTS.md` probes
(AMD §1). Fact-checked: 33 of 35 claims verified, one minor count corrected, none load-bearing refuted
(`subagent-reports/261022-fact-check-research-sonnet.md`).

**Short names.** SURFACE `RESEARCH-opencode-extension-surface.md`; ARCH `RESEARCH-opencode-architecture.md`; DUAL
`RESEARCH-dual-tool-repos.md`; COUP `RESEARCH-daemon-couplings.md`; AMD `RESEARCH-claude-code-agents-md.md`; SYNC
`RESEARCH-multi-agent-config-sync.md`; MAP `MAPPING-events.md`; PLANWF `ANALYSIS-plan-workflow.md`; OPTIONS
`OPTIONS-support.md`; RULINGS `subagent-reports/261022-open-questions-advice-fable.md`.

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
5. **One repo, both tools?** Yes, with `AGENTS.md` canonical and a `CLAUDE.md` shim (`@AGENTS.md`). **Today an
   opencode session in a daemon-managed repo gets no instructions and no guards**: opencode V2 reads `AGENTS.md`
   only, never `CLAUDE.md`, despite its docs (DUAL §1 findings 1, 5).
6. **Does Claude Code read `AGENTS.md` without `CLAUDE.md`?** Yes, from 2.1.277. **Fully equivalent?** No: it is a
   fallback plugin. One `CLAUDE.md` anywhere at or above cwd switches off every `AGENTS.md`, nested ones load only on
   Read or `@`, `InstructionsLoaded` does not fire, and there is no user, local or managed `AGENTS.md` (AMD §4).
7. **SOTA for config in sync?** `AGENTS.md` (Linux Foundation AAIF) for instructions, Agent Skills for skills, and
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
| Status line, cron | Neither                                                         | Both                                            | Absent in opencode                     |
| MCP, headless SDK | Built in; open HTTP/OpenAPI server                              | Built in; `claude -p`, Agent SDK                | Same                                   |
| API stability     | V2.1 broke plugin contracts in a minor release                  | Stable hook protocol, copied by other tools     | **opencode churns**                    |

Full 26-row comparison: ARCH §8.

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
  message does restart the loop, so a stop re-drive works (PLANWF §1 fact 1).
- **Dual-tool repos.** What each tool reads, collisions (agents' frontmatter is incompatible; a loose
  `.claude/skills/CLAUDE.md` becomes a phantom skill in opencode), and the item-by-item list for this repo (DUAL §2-§5).
- **Claude Code and `AGENTS.md`.** Equivalence table from ~40 probes; the shim in every directory is the only layout
  that restores native behaviour, including nested loads and `InstructionsLoaded` (AMD §4, §5).
- **Config-sync SOTA.** rulesync and ruler generate; hook registration is translated, hook semantics are not; nobody
  gates an agent editing a generated file (SYNC §1, §4, §6).
- **Performance.** A resident plugin removes the per-event process spawn; expected faster than Claude Code's 4.3 ms
  relay path, to be measured (OPTIONS §2 B "Performance").
- **Fail-loud.** Every handler is enforced, degraded or unsupported per host, visibly. A missing plugin is made loud
  by an `ask` permission baseline that only the plugin can relax (OPTIONS §4).

---

## 4. Decisions taken, and the one open question

Decided (CLEAR rulings, RULINGS; engineering decisions, OPTIONS §6):

| #   | Decision                                                                                                                                                        |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1  | Migrate `CLAUDE.md` into `AGENTS.md` by an explicit, opt-in, dry-run-first command per project; new installs default to `AGENTS.md` plus shims; this repo first |
| Q2  | rulesync is an optional detected integration (`generate --check` only), never a dependency or a recommendation; the daemon's own renderer (D1) comes first      |
| Q3  | The daemon does not read opencode's `service.json` password in this epic; the question returns to the owner only with the external driver                       |
| Q4  | Target is **guarded** opencode sessions, with Stop at declared "degraded: re-drive" fidelity; unattended is a go/no-go after plan 6, on evidence                |
| M1  | Git hooks: opt-in for existing clients, local `core.hooksPath` only, chain existing husky/pre-commit                                                            |
| M2  | Fail closed on an unsupported opencode version; pin a range; a Routine tracks opencode releases                                                                 |
| M3  | Bun/TypeScript toolchain: CI only, confined to the plugin and its contracts, never on clients                                                                   |
| M4  | A `hosts:` key in `hooks-daemon.yaml`; default `claude-code` only                                                                                               |
| D   | Translation lives in Python; plugin is a dumb pipe; V2 plugin API only; discovery file for the socket; general config generator (D3) rejected                   |

**Open, for the owner (non-blocking): M5, naming and positioning.** Is the product (a) "a Claude Code hooks daemon that
also covers opencode", or (b) "a multi-host enforcement daemon", with a rename and repositioning as a later epic of its
own? (b) would also bring SYNC §7 E6 into scope (publishing the canonical event/decision model). **Adviser default if
no answer: (a), E6 out of scope.** Nothing in the epic waits on this.

---

## 5. Epic proposal: candidate plans, in order

Sequence from OPTIONS §5, adjusted by the rulings. Plans 0, 1 and 2 can start in parallel; the spike gates 3 onwards.

**Plan 0: opencode spike (small, throwaway).** A live opencode 2.1.x server with a minimal V2 plugin talking to a
stub socket. Settles the known unknowns in §6 and measures plugin-to-daemon latency against the 4.3 ms relay.
Deliverable: findings note and a go/no-go for plan 3 onward. *Depends on:* nothing. *Evidence:* every B-risk listed as
UNVERIFIED in OPTIONS §2 B "Open unknowns" and fact-check claim 35.

**Plan 1: tool-neutral commit gates (Option A, git half; small-medium).** CLI entry points for the conflict-marker,
staged-lint and sensitive-content commit scans (the others are already CLIs); a `core.hooksPath` installer that is
opt-in for existing clients and chains existing frameworks (M1); a staged-tree-hash stamp so Claude Code does not run
gates twice; a "git hooks not installed" startup report; `--no-verify` deny in provisioned `opencode.json`; a hook
that exits non-zero naming the repair when the venv is missing. *Depends on:* nothing. *Evidence:* no git hooks
installed today and every commit gate is a Claude-only `PreToolUse` (DUAL §1 finding 5, §7; PLANWF §4).

**Plan 2: `AGENTS.md` canonical and its enforcement (Option A, instruction half; medium).** The plan the owner asked
for, in this order:

1. **Compact neutral guidance.** Shrink the generated `<hooksdaemon>` section (118,604-byte `CLAUDE.md` today) to a
   compact, host-neutral form under a size budget below Codex's 32 KiB cap, depth behind `explain-rule` and a skill.
   Done before any migration, or the dogfood proves nothing (RULINGS Q1.6; OPTIONS §2 A "Size").
2. **`AGENTS.md` target** for the guidance injector, with neutral tool vocabulary (COUP B3, B12).
3. **Shims.** New installs write `AGENTS.md` plus a `CLAUDE.md` whose first line is `@AGENTS.md`, in every directory
   with an `AGENTS.md`; a `layout: claude-md-only` key keeps the old shape (RULINGS Q1.2-Q1.3; AMD §5 design 1).
4. **Drift checks** (AMD §5 design 2 (a)-(e); SYNC §7 E3-E4): an `AGENTS.md` invisible to Claude Code, a `CLAUDE.md`
   that does not import its sibling, shared content in a shim, a committed `CLAUDE.local.md`, instruction files above
   the git root. SessionStart report plus commit gate; enforced only where the project has the layout, else a one-line
   advisory (RULINGS Q1.5).
5. **Editing guards** (SYNC §7 E1-E2): deny edits to generated or shim files naming the canonical source; a content
   guard keeping Claude-only constructs (Claude tool names, `CLAUDE_*`, Claude-specific `@` imports) out of
   `AGENTS.md`. One token-list classifier serves both this guard and the migrate command.
6. **Opt-in migrate command** (`bin/hooks-daemon migrate-agents-md` or similar): dry run by default; moves shared
   content to `AGENTS.md`, leaves Claude-only content in the shim; refuses loudly on a committed `CLAUDE.local.md`, a
   shadowing `CLAUDE.md` above the git root, or a size-budget breach; never drops content; never run by an upgrade
   (RULINGS Q1.1, Q1.7).
7. **Dogfood** in this repository, including its 12 nested `CLAUDE.md` files, before offering it to clients.

*Depends on:* nothing (plan 1 is independent). *Evidence:* opencode reads only `AGENTS.md` (DUAL §1); Claude Code's
fallback is not a peer and the shim is the only full layout (AMD §4-§5); nobody enforces the canonical file (SYNC §6).

**Plan 3: host abstraction in the daemon (Option B, Python half; large).** Request-envelope `host` field;
host-neutral verdict beside the Claude serializer; per-host capability table with the enforced/degraded/unsupported
report in `status` and guidance; `hosts:` key (M4); tool-name and field maps; the `patch` parser; identity re-keyed
from `transcript_path` and peer pid to a host-supplied session key; socket discovery file. Testable without opencode;
Claude Code behaviour unchanged. *Depends on:* plan 0 go. *Evidence:* COUP R2-R4, R7, B2, B21; MAP Table 3; OPTIONS §4
item 1.

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
namespace; never regenerate over a human edit. Follow-on D2: detect `.rulesync/`, run `rulesync generate --check` at
SessionStart and commit; report loudly if the binary is missing (Q2). *Depends on:* plan 2 (guidance channel), plan 4
for the plugin entry. *Evidence:* DUAL §3.2, §6; PLANWF §3; SYNC §4, §7.

**Plan 6: autonomy at re-drive fidelity (Option B; medium).** Stop and SubagentStop re-drive in the plugin with its
own re-entry counter; sub-agent result rewrite; stop-explanation contract; compaction re-brief; each degraded state
declared. Ends with the findings note that decides unattended operation (Q4.3). *Depends on:* plan 4. *Evidence:*
PLANWF §1 facts 1-2, §2.4; MAP Stop and SubagentStop rows.

**Plan 7 (not proposed now): external driver (Option C).** Daemon-owned crons, failsafe ticks, `/goal` equivalent.
Only on the owner's go after plan 6, together with the `service.json` trust decision (Q3, Q4). *Evidence:* OPTIONS
§2 C; PLANWF §5 C.

---

## 6. Known unknowns (for plan 0, the spike)

All UNVERIFIED in the inputs; no live opencode run was made in this plan.

1. Bun `node:net` Unix-socket I/O from inside a V2 plugin, and the plugin-to-daemon latency (p50, p95)
   (SURFACE §3; OPTIONS §2 B).
2. What a rejected or failing non-`execute.before` hook does to a turn (SURFACE §5; ARCH Gaps).
3. Whether every mutating tool calls `permission.assert`, which the `ask` fail-closed baseline relies on (OPTIONS §4
   item 3; MAP Gaps).
4. Whether plugin-sent `synthetic` messages re-enter `session.prompt` (a re-drive loop risk), and re-drive timing
   (MAP Gaps; PLANWF Gaps).
5. Whether a project-local plugin is instantiated per location on a shared server; child-session filtering on
   `parentID` (OPTIONS §5 step 0).
6. Subdirectory sessions and edit-permission resources; the `{shell, "*>*", deny}` rule; `default_agent` with a mode
   file (PLANWF Gaps).
7. Whether the V2 plugin design plan (`packages/plugin/src/effect/PLAN.md`) announces hook renames (SURFACE Gaps;
   OPTIONS Gaps).
8. Whether the live opencode website has been updated past the V1 plugin docs (SURFACE §0).
9. Claude Code side (not for the spike, but open): nested `AGENTS.md` behaviour on Write/Edit/Bash comes from source
   and docs, not a model-backed run; HTML-comment stripping and `claudeMdExcludes` on `AGENTS.md` unprobed (AMD §6).
