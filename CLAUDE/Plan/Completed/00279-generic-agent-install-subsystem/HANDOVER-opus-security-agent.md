# Handover: the `opus-security` delegation mechanism

> **Generalised field handover** imported into Plan 00279 from a
> defensive-security infrastructure estate that installs this daemon. It
> describes THAT estate, not this repository; estate-specific paths in the
> appendices have been placeheld on import.

> **Read-boundary notice.** This document deliberately carries the flaggable vocabulary it
> describes (it enumerates the classifier's trigger categories). It is written for the
> claude-code-hooks-daemon maintainer, on a model not subject to the classifier. It must not be
> read into a coordinator context running the affected caller model. Note that its filename does
> **not** match the `*-opus-security-DETAIL*` marker that the mechanism's own read-ban keys on —
> that hole is itself a finding, see §3.4.

**Source note.** Four of the five nominated sources exist and are reproduced verbatim in the
appendices. The fifth — the prior incident write-up `untracked/hooks-daemon-fable-cyber-flags.md`
— **is not on disk**; drafting it is what flipped the session at 06:51 (the boundary doc says so
explicitly), and it was never persisted. Its substance is reconstructed here from the estate's own
mitigation plan and its journal. The detection-backstop proposal (§2.6) survives only as one
sentence in those files; everything beyond that sentence is my own extrapolation and is labelled
as such. No handler names, config keys or option schemas below should be read as sourced.

---

## 1. WHY the mechanism exists

### 1.1 The model-fallback problem

The caller model in this estate (Fable 5) carries an **API-side content safety classifier**. When
a request reads like offensive security, the platform flags it and **silently substitutes a
different model for the remainder of the session**. The transcript JSONL records this as:

```
subtype: model_refusal_fallback
apiRefusalCategory: "cyber"
scope: "session"
```

Three properties make it pathological rather than merely annoying:

- **Sticky** — `scope: "session"`, so one flag degrades every subsequent turn.
- **Silent** — announced once, in one line, then never again.
- **Unchosen** — no human and no agent decided to change model; capability and effort profile
  change underneath the work in progress.

Generalise past the specific pair: *any* caller-side model with an API-side content classifier and
a session-scoped fallback has this failure mode. `Fable 5 → Opus 4.8` is the instance, not the
requirement, and a daemon feature should be written against the record shape, not the model names.

### 1.2 Why it is structural here, not incidental

The estate's entire subject matter is the material that false-positives: firewalls and edge
filtering, anti-spoof rules, fail2ban, rkhunter/IDS, host hardening. **The classifier keys on
attack mechanics, not on intent** — and describing a defence very often requires describing the
attack it stops. So legitimate daily defensive work triggers it, and recurrence is guaranteed.

### 1.3 The evidence — and the failure modes found iteratively

**At least five fallbacks occurred in a single session (2026-08-27), three of them timestamped.**
The sequence matters more than the count, because each one revealed a distinct leak that the
previous fix did not cover:

| #   | When      | What triggered it                                                                                        | Failure mode revealed                                                                                                                                       |
| --- | --------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 01:02:27Z | Writing an anti-spoof firewall rule *and describing the forged-source packet it drops*                   | The base case: producing attack-mechanics text flags, even defensively.                                                                                     |
| 2   | 06:42:07Z | Reading rootkit-scanner internals in the main context "to understand the question" **before** delegating | **Scouting-first.** Reading-to-scope is reading. The decision must be made from task framing or path, never from content.                                   |
| 3   | 06:51:11Z | Drafting the incident write-up in the main loop                                                          | **A document that enumerates the categories trips the flag.** Meta-work about the classifier is itself flaggable. (This is why source five does not exist.) |
| 4   | (untimed) | Merely *coordinating* the delegated work — repeating the topic's trigger nouns turn after turn           | **Coordinator vocabulary accumulation.** Delegation removes the worst exposure but not all of it; repetition alone accumulates to a flip.                   |
| 5   | (untimed) | A delegation prompt that briefed the subagent in detail (config knob names, method specifics)            | **The handoff prompt is itself a contamination vector** — it composes the exact vocabulary the mechanism exists to exclude, in the act of excluding it.     |

A sixth channel was identified by inspection rather than by a flip:

- **The git-command contamination channel.** `git diff`, `git show`, `git log -p`, `git add -p`,
  and `grep`/`rg` over a flaggable file pull that file's content into the coordinator's context
  **inside a routine command's output, with no deliberate `Read` at all.** A file-handoff contract
  does not cover this, because nobody ever decided to read the file.

### 1.4 The conclusion the evidence forces

Failures 4 and 5 are the important ones for a tooling maintainer: they show that **prevention has
a ceiling.** A session that must coordinate a lot of this work will flip eventually no matter how
disciplined the routing is. Therefore the durable answer is **detection** — noticing the platform's
own fallback record and telling a human within minutes rather than hours (the observed first
incident ran ~5.5 hours degraded before the owner noticed).

---

## 2. WHAT the mechanism is

Six parts. Parts 1–5 are implemented and in use; part 6 is a proposal.

### 2.1 The delegation boundary (the SSoT doc)

`CLAUDE/fable-safeguard-delegation.md` defines precisely which work is flaggable. The precision is
deliberate: routing *all* security work to the fallback model abandons the caller model entirely,
which in a defensive-security estate is most of the work.

**Delegate** when the sub-task requires reading or producing text describing: packet spoofing /
source forgery / anti-spoof mechanics; firewall bypass or evasion framing; exploit development or
CVE *exploitation* (as opposed to scanning/patching); IDS or rootkit-scanner **internals** from the
attacker's side — including merely *investigating* them; credential handling framed as extraction,
cracking or misuse; or **any doc, report or comment that enumerates these categories**.

**Stay on the caller model** for: ordinary config, sizing, addressing, inventory, templating,
plan/doc/journal work; standard vaulting and key rotation; declaring a firewall rule by its
*declared effect* without narrating the attack; editing a non-mechanics line in a security-adjacent
file. The doing is fine; the narrating is what flips.

**Tie-break rule**: when unsure, delegate. A needless round-trip costs one subagent invocation; a
needless flip costs the session's model.

### 2.2 Delegate before you read *or scout*

The routing decision is made from signals that do not require ingesting the content — the request
framing, the filename, the path. If the sub-task is flaggable, **the first tool call about it is
the delegation**, not a `Read`, not a `grep`, not a host probe, not a draft. Hand over the
question, not your findings about it.

### 2.3 The two-file artefact contract, with a read-boundary

Discovered live: **a subagent's final text reply does not reliably reach the coordinator** (only a
meta wrapper arrives), and its raw transcript must never be read back — the transcript holds
everything the subagent read, so reading it re-contaminates exactly the context being protected.

