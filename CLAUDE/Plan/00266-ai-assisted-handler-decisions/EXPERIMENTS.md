# Experiments: native `prompt` hooks, run live against this repository

Phase 1 research established what the *documentation* says. This document
records what actually **happened** when a native `prompt` hook was registered
in this repository and triggered. Every claim here is an observation from a
live run, not a reading of the docs.

**Environment**: Claude Code `2.1.241`, this repository (self-install mode),
daemon RUNNING, branch `plan/00266-ai-assisted-hooks`.

---

## Experiment 1 — Does a `type: prompt` hook work at all here?

### Setup

A second hook was appended to `PreToolUse`'s existing entry — **Layout B**,
the only layout `RESEARCH-claude-code-native-hooks.md` measured clean:

```json
{
  "type": "prompt",
  "prompt": "Hook input: $ARGUMENTS\n\nIf tool_name is Bash AND tool_input.command contains the exact string ECHD_PROBE_DENY, output exactly this JSON and nothing else:\n{\"hookSpecificOutput\":{...\"permissionDecision\":\"deny\"...}}\n\nOtherwise output exactly this and nothing else:\n{}",
  "timeout": 30
}
```

The design intent was a hook that could only ever deny one sentinel string and
stayed neutral otherwise — so it could be installed on the hot path safely.

### Result: **YES, and the intent failed in an instructive way**

| #   | Finding                                                                          | Evidence                                                                                                                                                                                                                                                         |
| --- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `type: prompt` hooks **are supported and do fire** in 2.1.241                    | The hook produced a `PreToolUse:Write hook error` that stopped a `Write` call                                                                                                                                                                                    |
| 2   | A hook added **mid-session takes effect without a restart**, after a short delay | The first probe (a `Bash` call carrying the sentinel) ran untouched; a few tool calls later the hook was live. The docs' "file watcher normally picks up hook changes" is accurate, and "normally" is doing real work — there is a propagation window of seconds |
| 3   | **Unparseable output FAILS CLOSED — it denies the tool call**                    | The model answered in prose: `The tool_name is 'Write', not 'Bash', so the condition ... is not met`. Claude Code surfaced that prose as a hook *error* and stopped the call                                                                                     |
| 4   | The `hookSpecificOutput` shape is **the wrong contract for a prompt hook**       | Prompt hooks are documented to return `{"ok": true\|false, "reason": "..."}`. The probe instructed the model to emit the `command`-hook shape instead, which is very likely why it reasoned in prose rather than complying                                       |
| 5   | The daemon's `command` hook kept working throughout                              | The Bash recovery call was dispatched and allowed by the daemon while the prompt hook was still registered — both ran, neither displaced the other. **Coexistence confirmed empirically**, not just from the docs                                                |

### Finding 3 is the important one, and it is undocumented

The documentation does not state what happens when a prompt hook emits
something unparseable. A `claude-code-guide` agent checking the official pages
confirmed this is a genuine gap. The answer, measured: **it fails closed.**

This inverts the risk profile the plan assumed. `lint_on_edit`'s leniency
("a linter that is not installed never blocks") had set an expectation that
infrastructure failures degrade to *allow*. A prompt hook does the opposite:
when the model does not produce the exact contract, the user's tool call is
**denied**, and the model's stray prose becomes the denial reason shown to
them.

For a *blocking* handler this is arguably the safe direction. For anything on
the hot path it is a availability problem: the failure mode of an LLM that
occasionally explains itself instead of answering is a **blocked session**.

---

## Experiment 2 — The lockout, which was not planned

An unscoped `PreToolUse` hook has **no `matcher`**, so it fires on *every*
tool. When the probe began emitting prose, it started denying `Write` and
`Edit` — the exact two tools needed to remove it from `settings.json`.

