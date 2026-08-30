# RESEARCH: full context-budget fat audit (Plan 00293, extension)

**Scope**: owner direction — "what was this mention of slash chrome — look
harder — what other fat can we trim?" Extends `RESEARCH-tool-disable.md`
(tool-schema costs, disable mechanisms) to every other context-resident
surface in a real session of this repo: the `/chrome` integration properly
verified, the daemon-injected `CLAUDE.md` block, skills/agents listings, MCP
servers, memory, rules files, and session-start advisories. Performed
2026-08-30 against Claude Code v2.1.247–v2.1.251 (both appear across this
project's session transcripts) and this repo's live `.claude/` config.

**Method** (same template as the prior doc): counted with `tiktoken`
`cl100k_base` (a proxy for the Claude tokenizer — treat as ±10–15%) via a
throwaway venv (`python3 -m venv`, `pip install tiktoken`; no other package
was available). Content was either transcribed from this session's own
rendered system context into scratch files, read directly from tracked repo
files (`CLAUDE.md`, `.claude/rules/*.md`, `.claude/settings*.json`), or
pulled from the 12 session transcripts at `/root/.claude/projects/-workspace/ *.jsonl` via bounded `grep`/streaming Python reads — no whole transcript was
loaded into context. Where a number could not be measured (no live
`/context`, no logged-in nested session — same limitation as the prior doc),
it is graded as an estimate or left as an open question rather than invented.

## The load-bearing findings first

1. **The single biggest context cost in this repo is not a tool — it's the
   daemon's own injected `CLAUDE.md` block**, at **28,630 cl100k tokens**,
   resident in **every** session and every turn thereafter (it's the system
   prompt, not a one-time injection). This dwarfs every tool schema combined
   (~9.4k in the prior doc's measured session) and is already the subject of
   Plan 00116, which is **Dormant** with the fix half-shipped. See below.
2. **`/chrome` is a real, documented feature — genuinely disabled in this
   repo — and the Reddit "22k tokens" number remains unverified by any
   primary source.** It is implemented as an MCP server (`claude-in-chrome`)
   registering roughly a dozen browser tools, off by default, requiring
   either `--chrome` or an explicit `/chrome` → "Enabled by default" opt-in.
   Neither has ever happened in this container: zero occurrences of the
   string "chrome" across all 12 of this project's session transcripts,
   no `--chrome` anywhere, no `enabledPlugins` entry for it, no MCP servers
   configured at all (`~/.claude/settings.json` and `/workspace/.claude/ settings.json` both have zero `mcpServers` keys). Cost today: **0
   tokens.** See §1.
3. **A live disconfirming finding on the Artifact source-disable, worth
   flagging to the owner directly**: `.claude/settings.json` already has
   `"enableArtifact": false` on disk right now (written by the in-flight
   `source_disable` work logged in this plan's journal at 20:53–20:54 today),
   yet **this very session's own tool list still carries the full Artifact
   tool with its complete ~6,038-token schema.** The setting has not actually
   taken effect for this session. See §4 for detail and a hypothesis.

## §1. `/chrome`, properly verified

### What it is

Primary source: [code.claude.com/docs/en/chrome](https://code.claude.com/docs/en/chrome)
(fetched 2026-08-30). Claude Code integrates with the **Claude in Chrome**
browser extension to drive a real, visible Chrome/Edge/Chromium-family
window: navigate, click, type, read console/network state, take screenshots,
record GIFs, upload files. It shares the user's logged-in browser session
(so it can act on authenticated sites like Gmail/Notion/Google Docs without
API connectors), and it is implemented as **the `claude-in-chrome` MCP
server** — the doc's own instruction for listing its tools is `/mcp` →
select `claude-in-chrome` → **View tools**.

**Tools it registers** (named individually in the docs' "Browser tools in
plan mode" section, the only place a tool inventory is given without a live
connection): `read_page`, `get_page_text`, `find`, `tabs_context_mcp`,
`browser_batch`, console-message reading, network-request reading,
screenshot (with a `save_to_disk` flag), plus click/type/navigate/tab-and-
window-management/GIF-recording actions bundled under "state-changing
calls" without individual names given. That's a minimum of **roughly a
dozen distinct tools** by name, likely more once click/type/navigate/tab
management are each their own tool (consistent with the doc's instruction to
check `/mcp` for "the full list" rather than enumerating it in prose).

### Is it enabled here? No — confirmed by four independent negative checks

| Check                                                                                       | Result                                                                                                   |
| ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `--chrome` flag ever used in any of this project's 12 transcripts                           | 0 occurrences of the string "chrome" at all                                                              |
| `/chrome` → "Enabled by default" toggle                                                     | No evidence of use; feature is opt-in per-machine, not per-repo, and this container shows no sign of it  |
| `mcpServers` configured (user `~/.claude/settings.json` or project `.claude/settings.json`) | Neither file has an `mcpServers` key — **no MCP servers of any kind are configured in this environment** |
| `enabledPlugins` (user `~/.claude/settings.json`)                                           | Only `pyright-lsp@claude-plugins-official` and `phpantom-lsp` — both LSP plugins, unrelated to Chrome    |

Chrome integration also requires signing in with `/login` on a direct
Anthropic plan; API-key/long-lived-token auth keeps it off even if
`--chrome` is passed (documented behaviour since v2.1.216, before which the
attempt silently 403'd). This container's auth mode was not independently
re-verified, but is moot given the four checks above already show zero
usage.

**This repo does have a *different*, cheaper browser-automation path**: the
user-level skill `/root/.claude/skills/browsing/SKILL.md` (CCY's own
`agent-browser` / `agent-browser-lite` CLI, invoked via **Bash**, not an MCP
tool). It drives Lightpanda (headless, ~25 MB RSS) or full Chromium
(headed), but because it's a CLI wrapped in Bash rather than a set of MCP
tool schemas, its context cost is just its skill-index line (part of the
1,994-token skills listing in §3) plus the skill body **only when actually
read** (on-demand, per skill-loading semantics) — never a standing tool-
schema tax. This is architecturally the reason to prefer it over `--chrome`
whenever headed-browser visibility for the *user* isn't specifically the
point.

### The 22k-token claim, graded

No primary source gives any number for the Chrome/browser-tools token cost.
The [chrome doc](https://code.claude.com/docs/en/chrome) only says, of the
"enabled by default" toggle: *"Enabling Chrome by default in the CLI
increases context usage since browser tools are always loaded. If you
notice increased context consumption, disable this setting and use
`--chrome` only when needed."* — confirming the *shape* of the cost (tools
are always-loaded, not deferred, when the default-on toggle is used) but
publishing no figure. A rough order-of-magnitude estimate from this
project's own measured schema costs: a dozen-plus MCP tools at the sizes
seen for comparable multi-parameter tools in the prior doc's table (Agent
836, Bash 704 tokens; a browser tool with page/selector/coordinate
parameters would plausibly sit in a similar 300–900 token band) would land
in the **4,000–12,000 token range**, not implausible next to 22k if the
real schemas run larger (Artifact's is 6,038 tokens for ONE tool with a
complex parameter surface) — but this is estimation from adjacent data, not
verification. **Grade: real feature, real always-loaded-when-default-on
cost confirmed in kind by the docs, exact magnitude and the specific "22k"
figure unverified by any primary source found.** Unchanged from the prior
doc's grading; this pass adds the four-way confirmation that it costs
**zero tokens in this repo today**, and traces the specific alternate route
(`browsing` skill) that avoids the tax entirely for CCY's own use cases.

### The off switch (exact mechanism, in case it's ever turned on)

- Never pass `--chrome`.
- If `/chrome` → "Enabled by default" was ever selected, run `/chrome` again
  and turn it back off (writes to user settings, not this project's).
- Organization-level: `deniedMcpServers` managed setting can block the
  `claude-in-chrome` MCP server outright (also suppresses the install
  prompt) — a project/org lever, not a per-session one.
- **Verdict: KEEP disabled.** Zero cost today; no action needed. If browser
  automation is ever wanted, prefer the `browsing` skill's `agent-browser`
  route (Bash-driven, no standing MCP schema cost) over `--chrome` unless
  the user specifically needs to *watch* the browser in real time, which is
  `agent-browser`'s (headed) whole reason to exist per that skill's own
  guidance.

## §2. The `CLAUDE.md` hooksdaemon block — the single fattest item this project owns

**Measured**: `/workspace/CLAUDE.md` is 121,933 bytes, essentially entirely
occupied by the auto-generated `<hooksdaemon>...</hooksdaemon>` block
(121,932 of 121,933 bytes — the file is *nothing but* this block plus a
trailing newline). Token count: **28,630 cl100k tokens.** This is resident
in the system prompt of **every** session, on **every** turn, for the whole
session's duration — the single most expensive line item measured in this
audit by a wide margin (4.7x the next-largest item, the Artifact tool
schema).

**This is already a known, tracked problem** — Plan 00116 ("CLAUDE.md Token
Compression via Stateful Progressive Disclosure") diagnosed exactly this
block back on 2026-05-29, when it measured **22,041 bytes / 407 lines = 46%
of a then-131KB total CLAUDE.md** (33k tokens across the whole always-on
tree at that time). **The block has grown roughly 5.5x in bytes since that
measurement** (22,041 → 121,932 bytes) and is now effectively 100% of
`CLAUDE.md` rather than 46% of it — the growth this audit measures is
directly the trend Plan 00116 was raised to arrest, continuing unchecked
because the plan's own fix was never finished.

Plan 00116's design (three-layer stateful progressive disclosure — a
compact always-on rule-ID table, a verbose block on a rule's *first* fire
per session, a terse reminder on repeat fires, full detail on-demand via
`rule-explain <ID>`) is exactly the on-demand pattern this audit found
already working well elsewhere (§5, rules files). **Status**: `Dormant` —
"Phases 1–2 complete and merged; Phase 3 blocked on the tracker-wiring
decision," per that plan's own header. Phase 3 is the part that would
actually shrink this 28,630-token block down to "a few KB" (the plan's own
projection).

**Verdict: TRIM — highest-value item in this entire audit, but the fix is
already planned and blocked, not undiscovered.** This audit's contribution
is the up-to-date measurement (28,630 tokens, 5.5x growth since diagnosis)
that makes the case for unblocking Plan 00116 Phase 3 concrete and current
rather than a five-month-old number. No new mechanism is proposed here —
re-read Plan 00116's own design rather than duplicating it.

## §3. Skills and agents listings

**Skills**: this session's available-skills listing (25 entries: `browsing`,
`acceptance-test`, `configure`, `docs-qa`, `hooks-daemon`, `mode`,
`optimise`, `release`, `design`, `dataviz`, `artifact-design`,
`artifact-diagramming`, `artifact-capabilities`, `update-config`,
`keybindings-help`, `code-review`, `simplify`, `fewer-permission-prompts`,
`loop`, `schedule`, `claude-api`, `run`, `init`, `security-review`, plus the
Claude/Anthropic-detection trigger block attached to `claude-api`) —
transcribed verbatim and token-counted: **1,994 cl100k tokens**, resident
upfront every session (the harness needs every skill's name+description to
decide when to invoke one — this is not deferrable the way MCP tools are).

Only `browsing` (project-relevant CLI skill), `acceptance-test`,
`configure`, `docs-qa`, `hooks-daemon`, `mode`, `optimise`, `release` are
this project's own skills (`/workspace/.claude/skills/`, 7 entries — see
directory listing). The remainder — `design`, `dataviz`, `artifact-design`,
`artifact-diagramming`, `artifact-capabilities`, `update-config`,
`keybindings-help`, `code-review`, `simplify`, `fewer-permission-prompts`,
`loop`, `schedule`, `claude-api`, `run`, `init`, `security-review` — are
user-level/global skills (only `browsing` was found under
`/root/.claude/skills/`; the rest are plugin- or platform-provided and not
files this repo or even this user's `~/.claude/skills/` directory controls
directly, so they are **not trimmable from this project's config at all**).

**Coupling to the Artifact decision** (§4, and cross-referencing the prior
doc's open question 4): five of the listed skills — `design`, `dataviz`,
`artifact-design`, `artifact-diagramming`, `artifact-capabilities` — exist
specifically to author Artifact content. If Artifact is genuinely retired
as a never-want, these five keep costing their index-line share of the
1,994 tokens for a tool that no longer exists. That per-skill share was not
separately measured (the five are interleaved with unrelated skills in one
transcribed block); a rough proportional estimate from the five descriptions'
combined length is on the order of **500–700 tokens** of the 1,994-token
total, but this is not independently trimmable by this project either — see
above.

**Agents**: the available-agent-types listing (14 entries: `claude`,
`claude-code-guide`, `code-reviewer`, `Explore`, `general-purpose`,
`hooks-daemon-docs-qa`, `hooks-daemon-plan-dedupe-scout`, `Plan`,
`python-developer`, `qa-fixer`, `qa-runner`, `release-agent`,
`statusline-setup`, `transcript-inspector`) — **1,060 cl100k tokens**,
resident upfront every session for the same reason.

**Verdict for both: DEFER.** Trimming requires usage data this audit does
not have — exactly the transcript-usage analyser Plan 00293 Phase 2 is
already scoped to build ("per-tool call counts... distinguishing never-used
from rarely-used"). The same analyser, pointed at `Agent`/`Task` invocations
instead of raw tool calls, would answer "which of these 14 agent types and
25 skills were ever actually used across this project's sessions" — that is
the right next step, not a guess made here. What this audit adds: the
**measured cost floor** (1,994 + 1,060 = 3,054 tokens/session for these two
listings combined) to weigh against whatever the analyser finds, and the
observation that most of the skills list is not this project's to prune
regardless (only 7 of 25 are project-owned).

## §4. Remaining upfront tool schemas, and the Artifact non-disable finding

**Incorporated from the prior doc** (Task 1.1's Reddit-verification table),
restated here for the ranked total: `Agent` 836, `Bash` 704, `Read` 430,
`Skill` 419, `ToolSearch` 347, `Write` 268, `Edit` 242 tokens — **3,246
tokens total**, all upfront/non-deferred by SDK design ("The SDK always
loads core built-in tools such as Bash, Read, and Edit upfront and doesn't
count them toward the [deferral] threshold" — [tool search
doc](https://code.claude.com/docs/en/agent-sdk/tool-search)). **Verdict:
KEEP** — not deferrable, not disableable; this is the harness's fixed floor
for a working agent.

**The Artifact finding**: this session's own tool list (the top of this
very conversation) still shows the **complete Artifact tool schema**
(matching the prior doc's 6,038-token measurement almost exactly — same
tool, same session type). But `/workspace/.claude/settings.json` line 312
reads `"enableArtifact": false` **right now, on disk**, written earlier
today per this plan's journal (20:53–20:54 entries: `source_disable` option
shipped, daemon restarted, PreToolUse event wrote the setting). By the
documented mechanism ("no file can turn it back on," settings "read at
startup"), this session should not have the Artifact tool at all.

**It does.** Two non-exclusive hypotheses, neither independently confirmed
in this audit (flagging for the owner/Phase 4 rather than guessing further):

1. **This is an `Agent`-tool-spawned subagent thread, not a fresh top-level
   `claude` process.** The settings read may happen once at the *team's*
   top-level session start, with spawned agent threads inheriting whatever
   tool set was resolved then — in which case the setting genuinely will
   apply from the **next top-level session**, and this audit's own tool
   list is not the right place to look for it. This matches the documented
   "settings are read at startup" behaviour if "startup" means the parent
   session's, not each spawned agent's.
2. **The setting was written after this particular thread's tool set was
   already resolved** (a race between the PreToolUse-triggered settings
   write and this agent's own spawn) — a timing gap rather than a mechanism
   gap.

Either way, **the plan's own Task 4.1 ("remaining verification... a
`/context` spot check in a fresh interactive session") is not yet
satisfied, and this audit is a second, independent data point saying so**:
do not mark the Artifact disable verified until a genuinely fresh top-level
session (not a subagent) is checked. If hypothesis 1 holds, this changes
nothing about the recommendation — the setting is still correct and will
take effect for the next real session — but the win should not be recorded
as *confirmed* until that check happens.

**Verdict: TRIM, status IN FLIGHT, verification incomplete.** No new
recommendation beyond what Plan 00293's own Task 4.1 already calls for;
this audit adds a second observed instance of the not-yet-verified gap.

## §5. Everything else checked

| Item                                                                                                                                                                     | Measured                                                                                                                                                   | Resident?                                                                                                                                                                                                                                                                         | Verdict                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Deferred built-ins** (11 tools: CronCreate/Delete/List, EnterWorktree, ExitWorktree, Monitor, NotebookEdit, SendMessage, TaskStop, WebFetch, WebSearch)                | ~105 tokens total (name-only; from prior doc, reconfirmed — this session's own tool list matches exactly: 8 upfront + 11 deferred)                         | Deferred — full schema loads only via ToolSearch on demand                                                                                                                                                                                                                        | **KEEP** — already optimal                                                                                                                                                                                                                                               |
| **`.claude/rules/*.md`** (9 files: agent-docs, ccy-supervisor-dogfooding, claude-agents, claude-skills, human-docs, importing-reports, plan-dir, source-dirs, test-dirs) | 4,893 bytes total (~1.2k tokens) across all 9                                                                                                              | **On-demand only** — Claude Code's native `paths:` frontmatter loads a rule only when a matching file is touched (confirmed: two of these rendered into my own context this turn, immediately after I touched `PLAN.md`/`CLAUDE.md`-adjacent files — the mechanism visibly fired) | **KEEP** — this is the working example of the progressive-disclosure pattern Plan 00116 §2 wants to bring to the hooksdaemon block                                                                                                                                       |
| **Memory directory** (`/root/.claude/projects/-workspace/memory/`)                                                                                                       | Directory does not exist on disk; `ls` returns nothing                                                                                                     | N/A — zero cost, confirmed empty                                                                                                                                                                                                                                                  | **KEEP / N/A**                                                                                                                                                                                                                                                           |
| **MCP servers**                                                                                                                                                          | Zero configured — no `mcpServers` key in either `~/.claude/settings.json` or `/workspace/.claude/settings.json`                                            | N/A                                                                                                                                                                                                                                                                               | **KEEP / N/A** — nothing to trim because nothing is there                                                                                                                                                                                                                |
| **Global user `CLAUDE.md`** (`/root/.claude/CLAUDE.md`)                                                                                                                  | 3,028 chars, **775 cl100k tokens**                                                                                                                         | Resident every session, for this user, across every project (not just this repo)                                                                                                                                                                                                  | **KEEP** — already lean (37x smaller than this repo's own hooksdaemon block); not this repo's file to trim regardless                                                                                                                                                    |
| **Session-start advisories** (this session's sample: plan-QA drift report + secret-file-hygiene notice, from the `SessionStart:clear` hook payload)                      | 278 cl100k tokens for this session's specific findings                                                                                                     | One-time injection at session start, but then persists in transcript/context for the rest of the session like any other turn                                                                                                                                                      | **KEEP** — functional safety net (dogfood-bug-stop banner, drift findings); size is self-limiting — it shrinks automatically as the findings it reports (stale plan links, ungitignored secrets) get fixed, so the fix is "keep the tree clean," not "trim the advisory" |
| **Standing-authorisations reinforcement** (Plan 00283)                                                                                                                   | Not independently re-measured this pass (a full-text delivery once per session, then periodic short reinforcements per the cadence in `hooks-daemon.yaml`) | Session-scoped, cadence-gated                                                                                                                                                                                                                                                     | **DEFER** — no anomaly found; same shape as session-start advisories, already designed to avoid ride-along on every automated turn                                                                                                                                       |

## Ranked fat table (biggest first)

| Rank | Item                                                                              | Tokens (cl100k)                                                 | Resident                              | Owned by this repo?                       | Verdict                                                                                         |
| ---- | --------------------------------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 1    | `CLAUDE.md` hooksdaemon block                                                     | **28,630**                                                      | every session, every turn             | Yes (daemon-generated, tracked)           | **TRIM** — Plan 00116 Phase 3, currently Dormant/blocked                                        |
| 2    | Artifact tool schema                                                              | **6,038**                                                       | every session (upfront, not deferred) | Yes (settings-controlled)                 | **TRIM** — mechanism shipped today, **not yet verified as effective** (§4)                      |
| 3    | 7 non-Artifact upfront tool schemas (Agent/Bash/Read/Skill/ToolSearch/Write/Edit) | **3,246**                                                       | every session, every turn             | No (SDK-mandated)                         | KEEP                                                                                            |
| 4    | Skills index listing (25 skills)                                                  | **1,994**                                                       | every session, every turn             | Partially (7 of 25)                       | DEFER — needs Phase 2 usage analyser; ~500–700 est. coupled to Artifact's fate                  |
| 5    | Agents index listing (14 types)                                                   | **1,060**                                                       | every session, every turn             | Partially (project subagents + built-ins) | DEFER — needs usage analyser                                                                    |
| 6    | Global user `CLAUDE.md`                                                           | **775**                                                         | every session, all projects           | No (user-level)                           | KEEP                                                                                            |
| 7    | Rules files total (9 files)                                                       | ~1,200 bytes-equivalent, **on-demand, not resident by default** | Only when a matching path is touched  | Yes                                       | KEEP — model for #1's fix                                                                       |
| 8    | Deferred built-ins (11 tools)                                                     | **~105**                                                        | name-only; full schema on demand      | No (SDK behaviour)                        | KEEP — already optimal                                                                          |
| 9    | Session-start advisory (this session's sample)                                    | **278**                                                         | once at start, persists in transcript | Yes (daemon-generated)                    | KEEP — self-limiting, functional                                                                |
| 10   | `/chrome` browser tools                                                           | **0** (today)                                                   | N/A — not connected                   | N/A (platform feature, opt-in)            | KEEP disabled; unverified ~several-k-token cost if ever enabled, "22k" figure still unconfirmed |
| 11   | MCP servers                                                                       | **0**                                                           | N/A — none configured                 | N/A                                       | KEEP / N/A                                                                                      |
| 12   | Memory directory                                                                  | **0**                                                           | N/A — empty                           | N/A                                       | KEEP / N/A                                                                                      |

**Total measured, currently-resident, every-turn floor for a session in this
repo**: 28,630 + 6,038 + 3,246 + 1,994 + 1,060 + 775 + 105 ≈ **41,848
tokens**, before the session-start advisory (~278, variable) or any actual
work begins.

**Total realistically trimmable**:

- **Available today, one config change, pending only the verification gap
  in §4**: Artifact's 6,038 tokens (mechanism shipped, not yet confirmed
  live).
- **Available with follow-through on already-designed work**: the
  `CLAUDE.md` block's 28,630 tokens, reducible to Plan 00116's own
  projected "a few KB" (roughly 1,000–1,500 tokens for a compact rule-ID
  table) if Phase 3 ships — a **~27,000-token** reduction, by far the
  largest lever in this repo and larger than every other item in this table
  combined.
- **Combined realistic ceiling**: on the order of **33,000 tokens** (~79%
  of the measured 41,848-token floor) recoverable from items this project
  actually owns, without touching anything the SDK mandates (#3, #8) or that
  is already optimally on-demand (#7) or already zero-cost (#10–12).

## Open items for follow-up (not resolved in this pass)

1. **Artifact disable verification** (§4) — check a genuinely fresh
   top-level session's tool list, not a subagent's, before marking Plan
   00293 Task 4.1 done.
2. **Plan 00116 Phase 3** — this audit's up-to-date 28,630-token /
   5.5x-growth measurement is the strongest case yet for unblocking it; the
   "tracker-wiring decision" it's blocked on is outside this audit's scope
   to resolve.
3. **Skills/agents usage data** (§3) — Plan 00293 Phase 2's analyser, once
   built, should be pointed at `Skill`/`Agent` invocations specifically, not
   just raw built-in tool calls, to give ranks 4–5 a real usage-based
   verdict instead of DEFER.
