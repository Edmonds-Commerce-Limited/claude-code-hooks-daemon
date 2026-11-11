# Plan 00600 research: scanning human prompts at UserPromptSubmit

The owner asked whether the daemon should scan what a HUMAN types, and warn on or block a prompt that is clearly not
optimal. This document answers with evidence from three sources: Anthropic's two prompting guides, the vendored Claude
Code hooks contract, and the daemon's own UserPromptSubmit handlers. Citations use `path:line` in this repository.

**Short answer: a narrow GO.** Three deterministic detectors are worth building, all advisory by default. One of them
(pasted credentials) has an opt-in block. A general "prompt quality" judge is a NO-GO: the defects that matter most
need a model's judgement, and the agent that receives the prompt is already that model.

## Sources

- Anthropic, "Prompting best practices" (WebFetch of
  `platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices`). Relevant
  sections: "Be clear and direct", "Add context to improve performance", "Long context prompting", "Tool usage",
  "Balancing autonomy and safety".
- Anthropic, "Prompting Claude Fable 5.2" (WebFetch of `.../prompting-claude-fable-5-2`), section "Approvals".
- Vendored hooks reference: `remote-docs/code.claude.com/docs/en/hooks.md` (fetched 2026-11-10), section
  "UserPromptSubmit" (lines 1526-1609), output caps (line 1100), timeouts (line 450), prompt-based hooks (line 3982).
- Vendored contract: `contracts/claude-code-hooks/UserPromptSubmit.json` and `ALLOWLIST.yaml` (audited against
  Claude Code 2.1.296, `contracts/claude-code-hooks/META.json`).
- Daemon handlers in `src/claude_code_hooks_daemon/handlers/user_prompt_submit/`, the Plan 00501 classifier
  (`src/claude_code_hooks_daemon/utils/session_modes.py:502`), the Plan 00274 transcript tooling
  (`src/claude_code_hooks_daemon/skill_scan/`), and `CLAUDE/HANDLER_DEVELOPMENT.md`.

## What the guides actually say about the human's side

Both guides are written for people who author prompts. Most of their advice is about system prompts, not about a
person typing at a terminal. Four points do apply to a typed prompt:

1. **Name the action, not "continue".** Fable 5.2 guide, "Approvals": "When you tell the model to keep going, say
   clearly what you want from it instead of sending a bare 'continue.' For example, reply 'Yes, run the migration on
   the staging database' where you might have sent 'go' or a thumbs-up." This is the only advice in either guide
   that is specifically about the human's reply.
2. **Be explicit about whether to act.** Best practices, "Tool usage": "If you say 'can you suggest some changes,'
   Claude will sometimes provide suggestions rather than implementing them, even if making changes might be what you
   intended."
3. **Be specific; give the reason.** Best practices, "Be clear and direct": the "key test" is to "show your prompt to
   a colleague with minimal context ... If they'd be confused, Claude will be too." "Add context": giving the
   motivation lets "Claude ... generalize from the explanation."
4. **Long inputs: data first, query last.** Best practices, "Long context prompting", for inputs of "20k+ tokens":
   "Place your long documents and inputs near the top of your prompt, above your query", and "Queries at the end can
   improve response quality by up to 30 percent in tests."

