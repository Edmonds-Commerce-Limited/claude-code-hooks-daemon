# WebFetch / WebSearch hook surface — what the daemon can and cannot do

Explorer report for the team lead. Read-only exploration of `/workspace`; nothing was edited.

## Answer to the critical question first (item 3)

**The vendored contract does not document WebFetch or WebSearch at all.** A grep for
`webfetch|websearch` over `/workspace/contracts/claude-code-hooks/*.json` and `*.yaml`
returns **zero hits**. The contract is organised **per EVENT, not per TOOL** — 33 files,
one per hook event, each carrying exactly **one** `input_example` using a single
illustrative tool. There is no per-tool `tool_input`/`tool_response` catalogue anywhere
in it.

The only two tool payload examples that exist, verbatim:

`/workspace/contracts/claude-code-hooks/PreToolUse.json:29-44`

```json
  "input_example": {
    "session_id": "abc123",
    "prompt_id": "00000000-0000-0000-0000-000000000000",
    "transcript_path": "/home/user/.claude/projects/.../transcript.jsonl",
    "cwd": "/home/user/my-project",
    "permission_mode": "default",
    "hook_event_name": "PreToolUse",
    "tool_name": "Bash",
    "tool_input": {
      "command": "npm test",
      "description": "Run test suite",
      "timeout": 120000,
      "run_in_background": false
    },
    "tool_use_id": "toolu_01ABC123..."
  }
```

`/workspace/contracts/claude-code-hooks/PostToolUse.json:28-45`

```json
  "input_example": {
    "session_id": "abc123",
    "transcript_path": "/Users/.../.claude/projects/.../00000000-0000-0000-0000-000000000000.jsonl",
    "cwd": "/Users/...",
    "permission_mode": "default",
    "hook_event_name": "PostToolUse",
    "tool_name": "Write",
    "tool_input": {
      "file_path": "/path/to/file.txt",
      "content": "file content"
    },
    "tool_response": {
      "filePath": "/path/to/file.txt",
      "success": true
    },
    "tool_use_id": "toolu_01ABC123...",
    "duration_ms": 12
  }
```

So: **no `url`, no `prompt`, no `query` field is contractually documented anywhere**, and
**whether `tool_response` carries fetched markdown is not answerable from this repo's
contract.** The daemon's own schema is deliberately shape-agnostic —
`/workspace/src/claude_code_hooks_daemon/core/input_schemas.py:64-87`:

```python
        "tool_response": {
            "type": "object",
            "description": "Tool-specific response structure (stdout, file, filenames, etc.)",
            # Note: Structure varies by tool - Bash, Read, Glob, Grep, etc.
        },
```

with two pinned invariants in the comments at `:61-62`: *"Real events have `tool_response`,
NOT `tool_output`"* and *"Bash tool_response has NO `exit_code` field"*. The schema also
sets `"not": {"required": ["tool_output"]}` — the wrong field name is an explicit
rejection, not just an omission.

Note `tool_response` is typed `"type": "object"` and is in `required` — a plain *string*
response would arguably fail that validation. Worth checking if your design depends on it;
`budget_exhaustion_detector` defensively handles str/dict/other (see item 5).

### What the repo does know empirically about the web tools

The one field-derived fact lives in
`/workspace/CLAUDE/Plan/Completed/00315-hidden-agent-budget-detection/BUDGETS.md:21-22`:

- **WebSearch budget**: 200 calls/session, env `CLAUDE_CODE_MAX_WEB_SEARCHES`. Evidence is
  a *"Field fixture only (verbatim, another machine)"*; the reachability column reads
  **"Unknown — needs one live confirmation of whether the replacement reaches the
  PostToolUse tool_response"**. The observed shape is that a system message *REPLACES* the
  search result: `"Web search was not performed: this session has used its web search budget…"`.
- **WebFetch**: *"Unmapped — no ceiling, no fixture, no doc found… None (zero evidence in
  589 MB)… Unknown"*, and line 61: *"NO BUILD: WebFetch. Nothing to match; revisit only if
  a fixture ever appears."*

