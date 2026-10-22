# Adviser rulings on the open questions (Plan 00549, OPTIONS-support.md §7)

Inputs read in full: `PLAN.md`, `OPTIONS-support.md`, `RESEARCH-claude-code-agents-md.md` (AMD),
`RESEARCH-multi-agent-config-sync.md` (SYNC). Spot-read: `RESEARCH-opencode-architecture.md` §1.2 (the `service.json`
contract) and `ANALYSIS-plan-workflow.md` §5 (the ranked list, including B.6 "an in-plugin scheduler").

Owner context applied: enforce `AGENTS.md`; config in sync across agents; opencode is the foundation of a new epic;
performance is a priority; no silent fallbacks; releases are human-gated; the daemon is installed into many client
repositories, so anything it writes into one matters.

Each ruling is marked **CLEAR** (an engineer-owner would accept it) or **UNCLEAR** (needs the human owner, with the
exact choice stated). Only UNCLEAR rulings go up.

---

## Q1. Migrate existing `CLAUDE.md` content into `AGENTS.md`? In this repo and/or clients? How?

**Ruling: yes, by an explicit per-project migrate command; never as an upgrade side effect. CLEAR.**

1. **Existing client projects: opt-in only.** No upgrade of the daemon may rewrite a client's instruction layout. The
   migrate command (`bin/hooks-daemon migrate-agents-md` or similar) is the only route, it is run by a human or by an
   agent the human told to run it, and it reports what it will change before it changes it (`--dry-run` default or
   a plan-then-apply shape). This is the owner's own constraint ("anything it writes into a client repo matters")
   applied; OPTIONS §2 A "Behaviour change for existing Claude Code clients" says the same.
2. **New installs: `AGENTS.md`-canonical by default.** A fresh install already writes a `CLAUDE.md`; writing
   `AGENTS.md` plus a `CLAUDE.md` shim instead is the same intrusion in a better shape, and it closes the silent
   opencode hole (DUAL §1 finding 5) from day one for every new client. A `layout: claude-md-only` key in
   `hooks-daemon.yaml` keeps the old shape for a client that wants it.
3. **The shape is the shim, root and nested.** `CLAUDE.md` = `@AGENTS.md` first line, then Claude-only extras, in
   **every** directory that has an `AGENTS.md` (AMD §5 design 1, probe k). Not symlinks (Windows `core.symlinks`,
   Edit-through-link refusal, SYNC §5). Not the user-level `claude-md-and-agents-md` setting (cannot be committed,
   misses Write/Edit/Bash triggers and `InstructionsLoaded`, AMD §5 design 4).
4. **What moves and what stays.** Shared project guidance moves to `AGENTS.md`. The daemon's generated section
   moves there in the compact neutral form (OPTIONS §6 decision 07). Claude-only content stays in the shim:
   anything naming Claude tools, `CLAUDE_*` vars, `@` imports of Claude-specific files, and the daemon's own
   `.claude/agents/CLAUDE.md` and `.claude/skills/CLAUDE.md` (AMD §5 design 5). The migrate command needs a
   classifier for "Claude-only"; SYNC §7 E2's token list is that classifier, so build it once and use it for both.
5. **Enforcement follows the choice.** The AMD §5 checks (a)-(e) are enforced only in a project that has the layout
   (new install or migrated). In a `claude-md-only` project they are at most a one-line SessionStart advisory. This is
   the "enforce it where a project has chosen it" half of the paper's question, and both halves are wanted, not one.
6. **This repository migrates first and dogfoods**, including its 12 nested `CLAUDE.md` files, before the command is
   offered to clients. The 118 KB generated section must be shrunk to the compact form before the migration, or the
   dogfood proves nothing about the Codex 32 KiB cap (OPTIONS §2 A "Size").
7. **Fail-loud specifics.** The migrate command refuses (non-zero, naming the file) on: a `CLAUDE.local.md` that would
   be committed, a `CLAUDE.md` above the git root that would shadow the result (AMD probes g2, i), and an `AGENTS.md`
   that would exceed the size budget. It never silently drops content.

Why CLEAR: every element is either the owner's stated constraint, the only layout the probes show works, or an
engineering shape with no plausible alternative an owner would prefer. The one thing that could have needed the owner,
"rewrite every client on upgrade", is ruled out by the owner's own words.

## Q2. Is rulesync acceptable as a recommended/optional config-sync tool?

**Ruling: acceptable as an optional, detected integration (D2); not a dependency, not installed by the daemon, not
"recommended" in install docs. D1 is built first. CLEAR.**

1. **D1 first.** The daemon renders only what it deploys (`.opencode/agents`, `.opencode/commands`, its own
   `opencode.json` keys) with the existing md5 ownership ledger (OPTIONS §2 D1). This is the owner's config-sync
   requirement for everything the daemon is responsible for, and it needs no third party.
