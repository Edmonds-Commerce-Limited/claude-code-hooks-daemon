# Decision request: what should survive degraded mode

**Status**: DECIDED — see
[fable-degraded-mode-decision.md](fable-degraded-mode-decision.md): "B, then
A", both narrowed, with the reporters' silence on an unparseable config fixed
first. Nothing here is implemented.
**Source**: Plan 00412, run `2026-001`, check `D-SEC` — the highest-value
finding in the run, and the only one where three individually-sound decisions
compose into something none of them intended.

This document exists because the remedy changes the gate surface in **every
installing project**. That is not a call to make from inside a security sweep.

## The chain

Three decisions, each defensible on its own, verified against current code:

**1. A config-validation failure fails open.**
`daemon/controller.py:915-926`. Deliberate, per Plan 00304 — and already
narrowed once by that plan, which added `_degraded_mode_safety_net`
(`controller.py:794-841`) after a real-repo canary caught `git reset --hard`
sailing through unblocked.

That safety net hard-codes **exactly one handler**: `DestructiveGitHandler`.
So degraded mode does not disable *everything* — it reduces the PreToolUse
guard set to one.

What does **not** survive, among others:

| Handler               | What stops being enforced                        |
| --------------------- | ------------------------------------------------ |
| `secret_file_guard`   | protected files' contents can be read            |
| `sensitive_content`   | blocked patterns and secret terms can be written |
| `sed_blocker`         | `sed -i` across the tree                         |
| `project_containment` | writes outside the repository                    |
| `curl_pipe_shell`     | `curl … \| bash`                                 |

**2. Nothing guards writes to the config that triggers it.**
`.claude/hooks-daemon.yaml` has no write guard. It is also *explicitly* on
`sensitive_content`'s `exclude_paths` (line 265) — for a good reason, stated in
the file: "A rules file must be able to contain its own rules." That exemption
is correct in isolation and is the second link here.

**3. Every deny message names the key that disables the handler.**
`To disable: handlers.pre_tool_use.<name> (set enabled: false)`. Excellent
documentation — it appears on every block, and it is how an agent learns to fix
a misconfiguration rather than thrash against it.

## Why the composition matters

Read together: **one malformed line reduces the guard set to one handler,
nothing prevents that line being written, and the deny messages are a map of
which line to write.**

The property worth naming is not "an attacker could do this". It is that **a
typo and an attack have the same blast radius**, and the system reports both
the same way — as a configuration-error advisory. There is no signal that
distinguishes "someone fat-fingered the YAML" from "the guard set was reduced
to one handler deliberately".

No single decision is wrong. The chain was found by a reviewer looking at one
check (`D-SEC`); none of the three authors could have seen it from their own
change.

## What is NOT claimed

- This is not a privilege-escalation path. An agent that can write the config
  can already write files; the guards are advisory infrastructure for an agent
  acting in good faith, not a sandbox.
- Plan 00304 already did the hard part of the analysis. This is a question of
  where its line now sits, not a new discovery that fail-open is dangerous.
- Nothing here is exploitable by issue text or any other untrusted input that
  cannot already write to the repository.

## Options

### A. Widen the safety net (extend Plan 00304's precedent)

Add the config-independent guards to `_degraded_mode_safety_net` — the ones
that hard-code their own patterns and need no options: `sed_blocker`,
`curl_pipe_shell`, `chmod_world_writable`, and arguably `secret_file_guard`
using default globs.

- **For**: follows a precedent already set and tested; each addition is
  individually justifiable by the same argument Plan 00304 made.
- **Against**: the list will drift out of date silently, exactly like
  `_SCOPED_TREES` in the authored-path Defence. Needs its own Detector — a
  handler that declares itself config-independent but is absent from the net.

### B. Make degraded mode loud rather than permissive

Keep fail-open, but stop treating a reduced guard set as an ordinary advisory:
surface it in the status line, and say in the advisory *how many* handlers are
active versus configured.

- **For**: no behaviour change, so no installing project breaks; it attacks the
  actual defect, which is that the state is indistinguishable from healthy.
- **Against**: an advisory nobody reads changes nothing. Weakest option if the
  concern is genuinely adversarial.

### C. Guard the config file

Treat `.claude/hooks-daemon.yaml` as write-sensitive: require the edit to
validate before it lands.

- **For**: cuts the chain at link 2 rather than mitigating link 1.
- **Against**: the bootstrap problem is real — a broken config cannot be fixed
  if fixing it requires a working daemon. Needs a careful escape hatch, which
  is the shape of thing that becomes the vulnerability.

### D. Accept and document

Record the chain in `CLAUDE/Security/`, change no code.

- **For**: honest; the threat model genuinely does not include an adversary
  who can already write to the repo.
- **Against**: leaves the typo case, which is the likely one and the reason
  this was found at all.

## Recommendation

**B, then A.** B first because it is the only option that costs no installing
project anything and it addresses the part that is indefensible on any threat
model — that a degraded guard surface currently looks like a healthy one. A
second, with the Detector that keeps its list honest, since the precedent and
the test scaffolding both already exist.

C is the strongest and the riskiest; it should not be attempted as a follow-on
to a security sweep, because the bootstrap escape hatch needs designing in its
own right.

Whichever is chosen, the argument for a Detector is the same one this plan has
now proved twice: a list that must be kept in step with a growing set of
handlers will fall out of step, and nothing will notice.
