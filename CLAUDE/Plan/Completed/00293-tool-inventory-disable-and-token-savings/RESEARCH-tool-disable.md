# RESEARCH: tool disable mechanisms and token savings (Plan 00293, Phase 1)

**Scope**: Task 1.1 (disable mechanisms, schema-vs-refusal, deferral, measured
per-tool token costs, Reddit-lead verification) and Task 1.2 (this repo's
fight-with-hooks inventory). Research performed 2026-08-30 against Claude Code
v2.1.251 (installed here) and the official docs at code.claude.com/docs.

## The load-bearing answer first

**Yes — the right disable mechanisms remove the tool's schema from the context
window; a permission deny rule with a specifier does not.** The mechanisms
split into three tiers:

1. **Feature switches and tool-set selection** (`enableArtifact: false`,
   `CLAUDE_CODE_DISABLE_ARTIFACT=1`, `--tools`, subagent `tools`/
   `disallowedTools` frontmatter): these operate on tool *availability* — the
   tool is not registered for the session at all, so its definition is never
   sent. Evidence grade: strong (documented wording plus the artifacts doc
   treating all its four routes as equivalent "turn artifacts off" switches;
   direct `/context` confirmation deferred to Phase 4 dogfood — see Open
   questions).
2. **Bare tool-name deny rules** (`permissions.deny: ["Artifact"]`,
   `--disallowedTools Artifact`): documented as one of the four equivalent
   routes to "turn artifacts off" ([artifacts doc, "Disable
   artifacts"](https://code.claude.com/docs/en/artifacts)), and the tools
   reference describes deny-rule behaviour in removal language ("When your deny
   rules remove every other tool and also match `EndConversation`, as `"*"`
   does, Claude Code **removes it** too rather than leaving it as the only
   tool" — [tools reference](https://code.claude.com/docs/en/tools-reference)).
   Evidence grade: good but inferential — no doc sentence says "the schema is
   omitted from the API request" in those words.
3. **Specifier/parameter deny rules** (`Bash(rm *)`, `Agent(model:opus)`,
   `WebFetch(domain:x)`): these *cannot* remove the schema — the tool must stay
   loaded for its other uses, so they are call-time refusal only. No token
   savings. ([permissions doc](https://code.claude.com/docs/en/permissions))

So the plan's motivating insight holds: a binary never-want (the whole tool)
converts to a source-level disable and recovers the schema tokens; a semantic
policy (some uses allowed) cannot, and the hooks system remains the right tool
there.

## Task 1.1 — the disable mechanisms in detail

### 1. Settings permission rules (`permissions.deny`)

Primary source: [Configure
permissions](https://code.claude.com/docs/en/permissions).

- Granularity: bare tool name (`Artifact`), specifier (`Bash(npm run build)`,
  `Read(./.env)`, `WebFetch(domain:example.com)`), or parameter match
  (`Tool(param:value)`, deny/ask only, e.g. `Agent(model:opus)`,
  `Bash(run_in_background:true)`).
- **Parameter-match limits that matter for our Artifact case**: "A parameter
  the model omits is never matched, so `Agent(model:*)` doesn't match a call
  that leaves `model` unset." The Artifact tool's `action` defaults to
  `publish` when omitted, so `Artifact(action:publish)` is bypassable by
  simply omitting `action` — **permissions.deny cannot soundly express
  "publish blocked, list/read allowed"**. Primary content fields (`command`,
  `file_path`, `url`) are explicitly not parameter-matchable either.
- Deny wins across every scope: "If a tool is denied at any level, no other
  level can allow it." Managed settings deny cannot be overridden by
  `--allowedTools`.
- `Agent(AgentName)` deny rules disable specific subagents.

### 2. CLI flags (verified against `claude --help`, v2.1.251)

- `--disallowedTools, --disallowed-tools <tools...>` — deny list (same rule
  grammar as settings). The Reddit thread's spelling is correct.
- `--allowedTools, --allowed-tools <tools...>` — allow list.
- `--tools <tools...>` — "Specify the list of available tools from the
  built-in set. Use `""` to disable all tools, `"default"` to use all tools,
  or specify tool names (e.g. `"Bash,Edit,Read"`)." This is availability-level
  selection of the built-in tool set — the strongest per-session lever.

### 3. Feature switches (settings + env)

Primary sources: [settings
reference](https://code.claude.com/docs/en/settings-reference),
[env vars](https://code.claude.com/docs/en/env-vars),
[artifacts](https://code.claude.com/docs/en/artifacts).

- `"enableArtifact": false` — settings reference: "Turn the Artifact tool off
  with a `false` in any file; **no file can turn it back on**." Honoured in
  project `.claude/settings.json`/`.claude/settings.local.json` from
  v2.1.242 (before that, a higher-precedence file could re-enable). The
  deprecated spelling `"disableArtifact": true` still works.
- `CLAUDE_CODE_DISABLE_ARTIFACT=1` — documented env-var equivalent.
- `/config` → Artifacts row off — writes `"enableArtifact": false` to user
  settings.
- `permissions.deny: ["Artifact"]` — listed by the artifacts doc as the fourth
  equivalent route.
- Related switches worth knowing: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`
  (artifacts are off when set), `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1`
  (drops built-in subagent types), and the task tools (`TodoWrite`,
  `TaskCreate/Get/Update/List`) being **left out by default** on Opus 4.8 /
  Sonnet 5 / Fable 5-era models unless opted in ([tools
  reference](https://code.claude.com/docs/en/tools-reference)) — precedent
  that Anthropic itself treats tool removal as the token-saving mechanism.
- No per-tool `enableX` switches were found for other built-ins (NotebookEdit,
  WebSearch, etc.) — for those, the levers are `--tools`, deny rules, and
  deferral.

### 4. Deferred tools / ToolSearch

Primary sources: [Scale to many tools with tool
search](https://code.claude.com/docs/en/agent-sdk/tool-search),
[context window](https://code.claude.com/docs/en/context-window), plus
first-hand observation of this session.

- "When it is active, **tool definitions are withheld from the context
  window**." Tool search is on by default; `ENABLE_TOOL_SEARCH` takes
  `true`/`false`/`auto`/`auto:N` (auto = defer once deferrable definitions
  reach 10% of the window).
- Deferral covers MCP tools (unless a server is marked `alwaysLoad`) **plus
  "the built-in tools that load on demand"**; "The SDK always loads core
  built-in tools such as Bash, Read, and Edit upfront and doesn't count them
  toward the threshold."
- First-hand evidence from the session that produced this document: eleven
  built-ins (CronCreate/Delete/List, EnterWorktree, ExitWorktree, Monitor,
  NotebookEdit, SendMessage, TaskStop, WebFetch, WebSearch) arrived as a
  name-only deferred list costing ~105 cl100k tokens total (~8 tokens/tool);
  each schema loads only when fetched via ToolSearch.
- **Implication for the plan**: deferral already delivers nearly all of the
  saving for *rarely-used* tools (name-only until needed). Full disabling is
  only worth pursuing for (a) *never*-wants — where removing even the name and
  the bypass surface is the point — and (b) tools the harness always loads
  upfront. **Artifact is in class (b): it is not deferred**, its full ~6k-token
  schema is resident in every session, which is exactly why it is the headline
  candidate.

### 5. MCP-server-level controls

- Deny rules by server or tool: `mcp__server`, `mcp__server__tool` (settings)
  — parenthesised `mcp__` rules in settings files are skipped; parameter-level
  MCP rules need `--disallowedTools`.
- Deferral (above) is the main context-cost control; `alwaysLoad` exempts a
  server from it. Removing an MCP server from config removes its tools
  entirely.

### 6. Measured per-tool schema token costs

**Method**: no API credential is available inside this container (nested
`claude -p` reports "Not logged in"), so a live A/B `/context` diff was not
possible. Extracting description strings from the installed binary was tried
and rejected: the descriptions are assembled at runtime from feature-gated
template fragments, so static extraction over- or under-counts. The numbers
below were instead measured by transcribing the **rendered schema blocks from
this session's own system prompt** (Claude Code harness, Fable 5, 2026-08-30)
to files and token-counting with `tiktoken` `cl100k_base` (a proxy for the
Claude tokenizer; treat as ±10–15%). Transcription source files are in the
session scratchpad (`schema-artifact.txt`, `schema-artifact-params.txt`,
`schema-other-tools.txt`).

| Tool                          | Loaded state             | chars  | cl100k tokens |
| ----------------------------- | ------------------------ | ------ | ------------- |
| **Artifact** (description)    | upfront                  | 16,163 | 3,552         |
| **Artifact** (parameters)     | upfront                  | 10,649 | 2,486         |
| **Artifact total**            | upfront                  | 26,812 | **6,038**     |
| Agent                         | upfront                  | 3,540  | 836           |
| Bash                          | upfront                  | 2,847  | 704           |
| Read                          | upfront                  | 1,627  | 430           |
| Skill                         | upfront                  | 1,824  | 419           |
| ToolSearch                    | upfront                  | 1,449  | 347           |
| Write                         | upfront                  | 1,110  | 268           |
| Edit                          | upfront                  | 999    | 242           |
| 11 deferred built-ins (names) | deferred                 | —      | ~105 total    |
| **Session total observed**    | 8 upfront + 11 deferred  | —      | **~9,400**    |

Notes:

- The Artifact tool alone is ~64% of this session's tool-definition budget —
  the single biggest discretionary context cost with a documented off switch.
- Rendered schemas are session-variant (feature-gated fragments; the binary
  contains conditional Artifact sections — `files`/multi-file, `lang`, type
  pages — not rendered here). A plain CLI session also loads tools this
  harness deferred or omitted (Glob, Grep, TodoWrite ~1.3k, etc.), so a CLI
  `/context` reading of ~10–20k total tool definitions is consistent with
  these measurements.
- The Phase 2 report generator should therefore ship measured *estimates* with
  a "measure your own session with `/context`" instruction rather than
  hard-coding one session's numbers.

### 7. The Reddit lead, verified claim by claim

Source: [r/ClaudeCode, "Tip: Instantly save 10k tokens on every new
session"](https://www.reddit.com/r/ClaudeCode/comments/1w2ja43/) by u/nNaz
(fetched 2026-08-30 via headless browser; reddit blocks plain fetchers).

| Claim                                                             | Verdict                                                                                                                                                                                                             |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ~20k tokens of tool definitions per session                       | **Plausible, session-dependent.** This session measured ~9.4k with 11 tools deferred; a full CLI tool set upfront lands in the 10–20k band. Docs publish no official total.                                          |
| Artifact is ~10k of it ("half")                                   | **Right order, high for this session.** Measured 6.0k here; feature-gated fragments (multi-file, lang, capabilities) can push it higher in other sessions. Direction and magnitude of the tip: confirmed.            |
| `"enableArtifact": false` in `~/.claude/settings.json`            | **Confirmed** — [settings reference](https://code.claude.com/docs/en/settings-reference); "no file can turn it back on".                                                                                              |
| `claude --disallowed-tools Artifact`                              | **Confirmed** — flag exists in v2.1.251 `--help` and the [permissions doc](https://code.claude.com/docs/en/permissions).                                                                                              |
| `CLAUDE_CODE_DISABLE_ARTIFACT=1`                                  | **Confirmed** — [env vars doc](https://code.claude.com/docs/en/env-vars).                                                                                                                                            |
| `/config` → Artifacts off (comment)                               | **Confirmed** — [artifacts doc](https://code.claude.com/docs/en/artifacts), writes `enableArtifact: false` to user settings.                                                                                          |
| Project-level override via `.claude/settings.local.json` (comment) | **Confirmed with a version gate** — honoured from v2.1.242; `false` wins, `true` cannot re-enable.                                                                                                                   |
| Not hot-loadable; needs a new session (comment)                   | **Consistent with docs** (no re-enable mechanism mid-session is documented; settings are read at startup). Unverified directly.                                                                                      |
| A skill can re-enable it per-invocation (comment)                 | **Unverified.** Skill frontmatter documents `allowed-tools` (narrowing); no primary source found for a skill *restoring* a session-disabled tool. Treat as folklore until tested.                                     |
| Disable `/chrome` to save 22k tokens (comment)                    | **Unverified number; real feature.** Chrome integration is real ([chrome doc](https://code.claude.com/docs/en/chrome)) and its MCP tools would cost context when connected, but no source for 22k. N/A in this repo. |
| "Smart zone is only ~200k of the 1M window"                       | **Opinion/folklore**, disputed in-thread; out of scope for this plan (we save tokens either way).                                                                                                                    |

## Task 1.2 — this repo's fight-with-hooks inventory

Method: reviewed the PreToolUse handler catalogue
(`src/claude_code_hooks_daemon/handlers/pre_tool_use/`, 52 handlers) and the
generated CLAUDE.md handler guidance, asking for each blocker: which tool does
it police, does the project ever want ANY use of that tool (semantic) or none
(binary), and what would retiring it lose?

### The one true source-disable candidate: `artifact_publish_blocker`

- **Tool policed**: Artifact. Current policy: publish/update **denied** (no
  escape hatch, human-only lift); `action: "list"` **always allowed**.
- **Binary or semantic?** *Almost* binary. The project never wants publishing
  from agents, but the handler deliberately preserves metadata-only `list`.
  That distinction is **inexpressible at source level**: `Artifact(action:publish)`
  in `permissions.deny` is unsound because an omitted `action` defaults to
  publish and omitted parameters never match, and `enableArtifact: false` /
  bare `Artifact` deny remove `list`/`read` too.
- **The trade**: keeping `list`+`read` costs ~6k tokens of schema in every
  session of every agent, plus the handler, its docs and its config surface.
  Retiring the tool outright saves all of that and (per the artifacts doc)
  cannot be re-enabled by any lower-precedence file — strictly stronger than
  the hook, which only sees tool calls the daemon intercepts.
- **What is lost by source-disabling**: (a) `action: "list"`/`read` (does any
  session actually use them? — a Phase 2 analyser question, and exactly what
  the transcript scan should answer); (b) the handler's advisory text
  educating agents about the policy (moot once the tool is invisible); (c) the
  audit trail of denied attempts (moot likewise); (d) artifact-flavoured
  skills (`artifact-design`, `design`, `dataviz`) keep costing index lines and
  become dead weight — a follow-on tidy.
- **Recommended disposition (for owner review in Phase 4)**: declare Artifact
  a never-want; set `"enableArtifact": false` in `.claude/settings.json`
  (requires ≥v2.1.242 — installed is v2.1.251); verify schema removal via
  `/context`; then demote `artifact_publish_blocker` to a zero-cost backstop
  (it only fires if the tool somehow exists) rather than deleting it —
  defence in depth retired deliberately, per the plan's non-goals.

### Everything else: semantic policy — hooks stay right

| Handler(s)                                                                                                                                                                                                                              | Tool(s) policed       | Why source-disable does not fit                                                                                                                                                                                       |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| destructive_git, sed_blocker, pipe_blocker, curl_pipe_shell, dangerous_permissions, root_recursion_guard, sudo_pip, pip_break_system, git_stash, git_message_backtick, github_auto_close_keywords, ancestry_preserving_merge, verification_result_gate, bash_safe_mode, worktree_file_copy, daemon_location_guard, npm_command, gh_issue_comments, gh_pr_comments, global_npm_advisor | Bash                  | Bash is wanted constantly; these judge command *content*. `permissions.deny` `Bash(prefix*)` rules exist but the docs themselves note content rules are bypassable by compound commands; the daemon's parsing is stronger. Zero token upside (Bash stays loaded regardless). |
| secret_file_guard, sensitive_content, error_hiding_blocker, security_antipattern, qa_suppression, comment_changelog, comment_size, lock_file_edit_blocker, write_clobber_guard, absolute_path, tdd_enforcement, markdown_organization, validate_instruction_content, plan_qa_edit, plan_time_estimates, docs_qa_edit, british_english | Write/Edit (+Read)    | Content/path-conditional policy on tools the project uses constantly.                                                                                                                                                   |
| lsp_enforcement, flaggable_content_channel_guard, quarantine_artefact_read_guard, flaggable_work_advisor, daemon_docs_guard                                                                                                              | Grep/Read/Bash        | Redirection/quarantine semantics; the tools themselves are wanted.                                                                                                                                                      |
| ask_user_question_blocker                                                                                                                                                                                                               | AskUserQuestion       | Allows prefixed questions — the definition of a semantic gate.                                                                                                                                                          |
| web_search_year                                                                                                                                                                                                                         | WebSearch             | Quality nudge on a wanted (and already deferred) tool.                                                                                                                                                                  |
| plan_number_helper, plan_qa_commit_gate, docs_qa_commit_gate, staged_lint_gate                                                                                                                                                          | Bash (git/mkdir)      | Workflow invariants, not tool bans.                                                                                                                                                                                     |

### Observed-never-used candidates (for the Phase 2 analyser, not policy)

- **NotebookEdit**: zero `.ipynb` files tracked in this repo; no handler wants
  it for anything. Already deferred here (~8 tokens), so the saving from a
  hard disable is cosmetic in this harness — but in a plain CLI session it
  loads upfront, and `--tools`/deny would remove it. Tier: never-used, low
  payoff, harmless.
- **EndConversation, PowerShell, computer-use tools** (where present):
  same shape — let the transcript analyser rank them by observed calls vs
  schema cost instead of legislating here.
- These are exactly the tier-(b) outputs the report generator should produce;
  no action in Phase 1.

## Options sketch for Phases 2–3

**Config shape (Task 2.3)** — under the daemon config, validated,
`extra="forbid"`, ships empty:

```yaml
tool_policy:
  never_want:
    - tool: Artifact
      reason: "publishing leaves the repository; see artifact_publish_blocker"
      disable_via: settings   # settings | env | deny — what the advisory recommends
  redundant_handlers:         # optional explicit mapping, else derived
    Artifact: [artifact_publish_blocker]
```

**Analyser input (Task 2.1)**: per-project session transcripts —
`~/.claude/projects/<project-slug>/*.jsonl`, the same JSONL surface the
daemon's transcript tooling already reads (`CLAUDE/DEBUGGING_TRANSCRIPTS.md`);
count `tool_use` blocks per tool per session with bounded streaming reads.
Distinguish calls by subagent vs main thread if cheaply available; never load
whole transcripts.

**Report tiers (Task 2.2)**: `never-want` (declared) / `never-used` (0 calls
across ≥N sessions) / `low-use` (below configurable calls-per-session floor) /
`keep`. Columns: tool, schema-token estimate (with "estimate — confirm with
/context" caveat), calls, sessions seen, tier, recommended mechanism (and for
never-wants, the exact settings snippet). Output: JSON + markdown under
`untracked/reports/`.

**Advisory (Task 3.1)**: session-start, opt-in, ships disabled. If a declared
never-want's disable is absent → advise the exact settings change; if present
→ flag the now-redundant blocker handler and the config to demote it. Never
edits settings itself.

## Open questions for the owner

1. **Artifact `list`/`read`**: is metadata-only listing worth ~6k tokens per
   session per agent? If yes, the blocker stays and no tokens are saved; if
   no, `enableArtifact: false` and demote the blocker. (The Phase 2 analyser
   can report observed `list` usage to inform this.)
2. **Verification step**: the schema-removal claim for `enableArtifact`/bare
   deny is docs-inferred. Confirm in Phase 4 by running `/context` in a
   session before/after the settings change (needs an interactive session —
   this container's nested `claude` has no login).
3. **Scope of never-want enforcement**: settings.json (shared, versioned)
   seems right over env/local — agree? Note deny-at-any-level cannot be
   re-allowed, and `enableArtifact: false` cannot be re-trued by other files.
4. **Skill index follow-on**: if Artifact goes, do the artifact-authoring
   skills (`artifact-design`, `artifact-capabilities`, `design`, `dataviz`)
   get pruned from this repo's skill roster too? (Separate small saving;
   separate decision.)
5. **Chrome/computer-use**: not connected in this repo's containers today; do
   we want the report to cover integration-level context costs (MCP servers,
   Chrome) or built-in tools only for v1?