I confirmed there is still no fixture: `/workspace/untracked/payload-capture/` is **empty
(0 files)**, and no captured payload anywhere in `untracked/` names WebFetch.

### How to settle it definitively

Documented at `/workspace/CLAUDE/DEBUGGING_HOOKS.md:49-96`: enable daemon-side raw payload
capture, restart the **daemon** (not Claude Code), do one WebFetch and one WebSearch, then
read `untracked/payload-capture/PostToolUse.jsonl`:

```yaml
# .claude/hooks-daemon.yaml
daemon:
  payload_capture:
    enabled: true      # off by default
    dir: null          # null = <daemon untracked>/payload-capture
    events:            # empty list = all events
      - PreToolUse
      - PostToolUse
```

Then `./bin/hooks-daemon restart`. Capture is non-invasive (never alters the payload or the
response), config-driven, restart-applied. This is a ~2-minute experiment and it is the only
thing that will de-risk the design. **Do it before writing a line of the handler.**

### Fallback route if `tool_response` turns out to be a summary/status only

The transcript. `TranscriptReader.get_tool_result_text_by_id(tool_use_id)` at
`/workspace/src/claude_code_hooks_daemon/core/transcript_reader.py:684-729` pairs a
`tool_use_id` (which PostToolUse *does* carry) to its own `tool_result` block text,
scanning backwards through user/human messages and returning the string content or the
joined `text` blocks. Pairing is by id specifically so an unrelated later tool call cannot
be mistaken for this one's result.

Caveat: today its only caller is a **Stop** handler
(`/workspace/src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py:714-716`),
where the transcript is definitively flushed. Whether the `tool_result` is on disk at
*PostToolUse* time is unverified — measure it in the same experiment. Related helpers on
the same class: `get_last_tool_result_text()` (`:650`), `last_tool_result_was_error()`
(`:731`), `load_tail(path, max_bytes)` (`:150`) for a bounded read.

## 1. `web_search_year.py` — the closest existing template

`/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/web_search_year.py`
(98 lines, read in full).

- **Base**: `PreToolUseHandlerBase` (line 22), imported from `core.handler_bases`.
- **`matches()`** (37-50): returns False unless
  `hook_input.get(HookInputField.TOOL_NAME) == ToolName.WEB_SEARCH`; then reads
  `hook_input.get(HookInputField.TOOL_INPUT, {}).get("query", "")`.
  **`"query"` is a bare string literal** — there is no constant for WebSearch's input
  field anywhere in the codebase. Matches a word-boundary regex over years
  2020..current-1, rebuilt per call from `datetime.now().year` (`_outdated_year_pattern`,
  52-55) so embedded digit runs like `20200` do not false-fire.
- **`handle()`** (57-75): returns
  `GatingResult(decision=Decision.ALLOW, context=[...2 lines...], guidance="SUGGESTION: …")`.
  Advisory only; never denies.
- **`get_claude_md()`** returns `None` (77-78) — exempted with a recorded reason (item 6).
- **`get_acceptance_tests()`** (80-97): one `AcceptanceTest` with `title`, `command`,
  `description`, `expected_decision`, `expected_message_patterns`, `safety_notes`,
  `test_type=TestType.ADVISORY`, `requires_event`, `recommended_model=RecommendedModel.SONNET`,
  `requires_main_thread=False`. Its safety note reads *"WebSearch may not be available to
  subagent"* — relevant if you plan to acceptance-test a web handler.
- **Registration**: `handler_id=HandlerID.WEB_SEARCH_YEAR`,
  `priority=Priority.WEB_SEARCH_YEAR`, `tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL]`.

**Defect in the template worth not copying**: it passes the `NON_TERMINAL` tag but **does
not pass `terminal=False`**, so `terminal` defaults to `True` while the tag claims
otherwise. `budget_exhaustion_detector.py:213` does it correctly with an explicit
`terminal=False`.

## 2. `constants/tools.py`

`/workspace/src/claude_code_hooks_daemon/constants/tools.py`:

- `WEB_SEARCH = "WebSearch"` (line 53), `WEB_FETCH = "WebFetch"` (line 54), under a
  `# Web access` comment; the class docstring lists `- Web access: WebSearch, WebFetch`
  (line 33).
