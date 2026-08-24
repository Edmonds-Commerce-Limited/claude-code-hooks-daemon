# Research: what Claude Code actually offers for LLM-driven hooks

This answers the plan's central factual question: does Claude Code itself
support "LLM driven hooks", and if so, what exactly, and how does it relate to
this daemon?

## Headline finding

**Yes — confirmed via the official docs page (`code.claude.com/docs/en/hooks`,
fetched 2026-08-24) and cross-checked by web search.** Claude Code's hook
system supports **five** hook types, registered per-event in the same `hooks`
JSON structure used today — the `settings.json` family (`~/.claude/`,
`.claude/settings.json`, `.claude/settings.local.json`), managed policy
settings, and skill/subagent frontmatter. There is no `.claude/hooks.json`;
see "Where this repo already half-describes it" below for how that wrong path
got into this repository's own docs:

| `type`     | What runs                                                                     | Default timeout                                                       |
| ---------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `command`  | A shell command (what this daemon uses exclusively today)                     | 600s (this project's convention; Claude Code's own ceiling is higher) |
| `http`     | A POST request to a configured URL                                            | not stated                                                            |
| `mcp_tool` | A tool call on an already-connected MCP server                                | not stated                                                            |
| `prompt`   | A single-turn LLM call over the hook's JSON input                             | **30s**                                                               |
| `agent`    | A subagent with tool access (Read/Grep/Glob) that can explore before deciding | **60s**                                                               |

So the user's instinct was correct: Claude Code has native, first-class
support for a hook whose "handler" is an LLM call rather than a script. This
is a **separate mechanism from this daemon** — it is evaluated by Claude Code
itself, not dispatched through `FrontController`, and does not go through
`Handler`/`HookResult`/the priority system/the config YAML/the QA or
acceptance-test machinery this project has built. A `prompt` or `agent` hook
is configured as JSON sitting alongside a `command` hook — and in THIS project
it must only ever be alongside. Replacing the daemon's wrapper with a
`prompt`/`agent` entry is not a supported swap: `reconcile_settings_hooks` is
additive per **event**, not per entry, so once an event carries any hook the
daemon's self-heal will not restore the wrapper it no longer sees, and every
`command`-dispatched handler on that event goes silently dark.

### `prompt` type — schema and behaviour

```json
{
  "type": "prompt",
  "prompt": "Should this Bash command be allowed? $ARGUMENTS",
  "model": "optional, defaults to a fast model",
  "timeout": 30
}
```

- `$ARGUMENTS` is a placeholder substituted with the hook's JSON input
  (escape with `\$` for a literal dollar sign).
- `model` is optional; unspecified default is described only as "a fast
  model" — no further guarantee.
- Output format matches command hooks: the model's response is expected to be
  the same JSON decision-control shape (`hookSpecificOutput.permissionDecision`
  etc. for events that support it).
- No tool access — this is a single LLM turn over the input JSON only. It
  cannot read a file to check something the input didn't already contain.

### `agent` type — schema and behaviour

```json
{
  "type": "agent",
  "prompt": "Verify all test files have corresponding implementation files",
  "model": "optional, defaults to a fast model",
  "timeout": 60
}
```

- Spawns a subagent with tool access — the sources found say Read, Grep, Glob
  (i.e. exploration tools, not Edit/Write/Bash), so it can inspect files
  before answering, unlike `prompt`. **The absence of Bash is a real
  structural limit**: an `agent` hook cannot itself run `git diff --cached`,
  or any other shell command, to gather context beyond what the hook's own
  JSON input already contains or what Read/Grep/Glob can see on disk. Any
  candidate use-case whose judgement depends on invoking a subprocess (e.g.
  reading staged git state, running a linter) is not reachable by this
  mechanism without that context first landing in the hook's input JSON some
  other way.
- **Explicitly marked "experimental and may change"** in the official docs.
  This is a direct caution against relying on it for anything the project
  needs to stay stable across Claude Code versions.
- Longer default timeout (60s vs 30s) reflecting the extra tool-call round
  trips.

### Hook coexistence and combination (partially resolved by a follow-up fetch)

A third, targeted fetch answered the coexistence question directly:

> "All matching hooks run in parallel. If you define the same handler in
> more than one settings file, it runs once. A plugin's or skill's copy of
> the same handler stays separate."

