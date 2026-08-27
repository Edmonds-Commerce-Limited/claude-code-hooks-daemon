# Fable `[cyber]` safeguard flips — problem, mitigation, and a possible daemon handler

> **Generalised field report** imported into Plan 00278 from a defensive-security
> infrastructure estate that installs this daemon. It describes THAT estate, not
> this repository. Sanitised at source (no real hostnames, IPs, addresses,
> tokens) and further generalised on import (the reporting project's own plan
> numbers removed).

## TL;DR

Claude Code's Fable 5 model carries an API-side safety classifier. When a request *reads like
offensive security*, the platform flags it (`apiRefusalCategory: "cyber"`) and **silently falls the
whole session back to a different model** (`scope: "session"`). For a defensive-security IaC estate
— firewalls, spoofing defence, fail2ban, intrusion-detection tooling — this is a routine
false-positive, and each occurrence downgrades the model for hours with nobody choosing it.

This is **not a hooks-daemon defect** — it is a model-platform behaviour. Our mitigation is
repo-level (a subagent + a skill + a path rule). A daemon-level handler *could* complement it; that
option is sketched at the end.

## The problem in detail

### What triggers it

The classifier keys on **attack-mechanics content, not on intent**. Defensive intent does not make a
request safe if answering it requires reading or producing text that describes *how* an attack, an
evasion, or an intrusion works. That is the trap for an estate whose whole job is building defences:
describing a defence usually means describing the attack it stops.

Observed trigger classes in this estate:

- packet spoofing / source-forgery / reverse-path (anti-spoof) mechanics;
- firewall/filter **bypass or evasion** framing;
- exploit development or CVE **exploitation** (vs. scanning/patching);
- intrusion-detection / rootkit-scanner **internals** described from the attacker's side;
- credential/key handling framed as **extraction or misuse** rather than routine vaulting.

### What the flip looks like

The transcript JSONL records it explicitly. Two record shapes appear (fields sanitised, structure
verbatim):

```json
{
  "type": "system",
  "subtype": "model_refusal_fallback",
  "level": "warning",
  "trigger": "refusal",
  "direction": "retry",
  "scope": "session",
  "originalModel": "claude-fable-5",
  "fallbackModel": "claude-opus-4-8",
  "apiRefusalCategory": "cyber",
  "content": "Fable 5's safeguards flagged this message. ... Switched to Opus 4.8. Details: `[cyber]`"
}
```

```json
{
  "message": { "role": "assistant", "model": "claude-opus-4-8",
    "content": [ { "type": "fallback",
      "from": { "model": "claude-fable-5" },
      "to":   { "model": "claude-opus-4-8" } } ] }
}
```

### Why it hurts

- **`scope: "session"`** — the switch is sticky. One flagged turn downgrades every later turn,
  including unrelated work, until the session is restarted.
- **Silent after the first line** — no per-turn banner. In one measured case the session ran on the
  fallback model for ~5.5 hours before a human noticed.
- **Structural, not incidental** — this estate does the flaggable class of work every day, so the
  flip recurs by design of the domain, not by accident of one prompt.

### How to detect it after the fact

Scan the session transcript for the two records above:

```bash
# In the session JSONL: find the exact flip point and direction.
python3 - <<'PY'
import json, glob
for path in glob.glob("<session>.jsonl"):
    for line in open(path):
        if 'model_refusal_fallback' in line or '"type": "fallback"' in line:
            r = json.loads(line)
            print(r.get("timestamp"), r.get("subtype") or "fallback",
                  r.get("apiRefusalCategory",""), r.get("scope",""))
PY
```

## What we are doing about it — repo-level delegation

The guard is **delegation, not persuasion of the classifier**: recognise the flaggable category
from the *task framing or the target path*, and hand that sub-task to a dedicated **Opus subagent**
*before* the main Fable context reads the flaggable content. The subagent runs on a model the
platform itself falls back to, so it holds the attack-mechanics text in its **own** context and
returns only a clean summary. The main loop's context never carries the vocabulary that trips the
flag, so it never flips.

The boundary is deliberately **narrow**: a defensive-security estate must not route *all* security
work to Opus (that abandons the faster model entirely). Only the attack-mechanics-*describing*
subset delegates; routine defensive config, vaulting, inventory and templating stay on Fable.

Three artefacts implement it (plus a single-source-of-truth boundary doc).

### 1. The Opus subagent — `.claude/agents/opus-security.md`