- Both appear in the `ToolNameLiteral` type alias (lines 95-96).
- **The only tool-name grouping in the file is `SUBAGENT_DISPATCH_TOOL_NAMES` (line 117)**
  — `frozenset({ToolName.TASK, ToolName.AGENT})`, with a comment explaining why dispatch
  gating must match the set rather than one literal (older builds send `Task`, >= 2.1.x
  send `Agent`). **There is no web-tool group.** A handler matching both web tools must
  define its own frozenset — either in the handler module or as a new peer constant here.
- `WEB_FETCH` currently has **zero references in `src/`** — the constant exists but nothing
  reads it. `WEB_SEARCH` is read only by `web_search_year.py`.
- `__all__` at line 120 exports `SUBAGENT_DISPATCH_TOOL_NAMES`, `ToolName`, `ToolNameLiteral`.

## 4. What PreToolUse and PostToolUse handlers can RETURN

Response shape is built by `HookResult` at
`/workspace/src/claude_code_hooks_daemon/core/hook_result.py`.

**Fields** (`:205-224`): `decision`, `reason`, `context: list[str]`, `guidance`,
`handlers_matched`, `worktree_path`, `updated_input: dict|None`, `rule` (internal-only —
consumed by the verdict-log writer, `to_json()` never emits it).

**PreToolUse serialisation** — `_format_pre_tool_use_response`, `hook_result.py:607-638`:

- `DEFER` → `{"hookSpecificOutput": {"hookEventName", "permissionDecision": "defer"}}` and
  **nothing else** (reason/updatedInput/context deliberately dropped, per the contract note).
- `DENY`/`ASK` → `permissionDecision` + `permissionDecisionReason` (deny gets
  `_DENY_CONTINUATION_SUFFIX` appended).
- `updated_input` → `hookSpecificOutput.updatedInput` (**replaces the ENTIRE tool input
  object**; emitted on allow/ask/deny, never defer).
- `context` → `hookSpecificOutput.additionalContext`, joined with `"\n\n"`.
- `guidance` → `hookSpecificOutput.guidance` — a **daemon-internal extension**, not part of
  the documented Claude Code contract; Claude Code ignores unknown keys. Allowlisted at
  `contracts/claude-code-hooks/ALLOWLIST.yaml:37-39`; comment at
  `core/response_schemas.py:39-42`.

**PostToolUse serialisation** — `_format_post_tool_use_response`, `hook_result.py:640-666`:

- `DENY` → top-level `{"decision": "block", "reason": …}`.
- `context` → `hookSpecificOutput.additionalContext` (joined `"\n\n"`).
- `guidance` → `hookSpecificOutput.guidance` (same internal extension,
  `ALLOWLIST.yaml:34-36`).
- **`hookSpecificOutput` is omitted entirely if it holds only `hookEventName`.**

**Tier enforcement** — `core/result_types.py` and `core/handler_bases.py`:

- `PreToolUseHandlerBase = GatingHandler` (`handler_bases.py:113`) → must return
  `GatingResult`: `ALLOW | CONTINUE | DENY | ASK | DEFER`. Constructors:
  `GatingResult.deny(reason, context=…)` (`result_types.py:105`),
  `.ask(reason, context=…)` (`:118`), `.defer()` (`:131` — **takes no arguments by design**,
  because the docs ignore reason/updatedInput/additionalContext on defer).
- `PostToolUseHandlerBase = BlockingHandler` (`handler_bases.py:118`) → must return
  `BlockingResult`: `ALLOW | CONTINUE | DENY`. **No ASK on PostToolUse** — there is no wire
  representation. `BlockingResult.deny(reason, context=…)` at `result_types.py:73`.
- Enforcement is dual-axis: mypy rejects an out-of-tier `Decision` argument, and Pydantic
  `validate_assignment` makes construction *and* mutation raise at runtime
  (`result_types.py:1-36`).

**Response JSON schemas** (`core/response_schemas.py:23-76`) — both
`PRE_TOOL_USE_SCHEMA` and `POST_TOOL_USE_SCHEMA` set `"additionalProperties": False` on
both the envelope and `hookSpecificOutput`. Anything not listed cannot be emitted.