**So the answer to "can a native `prompt`/`agent` hook coexist with this
daemon's `command` hook on the same event" is confirmed YES — both run, in
parallel.** This matters because every event this project cares about
already has a daemon `command` hook registered, so coexistence was not
optional for any design under consideration here.

What is **not** resolved: exactly how differing decisions from
parallel-running hooks of *different types* combine. The only precedence
statement found anywhere on the page is general and not type-specific:
"exit 2... blocks whether or not you print JSON: even a JSON
`permissionDecision` of `allow` can't override it" (command-hook exit-code
behaviour), and a separately-sourced general rule that multiple `PreToolUse`
hooks disagreeing resolve `deny > defer > ask > allow`. Nothing found states
whether a `prompt`/`agent` hook's JSON decision is folded into that same
precedence ladder identically to a `command` hook's, or whether one type's
slow response can delay another's. Reasonable to *assume* the same ladder
applies (decisions are decisions, regardless of how they were produced), but
this is an assumption, not a confirmed fact.

### Model determinism (partially resolved, and the news is not reassuring)

For `prompt` hooks, the complete documented statement of default model
behaviour is:

> "`model` — no — Model to use for evaluation. Defaults to a fast model"

No model name, no tier, no version, no statement about whether the default
can silently change between Claude Code releases. `agent` hooks' field table
does not list a `model` field at all in the excerpt fetched, meaning it may
inherit the same undocumented default or may not be configurable per-hook —
neither could be confirmed.

