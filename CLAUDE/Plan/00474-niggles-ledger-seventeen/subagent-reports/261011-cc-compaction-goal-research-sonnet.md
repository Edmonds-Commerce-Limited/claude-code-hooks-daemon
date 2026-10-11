# Claude Code compaction, /goal, cache TTL, git relative worktrees: research

Researched 2026-10-11 from the live docs (code.claude.com, platform.claude.com), the CHANGELOG
(https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md, read in full, newest entry 2.1.296) and git's own
Documentation/ tree. Anything not found in a source is labelled NOT FOUND or INFERENCE.

## 1. Compaction model and cost

**Which model.** NOT FOUND as an explicit statement. No doc page says "compaction uses model X". Evidence that it is the session's
own model:
- https://code.claude.com/docs/en/prompt-caching#compacting-the-conversation: the summary request is "a separate request with the
  same system prompt, tools, and history as your conversation, plus a summarization instruction appended as a final user message".
  A cache read on that prefix is only possible on the same model, so INFERENCE: the session model.
- https://code.claude.com/docs/en/model-config (fallback section): the `--fallback-model` chain "also covers compaction", but Claude
  Code will not fall back to a model with a smaller context window than the primary's.
- CHANGELOG 2.1.178: compaction honours `--fallback-model` on overload. 2.1.282: compaction retries on a fallback model when the
  summarization request is refused. 2.1.3: fixed sub-agents using the wrong model during compaction.
- https://code.claude.com/docs/en/context-window#what-survives-compaction: since v2.1.198 the summary request inherits the session's
  extended-thinking configuration.
- No source says a smaller model such as Haiku is used.

**Cache.** Yes. Same prompt-caching page: "While the cache is warm, that request reads your prefix from the cache, so a mid-session
`/compact` costs a fraction of what the context size suggests and spends most of its time generating the summary." After a gap longer
than the TTL "the summarization request reprocesses the full history as uncached input", which is why compaction "costs the most when
you resume an old session". CHANGELOG 2.1.70: compaction preserves images in the summarizer request so the cache is reused. 2.1.257:
fixed sessions with an advisor model missing the cache on background requests (compaction, /recap, prompt suggestions).

**TTL bucket caveat.** Same page, "Which TTL each request gets": compaction is in the "Everything else" bucket (default five
minutes, even on a subscription), not the main-conversation bucket (one hour on a subscription). The docs do not say how that
interacts with the read of the main-conversation prefix; reads are keyed on the prefix, so INFERENCE: no effect on the read.

**Cost of a 400k-token compaction.** NOT FOUND: no doc gives a dollar figure (https://code.claude.com/docs/en/costs says only that
compacting a large context "is itself a large request"). Arithmetic from the pricing rules in
https://platform.claude.com/docs/en/build-with-claude/prompt-caching: a cache read is 0.1x the base input price (0.05x on Opus 5.5
and Sonnet 5.5, 0.025x on Fable 5.1 and Mythos 5.1). For a base input price of P dollars per MTok:
- Warm: about 0.4 x 0.1 x P = 0.04P for the history read, plus the summary output (length undocumented).
- Cold: about 0.4 x P for the history as uncached input, plus the same summary output. The docs do not say whether the
  summarization request also writes a cache entry (which would add 1.25x or 2x).
- Ratio: roughly 10x cheaper warm (20x or 40x on the cheaper-read models), before output cost.
- After compaction the next turn re-caches only the short summary in both cases.

## 2. Idle compaction

NOT FOUND. No setting, flag or env var makes Claude Code compact an idle session by itself. Searched the changelog, settings
reference, env-vars page, and the context-window, prompt-caching and costs pages. Nearest features:
- Idle-return prompt, CHANGELOG 2.1.84: nudges a user returning after 75+ minutes to run `/clear`, "reducing unnecessary token
  re-caching on stale sessions". It suggests `/clear`; it does not compact. 2.1.92 fixed the token figure shown in that hint.