**What you CANNOT do today:**

- **`systemMessage` on Pre/PostToolUse** — `HookResult` has no carrier and the schemas
  forbid extra keys. Recorded as deliberate at `ALLOWLIST.yaml:67-69` and `:73-75`
  (*"unexpressed-universal-fields"*), along with `continue`, `stopReason`, `suppressOutput`,
  `terminalSequence`. The allowlist reason: *"declaring fields nothing emits would loosen
  the schema for no capability. Declare a field in the same change that makes something
  emit it."*
- **`updatedToolOutput` / `updatedMCPToolOutput` / `classifierContext` on PostToolUse** —
  documented Claude Code capabilities with **no daemon carrier**, deliberately (YAGNI),
  `ALLOWLIST.yaml:43-51`: *"add a HookResult carrier when a feature does"*. **If the design
  wants to rewrite, truncate or redact fetched content on the way back to the model, this
  is the gap to close**: a new `HookResult` field + `POST_TOOL_USE_SCHEMA` entry +
  serialiser branch, and **delete the three allowlist entries** — a stale allowlist entry
  whose drift disappears FAILS the `hook_contract` QA check by design.

Prior art for `updatedInput` rewriting on PreToolUse:
`/workspace/src/claude_code_hooks_daemon/handlers/pre_tool_use/bash_safe_mode.py`
(`mode: inject` auto-prepends a `set -euo pipefail` prelude; docstring `:14`, notes `:96`
and `:176`).

## 5. Prior art: handlers that persist artefacts or shell out

**Yes, well established.** Closest analogue to a content-inspecting web handler:

**`/workspace/src/claude_code_hooks_daemon/handlers/post_tool_use/budget_exhaustion_detector.py`**
— the single best template for a PostToolUse handler that *reads `tool_response` of any
tool and persists a record*:

- Reads `hook_input.get(HookInputField.TOOL_RESPONSE)` at `:269` and `:287`.
- Normalises the varying shape via `_stringify_tool_response` (`:155-169`): returns a `str`
  as-is, `json.dumps(..., default=str)` for a dict, `str()` otherwise. **This is the
  shape-agnostic pattern to copy** given the contract silence.
- Appends each detection to an untracked JSONL ledger (`budget-exhaustion-events.jsonl`)
  using `utils/private_io.py` (`make_private_dir`, `open_private_append`) and
  `utils/retention.py` (`cap_log_file`). Ledger writes are **best-effort and fail-open** —
  an I/O error is logged, never raised into the handler's return.
- Options injected as `self._excluded_tools` / `self._extra_patterns`, declared and
  defaulted in `__init__` (`:216-222`) so mypy sees real attributes.
- Excludes file-content tools by default (`_DEFAULT_EXCLUDED_TOOLS`, `:72-82`) because
  their `tool_response` is what a file merely *says*.
- Carries **self-referential guards** (`:89-104`) so reading its own ledger or docs does
  not re-fire it and append a fresh entry — a self-feeding loop it hit in the field.
- `get_default_enabled()` returns `True` (opt-out), justified at `:227-233` as safe because
  it is advisory-only.

Other file-writing handlers: `background_process_tracker.py`, `markdown_table_formatter.py`
(rewrites the edited file), `goal_injection.py`, `session_start/model_fallback_detector.py`,
`status_line/context_sidecar.py`, `status_line/thread_registry.py`,
`user_prompt_submit/standing_authorisations.py`, `pre_compact/compaction_signal.py`,
`stop/auto_continue_stop.py`.

Handlers that shell out (subprocess): `lint_on_edit.py`, `validate_eslint_on_write.py`,
`git_hooks_executable_fixer.py`, `staged_lint_gate.py`, `docs_qa_edit.py`,
`plan_qa_edit.py`, `security_antipattern.py`, `session_start/contract_staleness.py`,
`status_line/git_branch.py`, `status_line/supervisor_indicator.py`,
`worktree_create/worktree_create_handler.py`.

**Full PostToolUse handler list** (`src/claude_code_hooks_daemon/handlers/post_tool_use/`,
9 handlers + `__init__.py`):