**This is a real reproducibility risk, not a pedantic caveat**, for a
project that pins exact `expected_decision` values in acceptance tests and
runs a release gate that treats "all tests still pass" as load-bearing: a
"fast model" default that changes underneath the project between Claude Code
versions means a native `prompt`/`agent` hook's behaviour can drift with no
corresponding entry in *this* project's changelog, CI, or QA — because none
of that tooling has visibility into it (see "Where this repo already
half-describes it" below). A daemon-side handler calling a model directly
does not have this problem in the same way, because the model choice is a
line in *this* project's own code, reviewed and changed deliberately like
anything else.

### Settled by a direct re-fetch of the docs page

Four of the five gaps below were closed by fetching
`code.claude.com/docs/en/hooks` again with the questions asked directly.
Recorded here rather than edited into the text above, so the difference
between what the first pass found and what a targeted second pass found stays
visible.

- **There is no `.claude/hooks.json`.** The page lists `~/.claude/settings.json`,
  `.claude/settings.json`, `.claude/settings.local.json`, managed policy
  settings, skill frontmatter and subagent frontmatter — and a PLUGIN
  `hooks/hooks.json`, which is almost certainly where this repo's incorrect
  `.claude/hooks.json` came from. `CLAUDE/ARCHITECTURE.md` and
  `CLAUDE/HANDLER_DEVELOPMENT.md` have been corrected.

- **Coexistence is confirmed and better than assumed**: "All matching hooks
  run in parallel." So a native `prompt`/`agent` hook and this daemon's
  `command` hook both run, concurrently — a slow LLM hook does NOT serialise
  behind the daemon's dispatch. Also: "If you define the same handler in more
  than one settings file, it runs once", and hook entries MERGE across
  settings levels rather than replacing each other.

  **But parallel is not free, and it would be easy to misread it that way.**
  Parallelism means the hooks do not COMPOUND — the cost is the slowest hook,
  not the sum — while the tool call still blocks on that slowest one. So
  adding a `prompt` hook to `PreToolUse` still turns a ~45 ms round trip into
  a multi-second one for that event. The finding removes the fear that a
  native hook would degrade the DAEMON's latency; it does not weaken the
  event-selection argument in `DECISIONS.md` at all.

- **No per-event restriction is stated.** For skill/subagent frontmatter the
  page says "All hook events are supported". No allowlist or denylist for
  `prompt`/`agent` appears anywhere.

- **Timeouts are fully specified**: 600s for `command`/`http`/`mcp_tool`
  (lowered to 30s for `UserPromptSubmit` and 10s for `MessageDisplay`), 30s
  for `prompt`, 60s for `agent`.

- **`agent` is still experimental**, verbatim: "Agent hooks are experimental
  and may change."

**Still genuinely unanswered, and it is the one that matters most for this
project**: cost, billing and rate-limit consumption for `prompt`/`agent`
hooks is *not stated on the page at all*. A design that fires a model call per
event cannot be costed from the documentation, so any proposal must treat
per-invocation cost as an unknown to be measured, not estimated. The
introduction version is likewise unannotated, so no minimum Claude Code
version can be asserted.

Note also that no precedence rule is given for hooks that DISAGREE — the page
says only that they all run in parallel. So the `deny > defer > ask > allow`
ladder cited above remains the general multi-hook rule, and whether a
`prompt` hook's verdict folds into it identically is inference, not
documentation.

### What still could not be settled from documentation

1. **No stated introduction version** for `prompt`/`agent` hooks (unlike
   other features on the same page, which do carry version annotations).
2. **No explicit per-event allowlist/denylist.** Every example shown is
   PreToolUse/PostToolUse-shaped; whether `SessionStart`, `Stop`, or any of
   the other ~30 events can carry a `prompt`/`agent` hook at all was not
   confirmed either way.
3. **No documented interaction with permission modes**
   (`bypassPermissions`/YOLO mode).
4. **No cost/billing statement** — that a `prompt`/`agent` hook consumes an
   API call, and therefore budget/rate-limit headroom, had to be inferred
   from the timeouts and mechanism, not confirmed from the source text.
5. **The precise cross-type decision-combination rule** (see above) —
   plausible by extension of the general precedence rule, not confirmed.

**These five gaps are exactly the kind of question the `claude-code-guide`
agent type (visible in this session's team roster) is the authority on, and
which I was told I cannot spawn myself.** If settling them precisely matters
before committing to a design, the questions to put to it are:

- Which Claude Code CLI version introduced `type: prompt` / `type: agent`
  hooks, and is there a `settings.json`/`hooks.json` schema version gate?
- Which hook events (of the ~30) actually accept a `prompt`/`agent` hook —
  is there any event-type restriction at all?
- Does a `prompt`/`agent` hook's JSON decision fold into the same
  `deny > defer > ask > allow` precedence ladder as a `command` hook's,
  when both are registered on the same event and disagree?
- Does invoking a `prompt`/`agent` hook consume the user's normal API
  usage/rate-limit budget the same as an assistant turn, and is there any
  way to scope or pin which model/tier it uses, for reproducibility?
- Is `type: agent`'s "experimental and may change" warning still current, or
  has it stabilised? Does `agent` accept a `model` field at all?

## Where this repo already half-describes this mechanism

`CLAUDE/ARCHITECTURE.md` (§"Use Claude Code Native Agent Hooks For (Complex
Evaluation)") already draws exactly this line — daemon handlers for
deterministic pattern matching, native agent hooks (now correctly pointing
at `.claude/settings.json`, see below) for anything needing multi-turn
reasoning or file inspection — and gives a worked example (`"type": "agent"`,
a `prompt` field, blocking `git tag` against `RELEASING.md`). Its JSON shape
is consistent with the real, documented schema above.

**Historical note**: an earlier draft of this section treated the
`.claude/hooks.json` filename and a `hook_registration_checker` policy
collision as open problems this plan would have to resolve. Neither was —
the filename was a doc-truth bug (see "Settled by a direct re-fetch of the
docs page" above: hooks live in the `settings.json` family, not a bespoke
`.claude/hooks.json`; both `ARCHITECTURE.md` and `HANDLER_DEVELOPMENT.md`
are now corrected), and the registration-checker collision does not exist
at the code level, below.

**`detect_legacy_hook_commands` does NOT flag a native hook.**
(`utils/hook_registration.py:149`) It reads `command_entry.get("command", "")`
and `continue`s on an empty value; a `type: prompt`/`type: agent` entry has
no `command` key at all, so it is skipped and never reported. And
`reconcile_settings_hooks` is additive per EVENT (`if json_key in new_hooks: continue`), with a docstring stating that client-added custom entries are
left untouched — so a native hook added alongside survives auto-repair.

**But `hook_registration_checker` runs a SECOND validator, and that one DOES
flag a native hook in two of the three ways you might add it.** The handler
calls `validate_hook_commands` as well
(`handlers/session_start/hook_registration_checker.py:186`). Measured by
running both validators directly against each layout, not by reading the code:

| Layout for adding a native hook to an event                                     | `validate_hook_commands`                                                        |
| ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| **A** — as a separate matcher entry in the event array                          | ❌ `PreToolUse has 2 hook entries (expected 1) — likely duplicate registration` |
| **B** — appended AFTER the daemon command, inside the same entry's `hooks` list | ✅ no issues                                                                    |
| **C** — placed BEFORE the daemon command in that same list                      | ❌ `PreToolUse command does not end with /.claude/hooks/pre-tool-use: got ''`   |

Two mechanisms cause this: `validate_hook_commands` treats `len(event_hooks) > 1`
as a duplicate registration (Layout A), and it only ever inspects
`inner_hooks[0]`, so a native entry sitting first yields an empty `command`
that fails the `endswith` suffix check (Layout C).

**So Layout B is the only clean way to add a native hook to an event this
daemon already registers**, and any Phase 4 prototype must use it. This does
not block adoption — the checker is advisory and never blocks — but it would
emit a misleading session-start warning every session, which is exactly the
kind of false alarm that trains people to ignore a real one.

**This is also a latent defect in `validate_hook_commands` itself**, not just a
constraint to work around: a legitimate native hook is not a "duplicate
registration", and the `inner_hooks[0]`-only inspection means the validator
cannot see a daemon wrapper that is present but not first. It is latent rather
than live because no native hook exists in this repository yet. Fixing it —
scan all of `inner_hooks` for the daemon command rather than assuming index 0,
and count only `type: command` entries toward the duplicate check — is a
prerequisite for Phase 4, not a follow-up to it.

What IS true is that the handler's `get_claude_md()` guidance says "Every
registered command must end with `/.claude/hooks/{event}`. Anything else...
is a legacy setup", which READS as forbidding what the code permits. That is
a wording fix, not an exemption that needs implementing.

The real footgun sits next door: because reconcile is additive per EVENT and
not per ENTRY, replacing the daemon wrapper with a native hook means the
wrapper is never restored — the key exists, so it is skipped. Add alongside,
never replace.

**Net effect: there is no architectural tension to resolve.** Native
`prompt`/`agent` hooks are adoptable in this project TODAY, alongside the
daemon's own hooks, with zero code changes. What remains is a one-line
documentation fix to `hook_registration_checker.get_claude_md()` (scope the
"every command must route through the daemon wrapper" rule explicitly to
`type: command` entries, so its wording stops reading as forbidding what
the code already permits) — tracked as a task in `PLAN.md` — and remembering
the additive-per-event footgun above when actually adding one.

## The two fundamentally different mechanisms on the table

|                                                                            | Native Claude Code `prompt`/`agent` hook                                                                       | A daemon `Handler` that itself calls a model                                                                                   |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Who calls the LLM                                                          | Claude Code, natively                                                                                          | This project's own Python code (subprocess `claude -p ...` or the Anthropic API directly)                                      |
| Goes through `FrontController`/`Handler`/`HookResult`?                     | **No** — entirely outside this daemon's dispatch, config, priority and testing machinery                       | **Yes** — same `Handler` ABC, same `HookResult`/`AdvisoryResult` contract, same config YAML, same acceptance-test framework    |
| Implementation cost in this repo                                           | ~Zero (it's Claude Code's own feature — just JSON config)                                                      | New infrastructure: a way to shell out to a model, timeout/error handling, mocking for tests, cost/rate-limit accounting       |
| Engineering discipline (TDD, 95% coverage, deterministic acceptance tests) | **Bypassed entirely** — it's a prompt string in JSON, not testable the way this codebase tests everything else | Preserved — but testing a handler whose "correctness" depends on model output is a genuinely harder problem (see DECISIONS.md) |
| Config/observability                                                       | Lives in `settings.json`, invisible to `hooks-daemon status`, `verdict_log`, `plan-qa`, etc.                   | Fully observable via existing daemon tooling (verdict log, generate-docs, generate-playbook)                                   |
| Portability across client projects                                         | Whatever Claude Code ships, works everywhere Claude Code runs — no daemon dependency                           | Only works where this daemon is installed and configured                                                                       |

Neither option is free of the latency problem — see `DECISIONS.md` — because
both ultimately make a real LLM call somewhere in or adjacent to the hook
path. The choice between them is really a choice about **where the AI
judgement lives relative to this project's own engineering guarantees**, not
a way to dodge the latency question.

## Prior art in this codebase

None. `grep` across `src/claude_code_hooks_daemon/` for any invocation of the
`claude` CLI, `subprocess` calls naming it, or `anthropic`/`Anthropic(` usage
returns zero hits outside this plan's own research. Nothing in this daemon
has ever made a model call. Any handler doing so would be new infrastructure,
not an extension of an existing pattern — except for the nitpick pseudo-event
mechanism described in `DECISIONS.md`, which is architecturally the closest
existing thing to what an AI-assisted handler would need.