Recovery required a `Bash` call (which the hook happened to allow, because for
a `Bash` tool the prompt's condition was directly answerable) running a Python
round-trip over `settings.json` to strip every non-`command` hook. Had the
hook been marginally less lucky in its prose, the session would have had no
tool available to repair itself.

### Consequences for the plan

- **Any native-hook prototype MUST carry a `matcher`** narrow enough that
  `Edit` and `Write` remain reachable. This is a hard safety requirement, not
  a style preference — it is the difference between a bad experiment and an
  unrecoverable session.
- The `matcher` requirement **collides with Layout B**. This repository's
  `PreToolUse` entry has no `matcher` (it matches everything, deliberately, so
  the daemon sees every tool). Adding a matcher to that entry would change the
  daemon's own registration. Adding a *separate* entry with a matcher is
  **Layout A** — which `validate_hook_commands` misreports as a duplicate
  registration.
- So Task 4.0 (fix `validate_hook_commands`) is not merely a
  nice-to-have prerequisite: **Layout A is the only safe layout for a
  prototype**, and Layout A is precisely the one the validator flags today.
  The fix is load-bearing.

---

## Experiment 3 — Correct schema, scoped with a `matcher`

### Setup

Re-run with the two defects from Experiment 1 fixed: the documented
`{"ok": ..., "reason": ...}` contract instead of the `command`-hook shape, and
a `"matcher": "Bash"` so `Edit`/`Write` stayed reachable as an escape hatch.
That matcher forced **Layout A** — a separate `PreToolUse` entry — which is the
layout `validate_hook_commands` misreports.

### Result: it works, and the presentation is the problem

| #   | Finding                                                                                           | Evidence                                                                                                                         |
| --- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| 6   | The documented `{"ok": false, "reason": "..."}` contract **works**                                | The sentinel call was denied carrying exactly `ECHD_NATIVE_PROMPT_HOOK_FIRED`                                                    |
| 7   | `{"ok": true}` allows cleanly                                                                     | A neutral `Bash` call ran untouched                                                                                              |
| 8   | **Layout A functions correctly** — matcher scoping works, and non-`Bash` tools were never touched | `Edit` remained usable throughout and was used to remove the hook afterwards                                                     |
| 9   | **A deliberate, correctly-formatted denial is still labelled a "hook error"**                     | `PreToolUse:Bash hook error: [...]: ECHD_NATIVE_PROMPT_HOOK_FIRED` — the same framing Experiment 1's *malformed* output produced |
| 10  | **The entire prompt is echoed into every denial message**                                         | The full multi-line hook prompt appeared inline in the error, ahead of the reason                                                |

### Findings 9 and 10 are the practical blockers

**A successful policy denial and a broken hook are indistinguishable.** Both
arrive as `hook error` with the prompt echoed and a trailing string. Nothing in
the presentation tells the agent — or the user reading the transcript — whether
the rule fired as designed or the model simply failed to produce JSON. Every
other guard in this project is unambiguous on exactly this point.

**Every denial pays the full prompt in context.** Finding 10 means the cost of
a denial scales with the length of the hook's prompt. A real judge — one with
the nuance the `IDEAS.md` candidates need, e.g. `comment_changelog`'s
"keyed by failure mode vs keyed by release number" test — needs a *long* prompt.
That prompt is then reprinted, in full, on every single denial. Contrast the
daemon, whose deny reasons are authored for the reader and name the fix.

Together these make native `prompt` hooks a poor fit for **user-facing blocking
guidance**, independent of latency or cost. They remain viable where the verdict
is consumed rather than read.

---

## Experiment 4 — Can a native hook's ALLOW override the daemon's DENY?

This is the security question. If a `prompt` hook returning `{"ok": true}`
could override a `command` hook's denial, then adding ANY native hook to this
repository would silently weaken every protection the daemon ships — and the
`deny > defer > ask > allow` ladder's applicability to prompt hooks was, until
now, inference rather than measurement.

### Setup

A `prompt` hook (matcher `Bash`) that denies one sentinel — so its liveness is
observable — and returns `{"ok": true}` for **everything else**. The liveness
probe was denied with `ECHD_HOOK_IS_LIVE`, confirming the hook was loaded.

Then, with that always-allow hook live, a command the daemon blocks:
`echo "git reset --hard"`. Chosen because `destructive_git` matches the literal
string anywhere in the command, and because if the deny were overridden the
command is a harmless `echo` — zero risk either way.

### Result: **the daemon's DENY wins**

| #   | Finding                                                               | Evidence                                                                                                                 |
| --- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| 11  | A native hook's `allow` **cannot** override a `command` hook's `deny` | The daemon's `destructive_git` block fired verbatim, despite the live prompt hook returning `{"ok": true}` for that call |
| 12  | Liveness was independently confirmed in the same configuration        | The sentinel probe was denied with `ECHD_HOOK_IS_LIVE` immediately before                                                |

**So adding a native hook cannot weaken this daemon.** The two mechanisms
compose in the safe direction: any denial, from either, is final. This removes
the largest unquantified risk of native-hook adoption and means a native hook
can be added to a protected event without auditing whether it creates a bypass.

Note the asymmetry this establishes, taken with Finding 3: a native hook can
only ever ADD denials — deliberately, or by failing to produce parseable JSON.
It can never remove one. That is the opposite of the **confirm-the-positive**
shape (`DECISIONS.md` §3c), which exists precisely to *remove* false-positive
blocks — reconfirming that design is unreachable natively and must be
daemon-side.

---

## Aside — does editing `settings.json` require restarting Claude Code?

A reasonable and widely-held belief, and **it is not true in 2.1.241**. Every
hook in Experiments 1, 3 and 4 was written into `.claude/settings.json`
mid-session and fired **without any restart**.

The trap is a propagation window of a few seconds. Experiment 1's first probe
ran completely untouched, which read exactly like "hooks are snapshotted at
session start" — that conclusion was drawn, and was wrong. The next tool call
was denied by the very hook thought not to be loaded.

The documentation agrees: the file watcher "normally picks up hook changes
automatically", and a restart is offered only as the remedy when a change has
not appeared "after a few seconds".

**Practical consequence for anyone testing hooks**: a single negative result
immediately after editing `settings.json` proves nothing. Re-test, or use a
liveness sentinel (as Experiment 4 did) so the loaded/not-loaded question is
answered separately from the behaviour under test.

---

## What this changes in the plan

1. `RESEARCH-...md`'s "adoptable today" framing is confirmed for *mechanism*
   and refuted for *practice*: it works, but not safely without Task 4.0 and a
   matcher.
2. Fail-closed behaviour must be stated wherever the plan discusses reliability.
   The `IDEAS.md` "B-confirm" shape — a filter that can only ever *downgrade* a
   block and falls back to today's behaviour on error — was chosen because a
   model error should not create a new block. Experiment 1 shows a *native*
   hook cannot offer that guarantee: its error mode IS a new block. **This is a
   concrete argument for daemon-side implementation over native hooks for any
   blocking judgement**, which Phase 1 had left as an open trade-off.
3. The undocumented behaviours found here (fail-closed, propagation delay,
   prose-becomes-reason, error-framing, prompt-echo) belong in
   `CLAUDE/ARCHITECTURE.md` if this project ever ships native-hook guidance,
   since no reader can derive any of them from the official docs.
4. **The native-vs-daemon question is now decided for blocking judgements**,
   and Phase 1 had left it open. Findings 3, 9 and 10 together mean a native
   hook cannot deliver a *readable* block: its error mode creates a block, and
   a real block is indistinguishable from an error and costs the whole prompt
   in context. Task 4.1 should therefore prototype a native hook only for an
   **advisory** judgement, and any blocking candidate — `IDEAS.md` #2 and #16,
   both B-confirm — belongs daemon-side where the deny reason can be authored.

---

## Still unmeasured

- **Latency cost per invocation.** Not measured — the lockout in Experiment 2
  ended the run before a controlled timing comparison could be set up, and
  Experiment 3 was kept deliberately short.
- **Token/billing cost per invocation.** Still undocumented and still
  unmeasured; it remains the plan's largest open unknown, and Finding 10
  (the whole prompt echoed per denial) suggests the context cost is not small.
- **The reverse disagreement: a native DENY against a daemon ALLOW.**
  Experiment 4 settled native-allow vs daemon-deny (the deny wins). The mirror
  case is already implied by Experiment 3 — the sentinel denial fired on a
  command the daemon was happy with — so both directions now point the same
  way: any denial is final. Worth one explicit confirmation if a design ever
  depends on it.
- **Whether `validate_hook_commands` warns about Layout A in a live session.**
  Experiment 3 ran Layout A and the warning is a `SessionStart` advisory, so
  this session never saw it. The isolated measurement in `RESEARCH-...md`
  stands; the live confirmation does not exist yet.