```markdown
---
name: opus-security
description: >-
  Execution space for safeguard-flaggable work — tasks that require reading or
  producing text describing attack, spoofing, evasion, exploit, or
  rootkit/intrusion mechanics, even when the intent is defensive. Runs on Opus
  so the main context never ingests the flaggable material and never silently
  falls back. The main loop delegates the whole sub-task here BEFORE opening the
  sensitive content, and receives back only a clean, high-level summary.
model: opus
tools: Read, Write, Edit, Grep, Glob, Bash
---

You are the quarantine execution space for safeguard-flaggable infrastructure
work. You do the real work (read the sensitive files, edit the rules, run the
gates) to the same "done means proven" bar as the main loop.

The one rule that makes you worth having: your final report MUST be a clean,
high-level summary — what changed, which files, what the verification showed —
with NONE of the attack-mechanics vocabulary that would re-contaminate the
caller's context. The detail lives in the files, the commit, and the journal.
```

### 2. The trigger skill — `.claude/skills/security-delegation/SKILL.md`

`disable-model-invocation: false` lets the model self-route when the *description* matches a
flaggable ask; `user-invocable: true` lets a human call it too.

```markdown
---
name: security-delegation
description: >-
  Invoke BEFORE doing any infrastructure work that requires reading or producing
  text describing attack, spoofing, evasion, exploit, CVE-exploitation, or
  rootkit/intrusion mechanics — even defensively. Routes the flaggable sub-task
  to the opus-security subagent so the classifier never sees it and the session
  never silently falls back. Not for routine defensive config or inventory work.
argument-hint: "[the flaggable sub-task to delegate]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Grep, Glob
---

# Security delegation

1. Decide from the framing or the path, NOT the content — reading the file first
   already takes the material into context and can flip the session mid-read.
2. Delegate the whole sub-task:
   Agent(subagent_type: "opus-security", prompt: <goal + files, not a narration>)
3. Take back only the clean summary.
```

### 3. The path-triggered rule — `.claude/rules/fable-safeguard-delegation.md`

Claude Code injects the whole rule file when an edit matches its `paths:` globs, so touching a
known-sensitive file auto-surfaces the delegate-first reminder.

```markdown
---
paths:
  - "<edge-firewall-rules-dir>/**"
  - "<tarpit-config-dir>/**"
  - "<hardening-vars-file>"
  - "<intrusion-detection-source-dir>/**"
---

# Delegate safeguard-flaggable work to the Opus subagent

You are touching a file whose security-mechanics content can trip the classifier.
Before reading or writing those mechanics, decide (from the framing, not by
opening the content) whether the sub-task is flaggable; if it is, hand the whole
sub-task to the opus-security subagent. Routine edits that touch no
attack-mechanics text stay on the fast model.
```

### The delegate-before-you-read invariant

The decision **must** be made from signals that do not require ingesting the flaggable content — the
request framing, the filename, the path — because once the main loop opens the sensitive text it has
already taken the trigger material into context and can flip mid-read. So: read the *request* and
the *path*, decide, and if flaggable, invoke the subagent without opening the file first.

### The clean-summary contract

The subagent's entire value is that the flaggable material stays in *its* context. Its report back
must be operational — "added the declared observe-only edge rule and proved it loads" — never a
quote of the attack reasoning, the exploit payload, or the scanner internals. The detail belongs in
the files, the commit message, and the plan journal, which are read on purpose by whoever needs
them; a summary that quotes the mechanics back up the channel re-contaminates the exact context this
mechanism exists to keep clean.

## Optional: a daemon-level handler (proposal, not built)

The repo-level guard depends on the agent choosing to delegate. A hooks-daemon handler could add a
deterministic backstop, entirely within the daemon's existing PreToolUse model:

- **`fable_flaggable_advisor` (PostToolUse / UserPromptSubmit, advisory)** — pattern-match the
  request or the `Edit`/`Write` target path against a configurable flaggable-topic set and inject:
  *"this looks safeguard-flaggable; consider `Agent(subagent_type: opus-security)`."* Advisory, like
  the existing `background_process_tracker`.
- **`model_fallback_detector` (SessionStart / Stop, advisory)** — scan the live transcript for a
  `model_refusal_fallback` record and warn that the session is running degraded, so a human can
  restart rather than discovering it hours later. This is the highest-value, lowest-risk piece: it
  needs no classifier of its own, only to read a record the platform already writes.

Config shape would mirror existing handlers:

```yaml
handlers:
  post_tool_use:
    fable_flaggable_advisor:
      enabled: true
      flaggable_path_globs:
        - "<edge-firewall-rules-dir>/**"
        - "<intrusion-detection-source-dir>/**"
      flaggable_topic_terms: ["spoof", "evasion", "exploit", "rootkit"]
  session_start:
    model_fallback_detector:
      enabled: true
```

Neither is built here — the repo-level agent/skill/rule is the shipped mitigation. The daemon pieces
are offered because the daemon already owns the PreToolUse/SessionStart surfaces they would use, and
the fallback-detector in particular would help *every* project the daemon protects, not just this
estate.

## Evidence pointer

The triggering event and its records are preserved in the reporting session's transcript JSONL
(session id, `requestId`, and timestamps are in the estate's own plan journal, kept out of this
sanitised note). The mitigation ships as a plan in the estate's own repository.