| File                            | One-line role                                              |
| ------------------------------- | ---------------------------------------------------------- |
| `background_process_tracker.py` | tracks backgrounded processes (Plan 00142 Layer B)         |
| `budget_exhaustion_detector.py` | generic budget/quota-exhaustion advisory                   |
| `command_hints.py`              | config-driven command-hint advisories with per-session TTL |
| `git_hooks_executable_fixer.py` | auto-fixes non-executable git hooks                        |
| `goal_injection.py`             | plan-execution-start goal-intent signal                    |
| `lint_on_edit.py`               | language-aware lint after Write/Edit                       |
| `markdown_table_formatter.py`   | auto-formats markdown tables via mdformat                  |
| `recovery_cron_advisor.py`      | failsafe recovery cron lifecycle advisory                  |
| `validate_eslint_on_write.py`   | ESLint on TS/TSX after write                               |

## 6. Full checklist to ship a NEW handler in this project

Everything `web_search_year` touches, in dependency order:

01. **Test first** — `tdd_enforcement` blocks creating the source file otherwise.
    `tests/unit/handlers/{event}/test_<name>.py`.
02. **Handler module** — `src/claude_code_hooks_daemon/handlers/{event}/<name>.py`,
    subclassing the event's base from `core.handler_bases` (never `Handler` directly).
    Auto-discovered by directory name via `EVENT_TYPE_MAPPING` in
    `/workspace/src/claude_code_hooks_daemon/handlers/registry.py:32+`.
03. **Export** — add the import + `__all__` entry in `handlers/{event}/__init__.py`
    (cf. `pre_tool_use/__init__.py:35` and `:71`).
04. **`HandlerID`** — a `HandlerIDMeta(class_name=…, config_key=…, display_name=…)` entry in
    `/workspace/src/claude_code_hooks_daemon/constants/handlers.py` (web_search_year at
    `:384-388`).
05. **`HandlerKey` Literal** — add the config key to the `HandlerKey = Literal[...]` list in
    the same file (declared `:745`; `"web_search_year"` at `:794`). Missing here is a
    type-safety gap.
06. **`Priority`** — a constant in
    `/workspace/src/claude_code_hooks_daemon/constants/priority.py`
    (`WEB_SEARCH_YEAR = 55` at `:223`). `scripts/qa/check_handler_reference.py` reports
    `priority-unresolvable` for a handler whose priority bypasses this module.
07. **`get_default_enabled()`** — override returning `True` only for opt-out handlers; must
    stay consistent with the config template (`budget_exhaustion_detector.py:227-233`).
08. **`get_claude_md()`** — must return guidance *or* be justified.
    `/workspace/tests/integration/test_claude_md_guidance_coverage.py` holds a
    **classification table**; `_EXEMPT_FROM_GUIDANCE` carries
    `"WebSearchYearHandler": "T4 message already carries the year, query and alternatives"`
    at `:245`. A new handler returning `None` without an entry fails this test. The four
    tests (T1-T4) are described at `CLAUDE/HANDLER_DEVELOPMENT.md:886-945`.
09. **`get_acceptance_tests()`** — plus an entry in
    `/workspace/CLAUDE/AcceptanceTests/validation/expected-responses.yaml`
    (`web-search-year` at `:110-117`, with `event_type`, `priority`, `terminal`, `tests[]`
    of `{pattern, decision, reason_contains}`).
    *Existing drift noted: that file records `priority: 50` while `priority.py` says 55.*
10. **Docs** — a `#### <config_key>` section in
    `/workspace/docs/guides/HANDLER_REFERENCE.md` (web_search_year at `:2436-2465`:
    Property/Value table with Config key, Priority, Type, Event; Description;
    Example trigger; Config example) **and** a row in the summary table at `:3527`.
    Audited by `scripts/qa/check_handler_reference.py`; its
    `undocumented-blocking-handler` rule reads `.claude/HOOKS-DAEMON.md` and is *"a floor,
    not a ceiling"* — advisory handlers are not strictly forced, but every one is
    documented in practice.
