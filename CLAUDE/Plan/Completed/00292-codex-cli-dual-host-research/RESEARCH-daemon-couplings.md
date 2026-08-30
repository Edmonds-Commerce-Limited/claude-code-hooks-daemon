# Research: This Repository's Couplings to Claude Code

Plan 00292. Research-only — no code changes. All findings are from reading
`/workspace` source at HEAD (commit context: `Plan 00283: Complete —
standing-auth cadence + supervisor-typed channel`, plus the in-flight Plan
00290 socket-relay work). Every claim below cites the exact file(s) read.

## Method

Read (per the task brief):

- `src/claude_code_hooks_daemon/constants/events.py` — wired event catalogue
- `src/claude_code_hooks_daemon/core/event.py`, `core/hook_result.py` — hook
  input pydantic models and the verdict/response wire contract
- `src/claude_code_hooks_daemon/core/front_controller.py` — dispatch entry
  point (stdin→stdout JSON loop)
- `src/claude_code_hooks_daemon/install/client_owned_assets.py`,
  `install/forwarder_generator.py`, and `install.py` (`create_settings_json`,
  `create_forwarder_script`) — settings.json registration + forwarder deploy
- `.claude/init.sh`, `.claude/hooks/pre-tool-use` — the deployed forwarder
  shell layer
- `src/claude_code_hooks_daemon/handlers/status_line/*` (settings_reader.py,
  model_context.py) — status-line-specific host assumptions
- `src/claude_code_hooks_daemon/core/transcript_reader.py`,
  `utils/session_helpers.py`, `handlers/session_start/*`,
  `utils/permission_mode.py` — transcript-path / session-field assumptions
- `CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md` —
  the per-event socket transport design (host-agnostic byte pump)

Ranking scale: **easy** (config/constant swap), **medium** (an adapter layer
translates one host's shape to the daemon's existing internal model),
**hard** (the daemon's internal model itself encodes a Claude-Code-specific
concept that a generic adapter would have to either fake or extend),
**fundamental** (the coupling *is* the integration point — there is no
"daemon" without something upstream shaped exactly like this).

## Inventory

### 1. The event catalogue (`constants/events.py`) — **hard**

`EventIDMeta` is a fixed enumeration of Claude-Code-specific hook names
(`PreToolUse`, `PostToolUse`, `PermissionRequest`, `WorktreeCreate`,
`ElicitationResult`, `TeammateIdle`, …), each annotated with `can_block`,
`raw_stdout`, and `wired` flags that describe *how Claude Code's hook
contract lets that specific event refuse or emit raw text*
(`src/claude_code_hooks_daemon/constants/events.py:23-61`, `75-383`). The
module docstring cites `https://code.claude.com/docs/en/hooks` as the source
of truth for this catalogue (`events.py:185`).