2. **D2 is detect-and-check only.** If `.rulesync/` exists and `rulesync` is on `PATH`, the daemon runs
   `rulesync generate --check` at SessionStart (report) and as a commit gate (deny). The daemon never runs
   `generate` without `--check`, never writes `.rulesync/`, never installs Node or rulesync, and never asks a client to.
   If `.rulesync/` exists and the binary is absent, that is reported loudly ("rulesync tree present, binary missing,
   drift unchecked"), never skipped: the owner's no-silent-fallback rule.
3. **Why it is acceptable at all.** MIT licence, active (v40.1.0 on 2026-10-22), and it is the only tool that covers
   hooks and permissions across ~60 targets (SYNC §4). Re-implementing it is the rejected D3. Tracking the monthly
   tool churn is precisely the work the daemon should outsource (SYNC §2.4).
4. **Why not "recommended".** Three reasons an engineer-owner would weigh the same way: a Node dependency on a Python
   project's clients; near-daily releases mean a pinned minimum version and a staleness note in the check; and
   rulesync's own opencode hooks plugin (`.opencode/plugins/rulesync-hooks.js`) competes with the daemon's plugin
   (OPTIONS §2 B "Competing plugins"). The last one needs an engineering rule: when both are loaded, the daemon's
   plugin registers last on `execute.before` and the startup report names the other plugin.
5. **Wording for the docs.** "The daemon checks a rulesync tree if you use one" rather than "use rulesync". The
   daemon's differentiator is enforcement, not generation (SYNC §1 finding 6, OPTIONS §5).

Why CLEAR: the paper's two alternatives (D2 vs D1-only) are not exclusive; the low-regret combination is both, with D2
optional. No client is forced to take a dependency, so the owner's client-repo concern is untouched.

## Q3. May the daemon read opencode's `service.json` password to drive sessions via the HTTP API?

**Ruling: not in this epic. The question re-opens, and becomes the owner's, only if step 6 (external driver C) is
proposed. CLEAR as a ruling for the epic; the step-6 version is explicitly reserved for the owner.**

1. **Nothing in steps 0-5 needs it.** The permission path must be the plugin anyway (OPTIONS §2 C "Races"). The stop
   re-drive is in the plugin (decision 03). Crons can be an in-plugin scheduler (PLANWF §5 B.6) or OS-timer headless
   `opencode run` ticks (PLANWF §5 A.6) with no credential at all. The only things that genuinely need C are
   survival across an opencode server restart and the `/goal`-equivalent supervisor, and those are step 6.
2. **The technical facts, for when it re-opens.** The file is mode 0600, same user (ARCH §1.2). A daemon process
   already runs as that user, already reads `~/.claude/` transcripts and runs `git` with the user's credentials, so
   reading it grants no privilege the user's processes lack. What it does grant is **reach**: every session on that
   server across every project, not only this one (OPTIONS §2 C "Trust"). That reach, not the file read, is the
   trust decision, and it is the owner's.
3. **Mandatory constraints if the owner later says yes.** The daemon process alone reads the file; the password is
   never logged, never written to any daemon state file, never placed in a hook payload or any model-visible
   context, and the path is added to `secret_file_guard`'s protected set so no agent can read it. Every API call is
   scoped to sessions whose `directory` is this project. A dropped SSE subscription is reported in `status` and the
   next session banner (OPTIONS §4 item 6).
4. **Cost of this ruling.** Zero: nothing is built that the "no" would undo, and the "yes" is a small addition to a
   step the owner must green-light anyway.

Why CLEAR now: the ruling for the epic as scoped is "no, not needed", which no owner would reject. The trust question
is carried forward intact to the one step where it binds.

## Q4. Guarded opencode sessions (safety guards only) or fully unattended ones (autonomy layer too)?

**Ruling: guarded, at re-drive fidelity for Stop, is the epic's target (steps 0-5). Unattended is a separate go/no-go
decision taken on evidence after step 5, not a goal of this epic. CLEAR.**

1. **Guarded is where the daemon's value is and where the mechanism exists.** 108 of 187 handlers map at FULL
   fidelity and the first tranche is about 94 handlers (OPTIONS §2 B). The autonomy layer has no stop veto, no
   scheduler, no `/goal` (OPTIONS §1 fact 3). Building step 6 before steps 0-5 have measured re-drive behaviour would
   be building on an UNVERIFIED (loop risk through `session.prompt`, re-drive timing; OPTIONS §2 B "Open unknowns").
2. **Re-drive semantics are accepted for the guarded target, and declared, not hidden.** Every Stop handler's
   opencode state is "degraded: re-drive, not veto" in the per-host capability table (OPTIONS §4 item 1) and in
   `status`. That is what the owner's fail-loud rule requires, and it makes "permanent" the wrong word: it is the
   declared state until opencode grows a veto, at which point the table changes.
3. **The unattended decision is deferred with a defined trigger.** After step 5, a short findings note answers: does
   re-drive hold a session on task across N stops in the acceptance harness; does an in-plugin scheduler (PLANWF B.6)
   or OS-timer `opencode run` cover `persistent_crons` without C; what remains that only C can do. The owner decides
   step 6 on that note, together with Q3. Nothing in steps 0-5 forecloses either answer.
4. **"Unattended" under opencode is also a different product.** ccy supervision drives a PTY; opencode has an HTTP
   API and `opencode run --agent` (PLANWF §5 A.6, row "Agent switching"). Even a yes at step 6 is a redesign, not a
   port, which is another reason not to promise it inside this epic.

Why CLEAR: the sequencing closes no door, delivers the owner's stated requirements (AGENTS.md, sync, performance,
fail-loud) in the first steps, and puts the one real ambition question where the evidence to answer it will exist.

