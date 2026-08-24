# Research: what Claude Code actually offers for LLM-driven hooks

This answers the plan's central factual question: does Claude Code itself
support "LLM driven hooks", and if so, what exactly, and how does it relate to
this daemon?

## Headline finding

**Yes — confirmed via the official docs page (`code.claude.com/docs/en/hooks`,
fetched 2026-08-24) and cross-checked by web search.** Claude Code's hook
system supports **five** hook types, registered per-event in the same `hooks`
JSON structure used today (this project's own `.claude/settings.json`, or a
project's `.claude/hooks.json` — see "Where this repo already half-describes
it" below):

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
is configured as JSON sitting alongside (or instead of) a `command` hook.

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
deterministic pattern matching, "Native Agent Hooks" via `.claude/hooks.json`
for anything needing multi-turn reasoning or file inspection — and gives a
worked example (`"type": "agent"`, a `prompt` field, blocking `git tag`
against `RELEASING.md`). Its JSON shape is consistent with the real,
documented schema above (it just omits the `model`/`timeout` fields).

**But this is pure aspiration, never implemented in this repository:**

- `.claude/hooks.json` does not exist anywhere in this checkout (`find`
  confirmed zero matches).

- `"type": "agent"` and `hooks.json` appear in exactly two files in the whole
  tree: `ARCHITECTURE.md` itself and `HANDLER_DEVELOPMENT.md` — i.e. only in
  the documentation that describes the pattern, never in a config file that
  uses it.

- The project's own `hook_registration_checker` handler (SessionStart,
  advisory, self-healing) actively enforces the *opposite* policy today:
  "All hooks live in `settings.json`... Hook commands must invoke the daemon
  wrapper... Every registered command must end with `/.claude/hooks/{event}`.
  Anything else... is a legacy setup that bypasses the daemon entirely." A
  native `prompt`/`agent` hook registered in `settings.json` (there is no
  separate `hooks.json` actually read by Claude Code as far as this
  repository's own tooling assumes — `hooks.json` may be an aspirational name
  from the ARCHITECTURE.md author, not a distinct file Claude Code treats
  specially versus `settings.json`'s own `hooks` block) would presently be
  flagged by this checker as a "legacy-style command" bypassing the daemon,
  unless the handler were taught an exemption for `type: prompt`/`type: agent` entries.

  This is a genuine, concrete tension the plan must resolve, not paper over:
  **adopting native prompt/agent hooks anywhere in this project requires
  either changing `hook_registration_checker`'s policy or deliberately
  keeping native hooks and daemon hooks in two clearly-separated,
  non-conflicting lanes.**

## The two fundamentally different mechanisms on the table

|                                                                            | Native Claude Code `prompt`/`agent` hook                                                                       | A daemon `Handler` that itself calls a model                                                                                   |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Who calls the LLM                                                          | Claude Code, natively                                                                                          | This project's own Python code (subprocess `claude -p ...` or the Anthropic API directly)                                      |
| Goes through `FrontController`/`Handler`/`HookResult`?                     | **No** — entirely outside this daemon's dispatch, config, priority and testing machinery                       | **Yes** — same `Handler` ABC, same `HookResult`/`AdvisoryResult` contract, same config YAML, same acceptance-test framework    |
| Implementation cost in this repo                                           | ~Zero (it's Claude Code's own feature — just JSON config)                                                      | New infrastructure: a way to shell out to a model, timeout/error handling, mocking for tests, cost/rate-limit accounting       |
| Engineering discipline (TDD, 95% coverage, deterministic acceptance tests) | **Bypassed entirely** — it's a prompt string in JSON, not testable the way this codebase tests everything else | Preserved — but testing a handler whose "correctness" depends on model output is a genuinely harder problem (see DECISIONS.md) |
| Config/observability                                                       | Lives in `settings.json`/`hooks.json`, invisible to `hooks-daemon status`, `verdict_log`, `plan-qa`, etc.      | Fully observable via existing daemon tooling (verdict log, generate-docs, generate-playbook)                                   |
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