This is not a generic "event bus" — it is a literal transcription of Claude
Code's hook taxonomy, including host-specific quirks with no general
analogue (e.g. `WORKTREE_CREATE.raw_stdout=True` because Claude Code parses
that hook's *raw stdout* as a filesystem path rather than JSON, `events.py:
336-346`; `TEAMMATE_IDLE`/`TASK_COMPLETED` express refusal via
`continue: false` rather than `decision: block`, `hook_result.py:76`).

A second host (e.g. a hypothetical `codex-cli` with a different event
taxonomy) would either need: (a) a parallel `EventIDMeta` table for its own
events, with the wire-format code in `hook_result.py` (see §3) extended
per-event, or (b) a normalization layer that maps the second host's native
events onto this taxonomy where a semantic match exists, and drops/no-ops
the rest. Neither is "hard" in the sense of algorithmically difficult, but it
does mean the catalogue cannot simply be parameterised — it has to be
duplicated or generalised into a genuinely host-agnostic schema, and 28 of
31 wired events (`events.py:422-457`, `EventKey` literal) have Claude-Code
protocol quirks baked into their response formatting (§3), so the abstraction
has to happen at the response layer too, not just the naming layer.

### 2. `HookInput` / `HookEvent` pydantic models (`core/event.py`) — **medium**

`HookInput` (`core/event.py:102-127`) models the exact JSON shape Claude Code
sends per hook call: `toolName`, `toolInput`, `sessionId`, `transcriptPath`,
`message`, `prompt` — all camelCase aliases matching Claude Code's wire
format (`populate_by_name=True`, `extra="allow"`). `ToolInput`
(`core/event.py:85-99`) mirrors Claude Code's specific tool vocabulary
(`command`, `file_path`, `pattern`, `content`, `old_string`, `new_string` —
i.e. Bash/Read/Write/Edit/Glob/Grep field names).

This is **medium**, not hard, because the model is permissive (`extra="allow"`,
frozen dataclass-like structure) and the daemon's handler code mostly reads
through named accessors (`get_command()`, `get_file_path()`,
`is_bash_tool()` — `core/event.py:157-191`) rather than assuming the full
Claude Code tool set. An adapter for a different host's tool-call shape
could populate the same `HookInput`/`ToolInput` fields (or a superset via
`extra="allow"`) as long as the *concepts* — "a tool was called with this
command/file_path", "there is a session id", "there is a transcript path" —
exist on the other host. The genuine friction is `transcript_path`: Claude
Code writes a JSONL transcript file on disk at a host-managed path and hands
the path (not the content) to hooks; a host that keeps conversation state
purely in-process (no JSONL transcript file) would need a shim that
materializes an equivalent readable artifact, or the daemon's `transcript_
reader.py` consumers must be reworked to accept an injected stream. See §7.

### 3. The verdict/response wire contract (`core/hook_result.py`) — **hard**

This is the single largest concentration of host-specific knowledge in the
codebase. `HookResult.to_json()` (`hook_result.py:307-339`) is described in
its own docstring as "the single choke point" that "enforces the response
contract" — and that contract is a *per-event*, *undocumented-in-one-place*,
reverse-engineered mapping of Claude Code's actual accepted JSON shapes:

- `PreToolUse`: `hookSpecificOutput.permissionDecision` ∈
  {allow,deny,ask,defer} + `permissionDecisionReason` + optional
  `updatedInput` (`hook_result.py:607-638`)
- `PostToolUse`: top-level `decision: "block"` + `hookSpecificOutput.
  additionalContext` (`hook_result.py:640-666`)
- `Stop`/`SubagentStop`: top-level `decision: "block"` + `reason` (required
  when blocking) + a **documented Claude-Code-specific infinite-loop bug**
  workaround keyed on `stop_hook_active` (`hook_result.py:668-719`, citing
  "Sev-1 shipped in v3.31.0" — i.e. a literal Claude Code release version)
- `PermissionRequest`: nested `decision.behavior` object, with a
  "DUAL-CHANNEL" emission (`decision.message` + `additionalContext`) because
  live verification of which channel Claude Code actually renders is
  incomplete (`hook_result.py:721-760`)
- `Status` (status line): plain `{"text": ...}`, not JSON-decision shaped at
  all, with column-aware wrapping keyed on `terminal_columns` that Claude
  Code forwards from its own terminal width (`hook_result.py:529-557`,
  §5 below)
- `WorktreeCreate`: raw path on stdout, not JSON at all
  (`hook_result.py:559-564`, `_WORKTREE_PATH_KEY`)
- A closed set of other per-event shapes: `_TOP_LEVEL_BLOCK_EXTRA_EVENTS`,
  `_HSO_CONTEXT_EXTRA_EVENTS`, `_CONTINUE_FALSE_EVENTS`
  (`hook_result.py:58-76`)

Crucially, `REFUSAL_CAPABLE_EVENTS` (`hook_result.py:99-134`) documents that
some events (e.g. `Status`) **cannot express a refusal on the wire at all**
regardless of what a handler decides — this is a hard constraint of Claude
Code's hook protocol, not a daemon design choice, and the daemon's own code
comments call out that a schema-valid-but-refusal-dropping response is
"unreachable in this repository... but NOT unreachable for a client" —
i.e. this is inherent protocol shape, independently confirmed by handler
authors writing project-level handlers against the same host.

**Why hard, not fundamental**: the *internal* `Decision` enum
(ALLOW/DENY/ASK/CONTINUE/DEFER, `hook_result.py:18-28`) and `HookResult`
dataclass (decision/reason/context/guidance) are host-agnostic — they are a
reasonable general vocabulary for "a policy engine's verdict on an event."
The hardness is entirely in `_build_wire_response` / `_format_*_response`
(`hook_result.py:497-946`): ~450 lines of Claude-Code-specific JSON shape
knowledge that a second host's adapter would have to *fully replace* with
its own per-event serialization, because none of it generalizes (a
different host is exceedingly unlikely to share the exact same
`hookSpecificOutput.permissionDecision` nesting, the `continue: false`
convention, or the raw-stdout-as-path convention for its own "create a
worktree" analogue). A dual-host design would plausibly keep `HookResult`
as the internal representation and add a second `to_json`-equivalent
serializer per host, gated on which host is talking.

### 4. Front controller `run()` I/O loop (`core/front_controller.py`) — **easy**

`FrontController.run()` (`front_controller.py:171-213`) reads one JSON object
from stdin, dispatches, writes one JSON object to stdout, `sys.exit(0)`. This
is a generic request/response shape with only two Claude-Code-specific
touches: (1) it reads `stop_hook_active`/`stopHookActive` out of the raw
input to detect Claude Code's Stop-loop re-entry (`front_controller.py:
204-206`, feeding the workaround in §3), and (2) it forwards
`hook_input.get("terminal_columns")` to `to_json` for status-line wrapping
(`front_controller.py:210`, §5). Both are single-field reads, trivially
made conditional/optional for a host that does not send them. The dispatch
loop itself (`dispatch()`, `front_controller.py:66-147`) — priority-sorted
handler chain, terminal vs. non-terminal handlers, context accumulation,
exception→`HookResult.error()` fail-open — is entirely generic policy-engine
machinery with no host assumptions at all.

### 5. Settings.json registration + forwarder deployment (`install.py`,
`install/client_owned_assets.py`) — **fundamental** (registration mechanism)
/ **easy** (per-event mapping data)

`create_settings_json()` (`install.py:678-716`) writes `.claude/settings.
json` with a top-level `hooks` object keyed by Claude Code's own
PascalCase event names, each mapping to `[{"hooks": [{"type": "command",
"command": "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/<bash-key>"}]}]` —
this exact nested-array-of-objects shape, the `$CLAUDE_PROJECT_DIR`
environment variable, and the `statusLine` top-level key
(`install.py:713-716`) are all **Claude Code's own settings-file schema**,
not the daemon's invention. `_DAEMON_FORWARDER_HOOKS`
(`install.py:311-345`) — the bash-key→JSON-key table — is comparatively
easy to swap (it is exactly the same catalogue as `events.py`, duplicated
per the module's own comment at `install.py:308-310`: "Single source of
truth for install.py... Mirrors the daemon's own `.claude/hooks/` directory
and EventID wired catalogue").

The **fundamental** part is that the entire deployment model — a settings
file the *host* reads at session start to decide which external commands to
invoke per lifecycle event, passing JSON on stdin and reading JSON from
stdout — is Claude Code's actual extension mechanism. Any second host needs
its own equivalent registration surface (its own settings/manifest format,
its own env vars for project root, its own stdin/stdout or other IPC
convention) before forwarders can be deployed at all; there is no
generalizing this away, only *adding* a second registration path alongside
it. `client_owned_assets.py` (`install/client_owned_assets.py:1-40`,
124-205) documents the parallel problem this creates for tooling: files
deployed into `.claude/hooks/`, `.claude/ccy/`, `.claude/skills/hooks-
daemon/`, `.claude/agents/` are all placed at paths **Claude Code itself
defines the discovery contract for** ("Claude Code discovers skills under
`.claude/skills/`", `client_owned_assets.py:149-150`; "Claude Code
discovers sub-agents only under `.claude/agents/`", `client_owned_assets.py:
170-172`) — a second host with a different plugin-discovery convention
would need its own deploy targets for the semantically-equivalent assets
(if it has skills/sub-agents/status-line concepts at all).

### 6. `.claude/init.sh` + forwarder scripts — **medium**

`init.sh` (`.claude/init.sh`, 1269 lines) is largely host-agnostic Unix
socket plumbing (daemon lifecycle: `is_daemon_running`, `start_daemon`,
`ensure_daemon`, hostname-suffix socket path computation) that has nothing
to do with Claude Code specifically — it would work unmodified as the
transport layer for any host that can exec a bash script per event and pipe
JSON on stdin/stdout. The Claude-Code-specific surface is narrower and
concentrated in a few places:

- The **Status-line special case**: `send_request_stdin` injects `hook_
  event_name: 'Status'` and forwards `$COLUMNS`/`$LINES` from *this
  wrapper process's own environment* because "the daemon is a separate
  long-running process and never inherits COLUMNS/LINES" from Claude
  Code's terminal (`init.sh:1121-1132`) — this assumes Claude Code invokes
  the status-line command as a child of its own interactive terminal
  session; a host with no interactive terminal (e.g. a headless CLI agent)
  has no COLUMNS/LINES to forward and the wrapping logic degrades to
  single-line join (already handled gracefully, `hook_result.py:551-557`).
- `forward_stop_event()` (`init.sh:1223-1259`) exists **purely** to work
  around a specific Claude Code regression: "Claude Code v2.1.114 silently
  demotes JSON-via-stdout `{"decision":"block"}`... breaking the
  auto_continue_stop contract" and requires translating a JSON verdict into
  **process exit code 2** because "The daemon CANNOT control the hook
  subprocess exit code from inside its own Python process — only the bash
  wrapper that Claude Code spawns can set it" (`init.sh:1191-1201`). This is
  the single most host-specific piece of transport logic in the repo: it
  exists to satisfy one host's particular (and versioned/buggy) hook-exit-
  code contract, not a general protocol need.
- `_get_hostname_suffix()`'s comment about needing to "agree with the
  Python side" (`init.sh:322-330`) is host-agnostic (it's about the
  bash/Python split within the daemon itself, not about Claude Code).

An adapter for a second host would likely reuse `ensure_daemon`/socket
plumbing wholesale and write a **new** forwarder-script family per host,
swapping only: the stdin/stdout JSON envelope details, the exit-code
convention (if any), and the terminal-size-forwarding behavior for a status
surface (if the host has one).

### 7. Transcript-path assumptions (`core/transcript_reader.py`,
`session_start` handlers) — **medium/hard**, mixed

`HookInput.transcript_path` (`core/event.py:114`) carries a filesystem path
that Claude Code itself writes and maintains — a JSONL file of the running
conversation. `TranscriptReader` (`core/transcript_reader.py:1-33`) is a
"lazy, cached parser that provides read-only access to conversation history"
reading that JSONL file from disk, including a **bounded tail-read** window
(`_DEFAULT_TAIL_BYTES = 1_048_576`, `transcript_reader.py:29-33`) explicitly
sized for "the recent-conversation accessors the Stop handlers need." This
JSONL-on-disk convention, and the fact that hooks receive only a *path* (not
inline content) to it, is Claude Code's storage model, not a daemon
invention — grep confirmed additional consumers of `transcript_path`/
`transcriptPath` across `daemon/payload_capture.py`, `core/input_schemas.py`,
`handlers/session_start/model_fallback_detector.py`,
`handlers/stop/auto_continue_stop.py`, `utils/session_helpers.py`,
`utils/stop_hook_helpers.py`, `constants/protocol.py`,
`pseudo_events/nitpick.py`, and
`handlers/user_prompt_submit/idle_housekeeping_advisor.py` — i.e. this is a
load-bearing assumption threaded through several subsystems, not a single
call site.

This ranks **medium** for the mechanical part (any host that also persists
a readable transcript file — JSONL or otherwise — and hands hooks a path to
it can satisfy the same interface with a parser swap) but **hard** for hosts
that do *not* externalize conversation history to a hook-visible artifact at
all (e.g. state kept only in the host process's memory) — those would need
either a new IPC channel carrying transcript content directly, or the host
would need to be modified to write an equivalent artifact, which is outside
the daemon's control entirely.

### 8. Status-line handlers (`handlers/status_line/*`) — **hard**, host-specific feature

The status line as a *feature* (a persistent one-line summary rendered in
the host's own terminal chrome, refreshed on a host-driven cadence) is a
Claude-Code-specific UI surface, not a general hook concept — confirmed by
`events.py`'s own note that `StatusLine`/`raw_stdout=True` "ships
status_line handlers that render it (never a bare `{}` passthrough)"
(`events.py:172-175`) and by `hook_result.py`'s dedicated `Status`
branch in `_build_wire_response` (`hook_result.py:529-557`) which is
structurally unlike every other event's response. Within the handler set:

- `settings_reader.py` (`handlers/status_line/settings_reader.py:1-63`)
  reads **`~/.claude/settings.json`** directly — a fixed, Claude-Code-owned
  path under the user's home directory, read for values like the persisted
  effort level. This is a hard-coded host-specific config location with no
  abstraction point at all.
- `model_context.py` encodes Claude Code's own model-naming and
  effort-level vocabulary directly: it reads `hook_input["effort"]["level"]`
  as "the LIVE, authoritative value Claude Code sends on every status-line
  request" for features like `/effort max` session overrides
  (`model_context.py:20-24`), falls back to an `effortLevel` key in
  `~/.claude/settings.json` "for older Claude Code versions" (`model_
  context.py:26-27`), and hardcodes Claude's own model-tier color scheme
  (Haiku/Sonnet/Opus, `model_context.py:9-13`) and Claude Code's own
  five-tier effort ladder (low/medium/high/xhigh/max, `model_context.py:
  15-21`, explicitly noted as matching "Claude Code's own canonical...
  ordering"). None of this generalizes to a host with different model
  names, no effort-tier concept, or no per-session `/effort` command.

A second host without an equivalent terminal status-line hook (or with a
differently-shaped one) would need this entire handler family either
disabled or rewritten from the ground up against that host's UI extension
point, if one exists.

### 9. `permission_mode` field (`utils/permission_mode.py`) — **medium**

`is_bypass_mode()` (`utils/permission_mode.py:21-31`) reads a
`permission_mode` field Claude Code sends on every hook input, with five
recognized values (`"default"`, `"plan"`, `"acceptEdits"`, `"dontAsk"`,
`"bypassPermissions"`) documented as Claude Code's own approval-mode
vocabulary. The function itself is defensively generic (falls through to
`False` for anything unrecognized), so a host without this exact five-value
enum degrades safely to "never auto-approve" rather than crashing — medium
because the *concept* (a host-reported flag saying "no per-tool confirmation
prompt is active") is portable, but the exact string vocabulary is Claude
Code's.

### 10. Plan 00290's per-event socket relay — **host-agnostic transport, in favour of abstraction**

`CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md`
(read in full to line 150; §§0-3) is worth calling out as a **positive**
data point for future abstraction work: the per-event-socket design is
explicitly a pure byte pump with no host-specific knowledge at the
transport layer. Key facts from the design doc:

- "EOF-delimited framing... lets the relay be a pure byte pump" — the Rust
  relay binary (`relay/hooks_relay.rs`) does zero JSON parsing; it streams
  stdin→socket, then socket→stdout, and the daemon reconstructs the
  `{"event": ..., "hook_input": ...}` envelope server-side using "which
  listener the connection arrived on" to supply the event name
  (DESIGN-socket-relay.md §2, lines 76-103).
  the relay contract itself: "connect, before reading any stdin", pump,
  timeout, fail-open `{}` on error — is entirely generic and describes no
  Claude-Code-specific behaviour (DESIGN-socket-relay.md §3.1, lines
  105-149).
- The design explicitly separates "which socket got connected to" (a
  deployment-time literal, §3 lines 34-37 quoting `hooks_relay.rs`
  contract) from "what that event means on the wire" (still entirely owned
  by `hook_result.py`'s per-event serializers, §3 above) — i.e. Plan 00290
  only abstracts the *transport*, confirming that the wire-contract
  coupling (§3) is a separate, larger piece of work untouched by this
  design.

This means: **if** a second host were added, the per-event-socket/relay
transport layer as designed in Plan 00290 would very likely work unmodified
as the IPC mechanism between that host's forwarders and the daemon — the
hard work is entirely in what gets read from/written to that socket (the
JSON shapes in `core/hook_result.py`, §3), not in how the bytes move.

## Difficulty summary table

| # | Coupling | File(s) | Difficulty |
|---|---|---|---|
| 1 | Event taxonomy (`EventIDMeta`, `EventType`) | `constants/events.py`, `core/event.py` | Hard |
| 2 | `HookInput`/`ToolInput` field shapes | `core/event.py` | Medium |
| 3 | Verdict→wire response contract (`to_json`) | `core/hook_result.py` | Hard |
| 4 | Front-controller stdin/stdout loop | `core/front_controller.py` | Easy |
| 5 | settings.json registration mechanism | `install.py`, `install/client_owned_assets.py` | Fundamental (mechanism) / Easy (per-event data) |
| 6 | Forwarder scripts + init.sh transport | `.claude/init.sh`, `.claude/hooks/*` | Medium (Stop exit-code workaround is the hard spot) |
| 7 | Transcript-path-on-disk convention | `core/transcript_reader.py`, several consumers | Medium/Hard |
| 8 | Status-line feature + Claude-specific vocab | `handlers/status_line/*` | Hard |
| 9 | `permission_mode` field vocabulary | `utils/permission_mode.py` | Medium |
| 10 | Per-event socket relay transport | Plan 00290 `DESIGN-socket-relay.md` | N/A — already host-agnostic; evidence FOR abstraction |

## Open questions

- No web research was in scope for this doc; whether/how a second host
  (e.g. a `codex-cli`-shaped agent) exposes an equivalent hook-registration
  surface, transcript-path convention, or terminal status-line hook is
  unknown from this repository alone and would need separate research
  against that host's own docs.
- Whether `HookResult`'s internal `Decision` enum and event-agnostic fields
  (context/guidance) are sufficient as a genuinely host-neutral internal
  model, or whether a second host's hook contract would surface concepts
  this enum cannot express, cannot be assessed without knowing that host's
  actual hook taxonomy.
- The daemon ships 31 wired events out of 32 catalogued (`events.py`
  `EventKey` literal; verified by direct grep at HEAD during the Plan 00292
  repair pass — `DirectoryAdded` is the one `wired=False`); it is
  unclear how many of Claude Code's own hook types have obvious semantic
  analogues on a differently-designed host versus being Claude-Code-only
  concepts (e.g. `TeammateIdle`, `Elicitation`/`ElicitationResult` sound
  MCP/multi-agent-specific and may or may not generalize).