---

## Further owner-level questions the paper missed

Each is ruled where an engineer can; one is left for the owner.

### M1. Git hooks in client repositories (Option A step 1). CLEAR.

Installing `core.hooksPath` hooks is a new kind of write into a client checkout, beyond `.claude/`. Ruling: the hook
files live under the daemon's install root (`.claude/git-hooks/`), `core.hooksPath` is set in the clone's local git
config only (never committed), installation is **opt-in for existing clients** and offered at install time for new
ones, and an existing `core.hooksPath`, husky or pre-commit framework is chained into rather than replaced. If a
project declines, the daemon's SessionStart report says once per session that commit gates are Claude-Code-only, and
`opencode.json` still carries the `--no-verify` deny rule. That is loud without being nagging. The dedupe of the
double-run under Claude Code (PreToolUse plus hook) is an engineering item, not a question.

### M2. Opencode version pinning means client sessions can fail closed after an opencode upgrade. CLEAR.

Decision 06 (fail closed on an unsupported version unless an opt-in key is set) is right, but the owner should know
its consequence: with releases human-gated, each opencode release that breaks the pinned range leaves opencode
clients fail-closed until a daemon release ships. Ruling: accept it (it is exactly what no-silent-fallback means),
pin to a **range** not a version, and open a Routine (not a plan) that re-runs the acceptance harness against each new
opencode release so the daemon release follows promptly. The opt-in key carries the "untested version" banner.

### M3. A second toolchain (Bun/TypeScript) in this repository's QA. CLEAR.

Needed for the plugin's tests and the acceptance harness. Ruling: confined to `contracts/opencode-plugin/` and the
plugin directory, run in CI, and **not required on clients** (opencode bundles its own runtime and loads TS directly).
The daemon's own Python QA gate stays the gate; the Bun checks are an additional job.

### M4. Per-project opt-in for opencode support itself. CLEAR.

A `hosts:` key in `hooks-daemon.yaml` lists the hosts a project enables. Default for existing clients: `claude-code`
only. The opencode plugin is deployed and `opencode.json` touched only when `opencode` is listed. Without it, an
opencode session in that repository is still silent today; the A-step startup check (run by the daemon under Claude
Code) is what reports "this repository has no opencode protection", so the hole is at least named.

### M5. Project naming and identity once a second host is supported. UNCLEAR, non-blocking.

The package, binary, socket path and documentation are all named for Claude Code (`claude_code_hooks_daemon`,
`claude-code-hooks-daemon`). Supporting opencode does not require a rename, and a rename touches every client
install, so nothing in this epic should depend on one. But whether the product is "a Claude Code hooks daemon that
also covers opencode" or "a multi-host enforcement daemon" shapes the epic's documentation, the README positioning, and
whether SYNC §7 E6 (publishing the canonical event/decision model as the semantics layer sync tools lack) is in scope.
**The choice for the owner:** (a) keep the name and position opencode as an additional host, or (b) plan a rename
and multi-host positioning as its own later epic. Recommended default if no answer arrives: (a), with E6 out of
scope. This does not block any step; it is flagged because only the owner can set the product's identity.

---

## Consolidated verdict

| #   | Question                                  | Ruling                                                                                                                                    | Mark                  |
| --- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| Q1  | Migrate `CLAUDE.md` into `AGENTS.md`      | Yes: explicit opt-in migrate command for existing clients; default layout for new installs; shim pattern root and nested; this repo first | CLEAR                 |
| Q2  | rulesync                                  | Optional detected integration (D2, `--check` only), never a dependency or recommendation; D1 first                                        | CLEAR                 |
| Q3  | Read `service.json` password              | Not in this epic (nothing in steps 0-5 needs it); re-opens as the owner's call with step 6, under the listed constraints                  | CLEAR (deferred)      |
| Q4  | Guarded vs unattended                     | Guarded, re-drive fidelity declared as degraded; unattended is a post-step-5 go/no-go on evidence                                         | CLEAR                 |
| M1  | Git hooks in client repos                 | Opt-in for existing clients, local config only, chain existing frameworks                                                                 | CLEAR                 |
| M2  | Fail-closed on opencode upgrades          | Accept; pin a range; Routine to track opencode releases                                                                                   | CLEAR                 |
| M3  | Bun/TS toolchain                          | CI-only, confined, never on clients                                                                                                       | CLEAR                 |
| M4  | Per-project host opt-in                   | `hosts:` key, default Claude Code only                                                                                                    | CLEAR                 |
| M5  | Product naming and multi-host positioning | Keep the name for this epic; the identity question is the owner's                                                                         | UNCLEAR, non-blocking |

One item goes up to the owner: M5. It blocks nothing.