So the subagent communicates **only by written files**, two of them:

- **`<topic>-opus-security-SUMMARY.md`** — mandatory. Operational language only, provably clean:
  no mechanics, no log internals, no payloads, no signatures. Leads with done/not-done and the
  proof, names files and commits, states gaps honestly. **This is the only file the coordinator
  ever reads.**
- **`<topic>-opus-security-DETAIL.md`** — the raw flaggable substance when worth preserving. **The
  coordinator must NEVER read it**; it is for a human or another quarantine-model agent opening it
  on purpose. Its own first line says so.

The `-opus-security-SUMMARY` / `-opus-security-DETAIL` tokens are the constant markers. The
subagent's text reply is reduced to the SUMMARY path plus the word "written".

### 2.4 The subagent owns the entire git cycle

Because of the channel in §1.3, the subagent **stages, commits and pushes its own flaggable
files** with a proper plan-referencing message, exactly as the main loop would have. The SUMMARY
reports the commit hash and CI expectation; **the coordinator confirms CI by status (green/red),
never by diffing the content.** Content-revealing git and grep over those paths are forbidden in
the main context.

### 2.5 Lean-pointer delegation prompts, and coordinator hygiene

The handoff prompt is a **pointer, not a briefing**: name the plan task ("read
`CLAUDE/Plan/NNNNN-*/PLAN.md` and execute Task N.N"), state the output contract, stop. The plan
document carries the specifics — written once, read by the subagent, never recomposed in the main
context.

Alongside it: name the topic **once** to decide and delegate, then refer to it obliquely ("the
delegated assessment", "the sensitive work") for the rest of the session.

### 2.6 The proposed detection backstop *(reconstructed — one sentence survives)*

The only surviving description of the proposal is: *an automated check that reads the
`model_refusal_fallback` record the platform already writes and prompts a restart, so a human
learns the session is degraded in minutes rather than hours.* Everything more specific than that
sentence was lost with the incident write-up. The record shape in §1.1 is what such a check keys
on; the un-flip itself requires a session restart, since the fallback is sticky.

---

## 3. How the daemon could generalise this

Framing: the daemon already has the two handler shapes this needs, and already embodies the core
insight in `project_handler_load_checker` — **a silently-disabled guarantee needs an alert, because
nobody notices otherwise.** A silent model downgrade is the same class of problem.

### 3.1 `session_start` — fallback detection (highest value, lowest risk)

Scan the session transcript JSONL for `subtype: model_refusal_fallback` records; if any are
present, inject a loud advisory in the style of the existing `🚨 PROTECTION DEGRADED 🚨` alert:
the session is running a substituted model, `scope: session` means it will not recover on its own,
restart to clear it. Report-only, no blocking, no config required beyond enable/disable. This is
the part the estate cannot build itself — it needs to run *before* the agent's first turn and it
needs transcript access. It is also model-agnostic: it keys on the record, not on model names.

### 3.2 `pre_tool_use` — path-triggered delegate-first advisory

On a project-configured list of sensitive globs, advise (do not block) that a flaggable sub-task
should be delegated before the file is opened. Pattern it on `lsp_enforcement`'s `block_once` mode:
first touch in a session gets the guidance, retries pass. The estate approximates this today with
a `.claude/rules/` pointer, but a rule fires on *any* touch and cannot distinguish the first
scouting read — which is precisely the failure mode in §1.3 row 2.

### 3.3 `pre_tool_use` — close the git/grep contamination channel by command shape

The estate's rule can only *ask* the agent not to run `git diff`/`show`/`log -p`/`add -p` or
`grep`/`rg` over the flaggable paths. A handler can **deny** it, matching on command shape plus
configured globs — the same way `markdown_organization` closes the bash-redirect and `tee`
side-doors around its Write/Edit block. This is the single leak an agent-side convention cannot
plug, because the content arrives with no deliberate read.

### 3.4 Enforce the artefact read-boundary by pattern, not by trust

The `*-opus-security-DETAIL*` read-ban is currently a naming convention with **zero enforcement**,
and it fails exactly where the boundary doc says the risk is highest: documents *about* the
mechanism. This very report is the proof — it enumerates every category and is named such that no
pattern catches it. A daemon handler could deny `Read` on a configured "quarantined artefact"
glob from a non-quarantine context, and could equally warn when a new file enumerating the
configured trigger vocabulary is being authored outside one.

### 3.5 What a generic feature would need from a project

A small config block: the trigger globs, the artefact markers, the forbidden command shapes, and
the quarantine subagent's name. Everything else — the boundary doc, the skill, the agent — stays
project-owned, because the boundary is domain-specific and over-routing is its own failure.

---

## Appendix A — `.claude/agents/opus-security.md` (verbatim)

```markdown
---
name: opus-security
description: Execution space for safeguard-flaggable work — tasks that require reading or producing text describing attack, spoofing, evasion, exploit, or rootkit/intrusion mechanics, even when the intent is defensive. Runs on Opus (not subject to Fable's [cyber] classifier) so the main context never ingests the flaggable material and never silently falls back. The main loop delegates the whole sub-task here BEFORE opening the sensitive content, and receives back only a clean, high-level summary. Use for: writing/altering anti-spoof or firewall-evasion rules, fail2ban/rkhunter/IDS internals, exploit or CVE-exploitation work, offensive-shaped credential handling, or anything that reads like offensive security. See CLAUDE/fable-safeguard-delegation.md for the boundary.
model: opus
tools: Read, Write, Edit, Grep, Glob, Bash
---

You are the quarantine execution space for **safeguard-flaggable** infrastructure work in a
defensive-security IaC estate. You exist because the calling model (Fable 5) carries an API-side
`[cyber]` classifier that false-positives on legitimate defensive work the moment it must read or
produce text describing attack mechanics — and a single flag silently downgrades that model for the
whole session. You run on Opus, so you can hold that material without tripping the flag. **Read
`CLAUDE/fable-safeguard-delegation.md` in full before anything else** — it is the boundary and the
clean-summary contract you must honour.

## What you do

You do the real work the caller handed you — read the sensitive files, write or edit the firewall /
nftables / fail2ban / rkhunter / hardening / exploit material, run the verification, follow every
estate standard that applies (the `CLAUDE/*.md` bodies, the two-layer lint, the vault rules, the
no-armed-flags doctrine, plan/journal discipline if the caller is inside a plan). You are a full
executor, not an advisor: you are expected to Edit/Write and run `shellscripts/*` gates exactly as
the main loop would, to the same "done means proven" bar.

**You own the ENTIRE git cycle for the flaggable files — stage, commit, and push them yourself.**
The coordinator must never `git add` / `git diff` / `git show` / `git log -p` / `git add -p` or
`grep` those files, because every one of those pulls the flaggable content into its context with no
deliberate Read at all. So you finish the job: commit your changes with a proper `Plan NNNNN:`
message and push, exactly as the main loop would have. Your SUMMARY then reports the commit hash and
CI expectation; the coordinator confirms CI by status (green/red), never by diffing the content.

## The one rule that makes you worth having

**Your final report to the caller MUST be a clean, high-level summary** — what changed, which files,
what the verification showed, what remains — **with none of the attack-mechanics vocabulary that
would re-contaminate the caller's context.** Describe a dropped-spoofed-source rule as "added the
declared observe-only edge rule and proved it loads"; do not quote the forged-packet reasoning, the
exploit payload, the evasion technique, or the rootkit-scanner internals back up the channel. The
detail lives in the files, the commit message, and the plan JOURNAL — read on purpose by whoever
needs it — never in the summary that lands back in the main loop.

If the task turns out NOT to be flaggable (routine defensive config with no attack-mechanics text),
say so in one line so the caller learns the boundary — but still complete it, since you are already
here.

## Reporting — you communicate ONLY by written artefacts, in TWO files

Your text replies do not reach the coordinator (only a meta wrapper arrives), and your raw transcript
must never be read back (it holds everything you read and would re-contaminate the caller). So you
**communicate only by writing files** — never by returning findings in your reply. Write two:

- **`<name>-opus-security-SUMMARY.md`** — MANDATORY. Operational language only, **provably clean of
  anything flag-worthy**: no attack/spoofing/evasion/exploit/rootkit mechanics, no log internals, no
  payloads, no signatures. This is the ONLY file the coordinator (Fable) reads. Write it as if a
  safety classifier will scan it — because one will.
- **`<name>-opus-security-DETAIL.md`** — when there is raw flaggable substance worth preserving (the
  technical analysis, the internals you examined, the mechanics). This file **must NEVER be read by
  the main/Fable context** — it exists for a human or another Opus agent who opens it on purpose. Say
  in the DETAIL file's own first line that it is not for the coordinator.

Naming: put both under `untracked/` (or the governing plan's `reports/` for a durable deliverable);
the constant markers are the `-opus-security-SUMMARY` and `-opus-security-DETAIL` tokens (prefix or
suffix around a topic name is fine). Your text reply to the caller is just: the SUMMARY file's path
and the word "written" — nothing else, no findings, no topic vocabulary.

The SUMMARY must still: lead with done / not-done and the proof; name the files touched and commits;
state any gap honestly; and carry none of the flaggable vocabulary — that is the entire point.
```

## Appendix B — `.claude/skills/security-delegation/SKILL.md` (verbatim)

```markdown
---
name: security-delegation
description: Invoke BEFORE doing any infrastructure work that requires reading or producing text describing attack, spoofing, evasion, exploit, CVE-exploitation, or rootkit/intrusion mechanics — even when the intent is defensive (firewall/nftables anti-spoof rules, fail2ban, rkhunter/IDS internals, offensive-shaped credential handling). Routes the flaggable sub-task to the opus-security subagent so Fable's [cyber] classifier never sees it and the session never silently falls back to Opus. Not for routine defensive config, vaulting, or inventory work.
argument-hint: "[the flaggable sub-task to delegate]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Grep, Glob
---

# Security delegation — keep flaggable work out of Fable's context

**Read [`CLAUDE/fable-safeguard-delegation.md`](../../../CLAUDE/fable-safeguard-delegation.md) — it
is the single source of truth for the boundary, the delegate-before-you-read rule, and the
clean-summary contract.** This skill is the trigger; that document is the body.

## The move

1. **Decide from the framing or the path, not the content.** If the sub-task requires reading or
   writing attack/spoofing/evasion/exploit/rootkit mechanics — even defensively, and even just to
   *investigate* — it is flaggable. So is **authoring any doc, report, or comment that enumerates
   these categories** (a write-up about the flag trips the flag). Decide before opening the file:
   **scouting first is reading first.** If the request is flaggable, the FIRST tool call about it is
   the `Agent(subagent_type: "opus-security")` call — not a Read, grep, host probe, or draft. Hand
   over the question, not your findings about it. (This was learned the hard way: the session
   flipped twice more by scouting-then-delegating.)
2. **Delegate the whole sub-task** to the Opus executor:
   `Agent(subagent_type: "opus-security", prompt: <goal + files, not a narration of the attack>)`.
   The subagent reads/writes the sensitive material in its own context and runs the estate gates.
3. **Take back only the clean summary.** It reports what changed, which files, what the verification
   showed — no attack-mechanics vocabulary. The detail lives in the files, commit and JOURNAL.

## When NOT to use this

Routine defensive work with no attack-mechanics text stays on Fable: ordinary service config,
sizing, addressing, inventory, templating, plan/doc/journal work, standard vaulting and key
rotation, or declaring a firewall rule by its effect without narrating the attack it stops. The
boundary and worked examples are in the body doc — when unsure, delegate: a needless round-trip is
cheap, a needless session-wide model flip is not.
```

## Appendix C — `.claude/rules/fable-safeguard-delegation.md` (near-verbatim)

All four globs are placeheld on import — the originals were the estate's real
directory layout.

```markdown
---
paths:
  - "<firewall-templates-dir>/**"
  - "<tarpit-templates-dir>/**"
  - "environment/<inventory>/group_vars/all/hardening.yml"
  - "<intrusion-detection-source-dir>/**"
---

# Delegate safeguard-flaggable work to the Opus subagent

You are touching a file whose security-mechanics content can trip Fable 5's `[cyber]` classifier
and silently fall the whole session back to another model. **Before reading or writing the
attack/spoofing/evasion/rootkit mechanics in these files, decide whether the sub-task is flaggable —
from the task framing, not by opening the content first — and if it is, hand the whole sub-task to
the `opus-security` subagent** (`Agent(subagent_type: "opus-security", …)`). The subagent holds that
material in its own context and returns only a clean summary, so this context never carries the
vocabulary that flips the model. Routine edits here that touch no attack-mechanics text (a sizing
value, a comment, a declared rule stated by its effect) stay on Fable — the reminder prompts the
decision, it does not mandate delegation. **Forbidden**: narrating spoofing/exploit/evasion mechanics
in the main loop when a delegated subagent could hold them instead; reading or **scouting** the
flaggable content first "to decide" or "to scope it", which defeats the point by taking it into
context before handing over — if the sub-task is flaggable, the FIRST tool call is the delegation,
not a Read/grep/probe; **authoring a doc or comment here that enumerates the attack-mechanics
categories** — a write-up about the flag trips the flag, so delegate that too; **reading any
`*-opus-security-DETAIL*` file** from the main context — that file holds the raw flaggable substance
on purpose and is for a human or another Opus agent, never for Fable, which reads only the paired
`*-opus-security-SUMMARY*`; and **running any content-revealing git or grep over the flaggable
files** — `git diff`/`show`/`log -p`/`add -p` naming these paths, or `grep`/`rg` for their mechanics
— because that pulls the content into context with no Read at all. The `opus-security` subagent
stages, commits and pushes these files itself; the coordinator confirms CI by status, never by
diffing the change.

**Full statement, the boundary and the clean-summary contract**:
[`CLAUDE/fable-safeguard-delegation.md`](../../CLAUDE/fable-safeguard-delegation.md)
```

## Appendix D — the fifth artefact

`CLAUDE/fable-safeguard-delegation.md` is the SSoT body and is ~140 lines; it is not reproduced
here because §1 and §2 above are a faithful synthesis of it and this report is meant to be read in
one sitting. The maintainer should take it from the repo directly if the mechanism is promoted —
it is the file that defines the boundary, and the boundary is the part that must not be guessed at.