Two observations follow. First, point 3 (clarity) is a semantic property: no regex can apply the "colleague" test.
Second, the guides themselves expect the MODEL side to handle ambiguity. The best-practices guide offers system-prompt
blocks for both directions (`<default_to_action>`: "If the user's intent is unclear, infer the most useful likely
action and proceed, using tools to discover any missing details"; `<do_not_act_before_instructions>`: "When the
user's intent is ambiguous, default to providing information"). The guide places the fix for ambiguity in the
agent's instructions, not in a filter on the user.

## Q1. Which defects are deterministically detectable and worth acting on

### Local measurement (cheap, no tokens)

A throwaway probe (deleted before commit) read the local transcripts in this container. It used the same
genuine-human filter markers as `skill_scan/constants.py:29` and printed counts only, never prompt text. The sample
is small, so these numbers are anecdotal:

| Measure                                                          | Count              |
| ---------------------------------------------------------------- | ------------------ |
| Genuine human prompts                                            | 22                 |
| Bare approvals (`continue`, `go`, `yes`, `ok`, punctuation only) | 2                  |
| Shorter than 80 characters                                       | 8                  |
| Longer than 4,000 characters                                     | 1 (longest 10,567) |
| Longer than 20,000 characters                                    | 0                  |
| Matched a known credential prefix                                | 0                  |
| "can you suggest" phrasing                                       | 0                  |

The corpus is too small to set thresholds. Phase 1 of the plan therefore measures on a larger corpus before any
detector ships (see Q4).

One finding needs no corpus. The daemon's OWN ccy supervisor types the shape the Fable guide warns against: its
post-compaction resume line is the bare word `continue` (`.claude/ccy/claude-supervise.py:7434`, `_CONTINUE_BODY`).
That line is machine traffic, so a human-prompt scanner would skip it. But it is the cheapest instance of the defect
to fix, because the daemon controls the text.

### Candidate list

"FP risk" is the chance that a match is NOT a defect worth a message. "Mechanism" is what the detector would emit.

| #   | Defect                                                                                                                    | Deterministic?                                | How                                                                                                                                                                                                                    | FP risk                                                                                                                                                                                     | Worth acting on?                                                                                                                                                                                                                                                                                                                                       |
| --- | ------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D1  | Bare approval ("continue", "go", "yes", "ok", a thumbs-up)                                                                | Yes, plus one transcript read                 | Whole prompt matches a short closed word list; then read the last assistant message from the transcript tail                                                                                                           | **High on its own**: most bare "yes" replies answer a single clear question. **Low** when gated on the last assistant turn offering two or more options, or naming a destructive step       | **Yes, gated.** Advisory to the AGENT: state in one line which action you are taking; if the last message offered several options or a risky step, ask which. This is exactly the Fable "Approvals" case, and the existing critical-thinking nudge never fires on it because it skips prompts under 80 characters (`critical_thinking_advisory.py:17`) |
| D2  | Pasted credential                                                                                                         | Yes                                           | Reuse the existing patterns: `strategies/security/secret_strategy.py` (AWS, GitHub, Stripe keys, private key blocks), the `sensitive_content` public patterns and the secret word list via `utils/secret_redaction.py` | **Low** for prefixed tokens and `BEGIN ... PRIVATE KEY` blocks; **medium** for generic `sk-...` shapes. Intent FP is higher: a human often pastes a token on purpose ("put this in `.env`") | **Yes.** See Q2 for why the default is a visible warning, not a block                                                                                                                                                                                                                                                                                  |
| D3  | An ask that a daemon guard will refuse ("run `git reset --hard`", "squash merge it", "use sed to ...")                    | Yes, for commands in backticks or code blocks | Extract inline code spans and fenced blocks; dry-run each through the PreToolUse Bash handler chain as a synthetic `Bash` tool input. This reuses the real guards, so the detector cannot drift from them              | **Medium**: the human may be DISCUSSING the command ("why did the guard block `git reset --hard`?"). Prose asks ("throw away my changes") are not caught at all                             | **Yes, advisory.** It saves a round trip: today the agent tries, is denied, then tells the human to run it by hand. The advisory can tell the agent up front which rule will refuse, and that the human can run it with the `!` prefix                                                                                                                 |
| D4  | Very long unstructured paste                                                                                              | Yes                                           | Length over a threshold; Claude Code already wraps pastes in `<pasted_content id=...>` lines (`hooks.md:1552`), so "query before data" is checkable                                                                    | **Medium**. And the advice ("data first, query last") is about 20k+ token inputs, which the local sample never reached                                                                      | **No.** The agent cannot restructure a prompt it has already received, and a lecture to the human on prompt layout is paternalism for an effect measured only on very large inputs                                                                                                                                                                     |
| D5  | "Can you suggest" when the human means "do it"                                                                            | Yes (regex)                                   | Phrase match                                                                                                                                                                                                           | **High**: often the human does want suggestions only                                                                                                                                        | **No.** The model already applies the project's action default; a nudge could push it to change files the human only wanted advice on                                                                                                                                                                                                                  |
| D6  | A request that names no target ("fix it", "make it work")                                                                 | Partly                                        | Short prompt, deictic pronoun, no path, symbol or identifier                                                                                                                                                           | **High**: the referent is almost always in the previous turn                                                                                                                                | **No as a detector.** Whether "it" is clear depends on the conversation, which is a judgement                                                                                                                                                                                                                                                          |
| D7  | Contradictory or unscoped instructions ("don't touch any files, but fix the bug"; a prompt that conflicts with CLAUDE.md) | No                                            | Needs semantic comparison                                                                                                                                                                                              | n/a                                                                                                                                                                                         | **No as a detector.** LLM-only; see Q3                                                                                                                                                                                                                                                                                                                 |
| D8  | XY problem; a suboptimal approach                                                                                         | No                                            | Needs domain judgement                                                                                                                                                                                                 | n/a                                                                                                                                                                                         | Already covered by `critical_thinking_advisory`, which samples about one long prompt in fifteen to twenty                                                                                                                                                                                                                                              |

Only D1, D2 and D3 pass both tests: deterministic with acceptable precision, and an action that changes an outcome.

## Q2. Blocking versus warning: what UserPromptSubmit can do

### Capabilities (Claude Code 2.1.296 contract, vendored hooks reference)

| Capability                                            | Available?                                                                                                                                               | Evidence                                                                                                                                                                                      |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Block the prompt                                      | Yes: `decision: "block"` or exit 2                                                                                                                       | `hooks.md:1580-1590`; contract `block_mechanism: top-level-decision`                                                                                                                          |
| Block reason reaches the model                        | **No**. "`reason`: Shown to the user ... Not added to context"                                                                                           | `hooks.md:1585`; contract `notes`                                                                                                                                                             |
| Add context for the model                             | Yes: `additionalContext`, injected as a system reminder, no visible transcript entry                                                                     | `hooks.md:1576-1578`                                                                                                                                                                          |
| Warn the human without blocking                       | Yes: universal `systemMessage`, "Warning message shown to the user"                                                                                      | `hooks.md:1117`; contract `top_level_output_fields`. The daemon does not emit it on this event yet (`ALLOWLIST.yaml:94`, "no daemon feature emits ... systemMessage ... on UserPromptSubmit") |
| Rewrite the prompt                                    | **No.** There is no `updatedPrompt` field. Only PreToolUse has an input rewrite (`updatedInput`)                                                         | `HANDLER_DEVELOPMENT.md` tier table; contract field list                                                                                                                                      |
| Keep a blocked prompt's text out of the block message | Yes: `suppressOriginalPrompt: true`. The daemon has no carrier for it yet                                                                                | `hooks.md:1588,1607`; `ALLOWLIST.yaml:61`                                                                                                                                                     |
| Output size                                           | 10,000 characters per string, then spilled to a file with a 2,000-character preview                                                                      | `hooks.md:1100,1196`                                                                                                                                                                          |
| Time budget                                           | 30 s default for command hooks on this event. On timeout the output is discarded and the prompt goes through. The hook blocks the model until it returns | `hooks.md:450,1538-1540`                                                                                                                                                                      |
| Fires on non-human traffic                            | Yes: scheduled tasks, `/loop`, background subagent reports, cross-session messages                                                                       | `hooks.md:1532-1536`                                                                                                                                                                          |
| Slash commands                                        | Arrive as typed (`/deploy staging`), not expanded                                                                                                        | `hooks.md:1567`                                                                                                                                                                               |

### What a block costs

- **The human's turn is spent.** The prompt never reaches Claude. When a block coincides with an interrupt, "the
  text doesn't return to the input" (`hooks.md:1548`). For a plain block the reference documents only that the
  block message ends with `Original prompt:` and the text (`hooks.md:1607`), so recovery means copying it back from
  there. With `suppressOriginalPrompt` set, not even that copy exists, and a long prompt must be re-typed or found in
  the prompt history. Phase 1 should confirm the plain-block behaviour live before a block ships.
- **A block does not keep a secret off disk.** "The submitted text can still appear in local files such as the
  session transcript and your prompt history, so a blocking hook isn't a way to keep a secret off disk"
  (`hooks.md:1609`). By default the block message itself ends with `Original prompt:` and the full text, written to
  the transcript (`hooks.md:1607`). A credential block without `suppressOriginalPrompt` therefore writes the secret
  into the transcript a second time.
- **What a block does buy** for a credential: the text never reaches the model API, never enters the context that
  compaction summarises and carries forward, and so can never be copied by the agent into a file, a commit or a
  `gh` body.
- **Precedent.** The daemon already blocks human prompts in one case: `usage_pause_gate.py` holds every prompt while a
  usage pause is live. It does so only with a typed human override (`! bin/hooks-daemon usage-pause clear`) and with
  re-validation so a stale record cannot lock the owner out. It also notes that a block "reaches the USER only and
  is never added to the model's context" (`usage_pause_gate.py:9-12`). Any new block should meet the same bar.

### Testing the owner's expectation

The expectation was: advisory context to the model, never a silent block, with an opt-in hard block for a few narrow
classes such as pasted credentials. The evidence supports it, with two corrections:

1. **Advisory to the model alone is not enough for credentials.** `additionalContext` is invisible to the human
   (`hooks.md:1578`). If a key was pasted by accident, the person who must rotate it is the human, and only
   `systemMessage` reaches them. The default for D2 should therefore be a visible `systemMessage` warning plus an
   `additionalContext` instruction to the agent (treat the value as a secret; never write it into a tracked file,
   commit or log; suggest rotation if the paste looks accidental). D1 and D3 stay agent-only.
2. **The opt-in block must set `suppressOriginalPrompt`.** Without it, the block echoes the credential into the
   transcript. That needs a new `HookResult` carrier, which `ALLOWLIST.yaml:61` already anticipates ("add a
   HookResult carrier when a feature does").

A "silent" block is impossible in any case: the human always sees the block `reason`. The real risk is a block whose
reason does not say how to proceed. Every block must name the detector, the class matched (never the matched text),
and the way through (resend with the value redacted, or turn the option off).

## Q3. Mechanism: deterministic handler, model call, or agent nudge

| Mechanism                             | Latency per prompt                                                                                                                                                   | Token cost                                                          | Fit                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Deterministic daemon handler**      | About 1-5 ms per handler match on a warm daemon (`CLAUDE/ARCHITECTURE.md`, Benchmarks); one transcript-tail read for D1                                              | Zero, except the advisory text when it fires                        | D1, D2, D3. Same pattern as every existing UserPromptSubmit handler                                                                                                                                                                                                                                                                                                                                                         |
| **Model call inside the daemon**      | Seconds, inside a 30 s budget that discards all daemon output on timeout (`hooks.md:1540`). A slow judge would also drop the OTHER handlers' context for that prompt | One small-model request per human prompt                            | **Rejected.** The daemon has no model client, and the project already decided against a headless model shell-out (Plan 00274 Decision 9, cited in `skill_scan/pipeline.py:3-6`)                                                                                                                                                                                                                                             |
| **Claude Code `type: "prompt"` hook** | A background-model round trip before every prompt (`hooks.md:4026-4032`)                                                                                             | One request per prompt, outside the daemon's config, logs and tests | **Rejected as a default.** It cannot be gated by the genuine-human classifier, so it would also judge every cron tick and subagent report. Could be documented as a do-it-yourself option for owners who want it                                                                                                                                                                                                            |
| **Context nudge to the agent**        | Zero                                                                                                                                                                 | A sentence or two when it fires                                     | **Preferred for every LLM-judgement class (D6, D7, D8).** The agent is already a capable model reading the prompt with full conversation context. A short nudge ("if the target or scope is unclear, ask one clarifying question before acting") costs a few tokens. `critical_thinking_advisory.py` is the working precedent: three gates (length, cooldown, 20 % random) keep it to about one prompt in fifteen to twenty |

The deterministic detectors and the nudge are complementary. A detector supplies a FACT the model does not have
(this command will be refused; this string is a credential; your last turn offered three options). The nudge supplies
a disposition (push back, ask). No detector should try to supply the disposition, and no nudge should try to detect.

One gap in the existing nudge is worth closing: `critical_thinking_advisory` cannot fire on a short prompt
(`_MIN_PROMPT_LENGTH = 80`). That gate is right for its general message but means the bare-approval case D1 is never
covered. D1 fills that gap with a narrower, fact-bearing message instead of loosening the gate.

## Q4. Test design: how would we know it helps

All of this can be measured offline, on recorded transcripts, with no model calls.

**Corpus.** The Plan 00274 extraction (`skill_scan/extraction.py`, `extract_prompts`) already reads every transcript
in a window and keeps only genuine human prompts, using the same markers as the Plan 00501 classifier. It redacts
through `utils/secret_redaction.py`. Extend it, or reuse its iterator, so that each human prompt is paired with:
the assistant message before it (for D1) and the next assistant turn after it.

**Stage A: precision replay (zero tokens).** Run each detector over the corpus and report, per detector: match count,
match rate per hundred human prompts, and a sample of matches for a human to label (shown locally, never written to a
tracked file). A detector ships only if a labelled sample shows precision at or above an agreed bar (proposed: 90 %
for D2, 80 % for D1 and D3). This alone settles the thresholds the local sample could not.

**Stage B: outcome proxies (zero tokens, historical).** For prompts each detector WOULD have flagged, measure from
the transcript what happened next, compared with unflagged prompts of similar length:

- D1: how often the next assistant turn did something other than the last option it offered, or the human's next
  prompt was a correction ("no, I meant ..."), an interrupt (`[Request interrupted by user`), or an Esc-and-retype.
- D3: how often the next turn contains a PreToolUse deny from the rule the detector predicted, followed by "please run
  it yourself". This is the round trip D3 would remove.
- D2: how often a flagged credential later appears in a tool input (Write, Edit, Bash) in the same session.

If the flagged group shows no more rework than the unflagged group, the detector has no outcome to improve, and it
is dropped even if it is precise.

**Stage C: live A/B after shipping (zero extra tokens beyond the advisories).** With the handler on, assign by session
id parity whether the advisory is emitted or only logged as "would fire". Compare the Stage B rework proxies, plus
the count of clarifying questions the agent asks after a flagged prompt (an assistant turn that ends with a question
and makes no tool call). Count the human's corrections, not the agent's questions alone: more questions is not
better unless corrections fall.

**Not run here.** No experiment that spends model tokens was run. The only measurement was the local count above.

## Q5. Risks

| Risk                               | Detail                                                                                                                                                                                                                                                                                                                                                                                                          | Mitigation                                                                                                                                                                                                                                            |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Paternalism**                    | A tool that lectures the human on how to write prompts is irritating and will be turned off. The guides' own advice for ambiguity is aimed at the model, not the user                                                                                                                                                                                                                                           | Nothing is said to the HUMAN except for D2 (a possible leaked secret is the human's problem to fix). D1 and D3 speak only to the agent. No "prompt score", no style advice                                                                            |
| **Privacy of prompt text in logs** | The verdict log records no prompt text today (fields: ts, session, event, handler, verdict, rule, mode). Payload capture, if enabled, writes raw `hook_input`. `utils/secret_redaction.py:15-20` records that Claude Code's transcripts are never redacted by the daemon                                                                                                                                        | A detector logs its id, the class matched and the prompt length, never prompt text and never the matched span. Context and `systemMessage` text name the CLASS ("an AWS access key shape"), never the value. A D2 block sets `suppressOriginalPrompt` |
| **Interaction with Plan 00501**    | The genuine-human classifier (`session_modes.py:502`) decides which prompts renew focus and clear BLOCKED. The scanner must use the SAME classifier so that cron ticks, supervisor lines, task notifications and teammate messages are never judged. A block of a human prompt must not count as the human prompt that clears BLOCKED, or a blocked credential paste would silently end the awaiting-human mode | Gate every detector on `is_genuine_human_prompt`. Add a test that a D2 block leaves the session's modes unchanged. Skip prompts that start with `/` (slash commands, `hooks.md:1567`) and with the `hooks-daemon focus` trigger                       |
| **Fail-open**                      | The daemon's rule is that infrastructure failure never blocks work (`CLAUDE/ARCHITECTURE.md:670`). A missing, null or non-string prompt, an unreadable transcript tail, or a regex error must all ALLOW with no context. This is not a statement about guards (`ARCHITECTURE.md:872`), and D2's opt-in block is a guard, so the block fires only on a positive match, never on an error                         | Same `isinstance(prompt, str)` check as `critical_thinking_advisory.py:76`. D1 without a readable transcript tail emits nothing rather than the ungated version                                                                                       |
| **Latency and the 30 s budget**    | A timeout discards ALL the daemon's UserPromptSubmit output for that prompt, including usage-pause directives and standing authorisations                                                                                                                                                                                                                                                                       | D1's transcript read is bounded to the tail. D3's dry-run is bounded to a few code spans and runs only Bash-matching PreToolUse handlers. No model call                                                                                               |
| **D3 false advisories**            | A human discussing a blocked command is told it will be refused                                                                                                                                                                                                                                                                                                                                                 | Advisory wording states a fact ("the guard R-... refuses this command if run"), not an accusation, and tells the agent to proceed normally if the human was only asking about it                                                                      |
| **Self-feedback**                  | A daemon advisory that quotes a command could be re-scanned as a prompt                                                                                                                                                                                                                                                                                                                                         | Advisories are context, not prompts; the supervisor marker and tick sentinels are already excluded by the classifier                                                                                                                                  |

## Recommendation

**GO, narrowly.** Build one handler, `prompt_facts`, with three detectors, each with its own enable flag:

- **D1 gated bare approval**: agent-only advisory, default on.
- **D2 pasted credential**: `systemMessage` to the human plus agent advisory, default on; opt-in block with
  `suppressOriginalPrompt`, default off.
- **D3 command a guard will refuse**: agent-only advisory, default on.

Each ships only after it passes the Stage A precision bar and shows a Stage B outcome difference. Separately, change
the supervisor's post-compaction `continue` to name the action, because the daemon controls that text and the Fable
guide's advice applies to it directly.

**NO-GO** on a model-backed quality judge, on prompt rewriting (the event cannot do it), and on any style feedback to
the human (D4, D5). The judgement classes (D6, D7, D8) stay with the agent through the existing critical-thinking
nudge.