11. **Config templates** — `.claude/hooks-daemon.yaml.example:338` and
    `src/claude_code_hooks_daemon/daemon/init_config.py:228`. The
    `example-config-phantom-handler` QA rule audits this surface; it exists because that
    template had accumulated fifteen entries for handlers that no longer existed.
12. **Local dogfood config** — `.claude/hooks-daemon.yaml:546`.
13. **Integration tests** — `tests/integration/handlers/test_{event}_workflow.py`
    (`TestWebSearchYearHandler` at `:198`) and
    `tests/integration/test_all_handlers_response_validation.py` (`:202`). Blocking
    handlers additionally need an entry in
    `tests/unit/handlers/pre_tool_use/test_blocking_handler_evasion.py` (`:371`).
14. **Options (if any)** — there is **no per-handler options schema class to write**. The
    registry injects each `options:` key as a private attribute via `setattr`
    (`registry.py:389-405`, two-pass so `shares_options_with` inheritance works), so
    declare `self._my_option: T | None = None` in `__init__` for mypy. Document the option
    in `HANDLER_REFERENCE.md` (`CLAUDE/HANDLER_DEVELOPMENT.md:877`). Configurable *lists*
    must follow the additive/replace standard (`HANDLER_DEVELOPMENT.md:852-885`,
    MANDATORY). Unknown handler names in config are a hard error at
    `config/validator.py:502` (retired names are exempted).
15. **Restart the daemon before committing** (`daemon_restart_verifier`), and add a
    `CHANGELOG.md` entry.

The author-facing checklist is at `/workspace/CLAUDE/HANDLER_DEVELOPMENT.md:946-961`. Its
opening section (`:9-28`) insists you **capture the real event flow before writing the
handler** — which is exactly the payload-capture step in item 3.

## 7. Rate-limit / caching / network-access utilities

- **HTTP in the codebase: exactly one place, and it is not a handler** —
  `/workspace/src/claude_code_hooks_daemon/install/relay_deploy.py:219-234`,
  `_default_fetch(url)` using `urllib.request.urlopen` with a hardcoded `https://`-only
  scheme check and `_FETCH_TIMEOUT_SECONDS`; docstring says *"never exercised in unit tests
  (always mocked)"*. **No `requests`, no `httpx`, no `aiohttp` anywhere in `src/`.**
- **Network from a handler**:
  `/workspace/src/claude_code_hooks_daemon/handlers/session_start/version_check.py` shells
  out to `git ls-remote` against GitHub (`:31`) — prior art for a handler reaching the
  network, via subprocess rather than a Python HTTP client.
- **Rate limiting / TTL**: the only reusable pattern is in
  `/workspace/src/claude_code_hooks_daemon/handlers/post_tool_use/command_hints.py` —
  per-`(session_id, hint_id)` TTL bookkeeping (`_DEFAULT_TTL_SECONDS = 1800` at `:75`,
  configurable per hint), with a **bounded** map so a long-lived daemon cannot grow
  unboundedly (`:78`), and an optional `min_calls_between`. State lives only on the handler
  instance — a daemon restart resets it. It is a handler-local implementation, **not a
  shared utility**: copy the pattern, do not import it.
- **Retention / persistence helpers that do exist**: `utils/retention.py` (`cap_log_file`),
  `utils/private_io.py` (`make_private_dir`, `open_private_append`),
  `core/disclosure_tracker.py` (once-per-session disclosure suppression, reset by the
  `DisclosureReset*` handlers on SessionStart and PreCompact).

## Two things to flag

- **The `budget_exhaustion_detector` false-fired during this exploration.** A `grep` of
  `BUDGETS.md` returned the string `Web search budget`, and the PostToolUse detector matched
  it in the Bash `tool_response`. No budget was actually exhausted — its
  `_SELF_REFERENTIAL_RESPONSE_MARKERS` guard
  (`budget_exhaustion_detector.py:101-104`) covers only text naming the detector or its
  ledger, not `BUDGETS.md` prose. Worth knowing since your work sits adjacent to it.
- **`lsp_enforcement` blocks `grep 'WebFetch'`** as a symbol-lookup on first use per session
  (`block_once` mode). Expect it while exploring this surface.