- `/goal` idle check-ins (2.1.236 and later; capped at three per goal from 2.1.246; https://code.claude.com/docs/en/goal). These
  start a turn; they do not compact.
- The Reddit reports are not corroborated by any official source I found. I did not search Reddit.

## 3. Autocompact window

Sources: https://code.claude.com/docs/en/model-config#set-the-auto-compact-window,
https://code.claude.com/docs/en/settings-reference (autoCompactWindow, autoCompactEnabled, modelSettings),
https://code.claude.com/docs/en/env-vars, https://code.claude.com/docs/en/commands.

| Control | Detail | Version |
|---|---|---|
| `/autocompact [auto or tokens]` | 100K to 1M: plain count, k/M suffix, or a bare number 100-1000 meaning thousands. `auto` = window tuned for the model. No argument opens a dialog. Saved per model under `modelSettings`. | command: 2.1.221 or later (commands page); per-model save: 2.1.288 (before, one top-level `autoCompactWindow`) |
| `--autocompact` flag | Same values; overrides the saved setting for one launch; not preempted by managed settings. | version NOT FOUND |
| `autoCompactWindow` setting | Tokens, 100000 to 1000000, any settings file. A per-model value from `/autocompact` wins in the same file. | setting version NOT FOUND; added to subagent frontmatter and `--agents` in 2.1.296 |
| `modelSettings.<model>.autoCompactWindow` | Number 100000-1000000 or "auto". | 2.1.288 |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Plain integer only (`500k` reads as 500, clamps to 100K). Beats command, flag and setting. | version NOT FOUND |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | Percentage 1-100 of the auto-compact window. Can only lower the threshold; values above the default percentage are ignored. Only in sessions that compact before the model's limit. Applies to main and subagents. | version NOT FOUND |
| `autoCompactEnabled` / `DISABLE_AUTO_COMPACT=1` / `DISABLE_COMPACT=1` | Turn auto-compact off; the env var wins and the setting cannot re-enable. `DISABLE_COMPACT` also disables `/compact`. | |

- The window is capped at the model's context window.
- Defaults (model-config, "Default auto-compact thresholds"): with no window set, compaction happens at the model's context limit,
  except native-1M models (Fable, Sonnet 5+, Haiku 5.5, Opus 4.7+) compact at about 967K by default (CHANGELOG 2.1.247 moved
  Sonnet 5 from about 934K to about 967K). Sonnet 4.6 and Opus 4.6 without the 1M variant compact at the 200K boundary.
  `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` holds 1M models to 200K, and raising the window above 200K does not lift that hold.
- No default percentage is documented.

## 4. /goal and compaction (2.1.274 and later)

Sources: https://code.claude.com/docs/en/goal, CHANGELOG 2.1.274, https://code.claude.com/docs/en/hooks.

**(a) Within a live session, across compaction.** No sentence in goal.md states it. Supporting evidence:
- goal.md: `/goal` is "a wrapper around a session-scoped prompt-based Stop hook", so INFERENCE: the goal is session state outside
  the message history and compaction does not erase it.
- CHANGELOG 2.1.274: "Fixed hook-driven sessions (such as an active `/goal`) ending with 'Prompt is too long' instead of
  compacting when the context overflowed again after a reactive compaction". This presumes the goal stays active through compaction.
- goal.md lists "A context overflow that auto-compaction couldn't clear" as an error that clears a goal. That is a failed
  compaction, not a successful one.

**(b) `--continue` / `--resume` of a compacted session.** Yes, from 2.1.274. CHANGELOG 2.1.274: "Fixed an active `/goal` being lost
when resuming (`--continue` / `--resume`) a session that had compacted". goal.md "Resume with an active goal": restored on every
route (`--continue`, `--resume` with ID, name or transcript path, and the picker; the picker route since 2.1.239). The condition
carries over; turn count, timer and token-spend baseline reset. A goal already achieved or cleared is not restored. Before 2.1.274 a
compacted session lost its goal on resume.

**`/goal clear`.** Exists (goal.md "Clear a goal"; https://code.claude.com/docs/en/commands). Prints `Goal cleared:` plus the
condition, or `No goal set`. Aliases: `stop`, `off`, `reset`, `none`, `cancel`. `/clear` also removes an active goal.

**Can a hook observe it.** NOT FOUND. The docs do not say whether `UserPromptSubmit` fires for built-in commands such as `/goal`.
- hooks.md: `UserPromptSubmit` receives the `prompt` field with the submitted text.
- hooks.md: `UserPromptExpansion` fires when "a user-typed command expands into a prompt", with `expansion_type` `slash_command`
  (skills and custom commands) or `mcp_prompt`. Built-ins are not mentioned, so it probably does not fire for `/goal clear`.
- I saw no goal-specific hook event.
- Needs an empirical test: a logging UserPromptSubmit hook, then run `/goal clear` and `/goal <cond>`.

## 5. Prompt cache TTL

Source: https://code.claude.com/docs/en/prompt-caching, "Which TTL each request gets" and "Choose the TTL yourself".

Main-conversation default:
- Claude subscription within plan usage: one hour.
- Usage credits, API key, or cloud provider: five minutes.
- A subscription that goes over plan usage and draws on usage credits drops to five minutes.
- Everything else (subagents, workflows, teammates, forks, compaction, session titles): five minutes, except a small set of
  server-controlled helper requests that get one hour on subscriptions.

Settings that change it (values `5m` or `1h`; v2.1.242 or later):
- `promptCacheTtl` setting or `CLAUDE_CODE_PROMPT_CACHE_TTL`: main conversation.
- `subagentPromptCacheTtl` setting or `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`: everything else.
- Subagent frontmatter `experimental` `cacheTtl` (2.1.248 or later).
- `ENABLE_PROMPT_CACHING_1H=1` requests one hour for both buckets; `FORCE_PROMPT_CACHING_5M=1` forces five minutes for both and
  wins over the others. `DISABLE_PROMPT_CACHING` (and `_HAIKU`, `_SONNET`, `_OPUS`, `_FABLE`) turn caching off.
- Check with `claude -p "hello" --output-format json` and read `usage.cache_creation` (`ephemeral_1h_input_tokens` versus
  `ephemeral_5m_input_tokens`). `/cost` shows "warm (1h TTL, last activity ...)" (costs page).
- 1h writes cost 2x base input; 5m writes 1.25x (platform prompt-caching docs).

## 6. Git relative worktrees

- Added in **Git 2.48.0**. RelNotes/2.48.0 (https://github.com/git/git/blob/master/Documentation/RelNotes/2.48.0.adoc): worktree
  and repository link to each other "Use relative paths for this linkage", plus "a new repository extension to prevent older Git
  versions from mis-interpreting worktrees created with relative paths". I confirmed 2.47.0, 2.49.0 and 2.50.0 notes have no
  "relative" lines. I did not read notes older than 2.47.
- Controls (git-worktree and git-config docs): `git worktree add|move|repair --relative-paths` / `--no-relative-paths`; config
  `worktree.useRelativePaths` (default false). The flag overrides the config.
- Caveats from the git docs:
  - `worktree.useRelativePaths=true` implies `extensions.relativeWorktrees`, "thus making it incompatible with older versions of
    Git". The extension is set automatically whenever a worktree is created or repaired with relative paths, so any Git older than
    2.48 refuses the repository afterwards.
  - `git worktree repair` rewrites linking files on an absolute/relative mismatch even when the links are valid.
  - Intended for repositories and worktrees moved between locations (containers, mounts); every tool touching the repo then needs
    Git 2.48 or later.
- Claude Code: I did not read https://code.claude.com/docs/en/worktrees for relative-path handling. The only changelog entry that
  combines "relative" and worktree is 2.1.290 (a self-hosted runner failing with "missing but already registered worktree" when the
  sessions folder is a relative symlink), which is a symlink issue, not Git's relative links.

## Not found, plainly

- Explicit statement of which model compacts (inferred only).
- Dollar cost of a 400k compaction (arithmetic only; summary output length undocumented).
- Any idle auto-compaction in Claude Code.
- Whether `UserPromptSubmit` fires for the built-in `/goal clear`.
- An explicit doc sentence that a goal survives in-session compaction.
- Introduction versions of `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `--autocompact` and the
  `autoCompactWindow` setting.
- Scratch copies of the fetched pages: /workspace/untracked/scratch/cc-chg/.
