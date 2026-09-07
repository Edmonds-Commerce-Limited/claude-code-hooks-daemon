# Detection channels for "who changed the model?" — Task 2.1 evaluation

Task 2.1 asked one question: can `~/.claude/settings.json` carry the signal the
keystroke tap cannot? The answer is **no, not soundly** — and the evaluation
turned up a channel that is strictly better, because it inverts the question.

## The question the plan has been asking is the harder one

Every mechanism built so far tries to recognise **the human**, so the restore
can be SUPPRESSED. That is a negative inference: "the family changed, and I did
not cause it, therefore a human did". A negative inference needs the set of
non-human causes to be closed and observable, which is why it keeps failing:

- Plan 00316 inferred it from typed keystrokes. The picker's arrow keys carry no
  text, so two of four observed input shapes are unparseable — see
  [REPRODUCTION.md](REPRODUCTION.md).
- The supervisor's `note_model_reading` and the daemon's `downgrade_state.py`
  both infer it from a **high-water mark**: "we were on fable, now we are on
  opus, so this is a downgrade". A human picking opus produces exactly the same
  observation.

The auto-restore's scope, by the owner's ruling, is narrow: counteract the
automated fable SECURITY downgrade **and nothing else**. Stated that way the
positive form is available — detect the AUTOMATIC downgrade and arm on it. A
human change then needs no recognition at all, because it produces no
automatic-downgrade signal. That is what the rest of this document establishes.

## Channel A — `~/.claude/settings.json`

The file is real, it does hold the family, and the daemon already reads it
through an mtime-cached gate (`handlers/status_line/settings_reader.py`), so
the plumbing would be nearly free. Observed here:

```json
{ "model": "opus", "effortLevel": "xhigh",
  "modelSettings": { "claude-fable-5-1": { "effortLevel": "low" }, ... } }
```

Three defects, in increasing order of how badly they bite.

### A.1 No session attribution — and the project already ruled on this

The file is user-level. It carries no session id, so a `/model` in a concurrent
session is indistinguishable from one in the supervised session. This is not a
hypothetical: `_selector_model_matches` is session-scoped *because* an unscoped
wildcard was found disarming the auto-restore for a session the human never
touched, and the comment on it says so. Channel A cannot be scoped at all —
adopting it would re-introduce, at the file layer, the exact defect a previous
plan removed at the latch layer.

It does at least fail in the SAFE direction (a false "the human chose this"
suppresses a restore rather than overriding a human). That is why it is
tolerable as a supplement and not as the primary signal.

### A.2 mtime is ambiguous; only the `model` key's value is usable

The reproduction cited settings.json mtime 07:58:56 as evidence the human's
pick landed. That timestamp is not attributable: `/effort low` was injected at
07:58:56 and effort writes the SAME file (`effortLevel`, plus the per-model
`modelSettings` block). So a file-write watcher would fire on effort changes
too. Only a change in the `model` value can be used, which means fast
A → B → A switching between polls is invisible.

### A.3 The decisive premise is unmeasured

Channel A only discriminates if the automated downgrade does **not** write
`model`. Nothing in the captured evidence establishes that: the reproduction
found `opus` in the file, and both candidate causes (the human's pick, the
automatic bounce) predict `opus`. The product behaviour argues for it — the key
is documented in Claude Code's own confirmation as "your default for **new
sessions**", and silently rewriting a user's persisted default because one
request got downgraded would be a serious bug — but that is an argument, not a
measurement. This project has been burned by exactly that substitution twice
recently: Plan 00341's replay exposed a 25% false-positive shape argument had
missed, and Plan 00343's exposed 7 of 18.

If the premise is false, Channel A reports "the human chose opus" for every
automatic downgrade and the auto-restore becomes dead code — silently, and in
the direction that looks like success.

**Verdict: not sound as the primary signal.**

## Channel B — the transcript's `model_refusal_fallback` record

Claude Code writes the automatic downgrade into the session transcript as a
first-class structured record. The daemon **already parses this shape** in
`handlers/session_start/model_fallback_detector.py`; it was never wired to the
supervisor.

Scanned every transcript under `~/.claude/projects/-workspace/` (25 files).
**25 genuine records**, across 3 sessions, spanning 2026-08-26 to 2026-09-02 —
every one of them the fable security downgrade this plan exists for:

```json
{"originalModel": "claude-fable-5", "fallbackModel": "claude-opus-4-8",
 "apiRefusalCategory": "cyber", "scope": "session",
 "ts": "2026-08-27T09:34:10.341Z"}
```

Uniform across all 25: `claude-fable-5` → `claude-opus-4-8`, category `cyber`,
scope `session`. Two shapes are emitted per event — a `fallback` content block
inside the assistant message, then a standalone `subtype` record 7–90s later
(13 blocks / 12 subtypes in the sample, so they pair but not exactly; a
consumer should treat either as the trigger and dedupe).

Against the three defects above:

|                                  | Channel A (settings.json)      | Channel B (transcript record)                               |
| -------------------------------- | ------------------------------ | ----------------------------------------------------------- |
| Attribution                      | negative inference             | **positive** — names the automatic cause                    |
| Session scope                    | none (user-level file)         | **per-session** (the session's own transcript)              |
| Discriminates human vs automatic | only if A.3 holds — unmeasured | **by construction** — a human `/model` emits no such record |
| Carries the reason               | no                             | `apiRefusalCategory`, `scope`, both model ids               |
| Already parsed here              | reader exists                  | parser exists                                               |

### The consequence for Task 2.2

Arming positively makes the whole keystroke apparatus redundant, not merely
replaceable. The typed-argument parser, the fuzzy stem match, the picker
wildcard, its session key and the restore-steal guard all exist to answer "was
that the human?" — a question that stops being asked. Task 2.2's deletion is
therefore larger than it looked and is the main prize.

### Cost, and the one real constraint

The status-line event does **not** receive `transcript_path` (no status_line
module references it), so the sidecar the supervisor reads cannot be the
producer as it stands. `PostToolUse`, `UserPromptSubmit` and `Stop` all do
receive it. Latency is not a problem: the restore already waits out a quiet
delay before injecting, and a downgraded session emits hook events constantly.

Transcript size is the constraint worth respecting — the largest here is ~100 MB
— so the producer must scan the tail from a recorded offset, not re-read the
file. `model_fallback_detector` reads whole files today because it runs once at
SessionStart; a per-event consumer needs the incremental form.

The supervisor itself should NOT read the transcript. Plan 00317's audit keeps
the PTY host thin, and the daemon already sees `transcript_path` on every hook
event and already owns the parser. Producer in the daemon, consumer in the
supervisor, over the file channel they already share.

## Recommendation

1. Adopt **Channel B** as the arming signal: the restore fires only for a
   downgrade the transcript positively attributes to the safety classifier.
2. Execute Task 2.2's deletion on the strength of it — with the positive signal
   in place, human recognition is not needed, so the keystroke machinery goes
   rather than being maintained alongside.
3. Do **not** adopt Channel A. Its decisive premise is unmeasured and its
   failure mode is silent. It stays recorded here so the option is not
   re-derived from scratch; if Channel B ever proves insufficient, A.3 is the
   measurement to run first.
4. Phase 1 stays as the floor either way: one failed restore, no escalation.
