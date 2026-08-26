# Plan 00274 — Skill Opportunity Detector: Brainstorm

Free-form design exploration for a mechanism that tells a project when it is
probably time to create a skill (`.claude/skills/`) — because the same task
keeps being requested, or the same confusion keeps being explained, session
after session. Supporting document for `PLAN.md`; nothing here is a commitment
until promoted into a Technical Decision there.

## 1. The problem in one paragraph

Skills are cheap to create and expensive to *notice you need*. The evidence
that a skill is due — five sessions across three weeks each asking a variant of
"regenerate the docs then restart the daemon and verify" — is spread across
session transcripts nobody re-reads. A detector that periodically mines the
transcripts for repeated workloads and recurring explanations, and files a
report suggesting concrete skill candidates, turns that buried evidence into an
actionable, human-reviewed suggestion. It must never auto-create anything.

## 2. What the transcripts actually look like (verified on this machine)

Inspected live: `/root/.claude/projects/-workspace/*.jsonl` (10 files; the
largest has ~74k lines). Findings from a real file
(`9ea1b09b-….jsonl`, Claude Code v2.1.224):

- One JSON object per line. Session-level records (`type: "last-prompt"`,
  `"mode"`, `"permission-mode"`, `"ai-title"`, `"queue-operation"`,
  `"file-history-*"`, `"system"`) are ignorable. Conversation records carry
  `type: "user"` / `"assistant"` / `"attachment"` plus `timestamp`, `cwd`,
  `sessionId`, `gitBranch`, `isSidechain`, `userType`.
- `type: "user"` records have `message.content` that is EITHER a string (the
  common human-prompt shape) OR a list of blocks. In the sampled file the
  block-shaped ones are overwhelmingly `tool_result` (9,861 of 10,433 user
  records) — tool output echoed back as a "user" turn. **Exclude all
  block-content records except explicit `text` blocks, and treat even those
  with suspicion.**
- `isMeta: true` marks machine-injected user records (230 in the sample —
  command echoes such as `<command-name>` records, hook stdout, etc.).
  **Exclude.**
- `isSidechain: true` marks sub-agent threads. **Exclude** — a sub-agent's
  "user" prompt is the parent agent's instruction, not a human.
- `isCompactSummary: true` / `isVisibleInTranscriptOnly: true` mark compaction
  summaries. **Exclude.**
- After those field-level filters, the sampled file still had 304 string-content
  main-thread non-meta user records, of which only ~184 look genuinely human.
  The residual noise needs **content-level** filters:
  - `<teammate-message …>` / "Another Claude session sent a message" (42) —
    agent-team traffic;
  - `<task-notification>` (44) — background-task wake-ups;
  - `[Request interrupted by user]` and its `…for tool use` variant — UI
    artefacts;
  - `FAILSAFE RECOVERY CHECK` — the recovery cron's canonical prompt;
  - `/goal 🤖 [ccy-supervisor]` — machine-injected goal lines (Plan 00269
    surface; the fixed machine-origin marker makes these mechanically
    excludable);
  - `<command-name>`/`<local-command-stdout>` slash-command echoes (mostly
    already `isMeta`, but belt-and-braces).

**The crux is this two-layer filter (fields first, then content markers), and
it must be a tested, deterministic Python component** — not something Haiku is
asked to do, because sending noise to Haiku is exactly the cost and privacy
leak we are trying to avoid. The filter's marker list should be config-extensible
(`extra_exclude_patterns`) since agent-team wrappers evolve.

Caveat worth recording: the jsonl shape is Claude Code's private format and
version-dependent. The parser must tolerate unknown record types and missing
fields silently (skip, count, report "N records unparseable"), never crash the
scan. A schema-drift canary belongs in the report ("X% of user records matched
no known shape") rather than in a hard assertion.

## 3. Pipeline shape: three stages, only one of them AI

```
[Stage 1: extract]   jsonl files → genuine human prompts (deterministic, tested)
[Stage 2: condense]  dedupe/normalise/cluster + redact (deterministic, tested)
[Stage 3: judge]     bounded Haiku call over the condensed digest → suggestions
[Output]             untracked/reports/YYYY-MM-DD-skill-opportunities.md
```

### Stage 2 — deterministic pre-aggregation (the cost/privacy bulwark)

Sending raw prompts to Haiku is rejected: unbounded token cost, and raw prompts
are the privacy hazard (see §5). Instead:

- **Normalise**: lowercase, strip paths/quoted strings/hashes into placeholders
  (`<path>`, `<sha>`, `<num>`) so "fix test in tests/unit/x.py" and "fix test in
  tests/unit/y.py" cluster together.
- **Cluster without embeddings**: token-set Jaccard similarity (or trigram
  overlap) with a greedy threshold is sufficient for "near-identical repeated
  request" detection and requires zero dependencies. This is a heuristic first
  cut — Haiku's job in Stage 3 is precisely to make the fuzzy calls the
  deterministic stage cannot.
- **Aggregate per cluster**: representative prompt (redacted), occurrence
  count, distinct-session count, distinct-day count, date range. Repetition
  ACROSS sessions/days is the skill signal; 20 repeats inside one session is
  usually just an iterative task.
- **Budget**: cap the digest at `max_prompts` clusters (default ~100) ranked by
  distinct-session count, and truncate each representative to ~200 chars. That
  bounds the Haiku input to a few thousand tokens regardless of transcript
  volume. Windowing: only files whose mtime falls inside
  `transcript_window_days` (default 14) are read at all.

### Stage 3 — the Haiku judgement

Input: the condensed digest + an inventory of existing `.claude/skills/*` and
`.claude/commands/*` names/descriptions (so it never suggests what exists) +
a rubric. Output contract: strict JSON — a list of
`{suggested_skill_name, evidence_cluster_ids, rationale, confidence}` — parsed
defensively; unparseable output degrades to "raw model notes" appended to the
report, never a crash.

Positive signals the rubric names: near-identical repeated requests; repeated
multi-step workflows (same verb sequence); repeated user corrections or
re-explanations ("no, remember you must X first" shapes); repeated references
to the same doc/file. Negative signals: one-offs; clusters already covered by
an existing skill/command or by resident CLAUDE.md guidance; clusters that are
really bug reports (those want a plan, not a skill).

**How to invoke Haiku** — do not re-derive; Plan 00266 Phase 1 already mapped
the mechanisms (`RESEARCH-claude-code-native-hooks.md` §"native vs daemon-side"
comparison table): a daemon-side model call means this project's own code
shelling out to headless `claude -p --model haiku` (reusing the user's existing
Claude Code auth — no separate API key) or calling the Anthropic API directly
(needs `ANTHROPIC_API_KEY`), and it requires new infrastructure: timeout/error
handling, test mocking, cost accounting. 00266 also established
**fail-open as mandatory** for model calls and that latency in a hook path is
unacceptable (~1.2s measured for a native hook vs ~51ms daemon dispatch —
`EXPERIMENTS.md` §5). Both findings shape this design: the model call lives in
a CLI pipeline OUTSIDE any hook path (§4), and every failure (no CLI, no key,
offline, timeout, garbage output) degrades to a logged skip. Preference order:
`claude -p --model haiku --output-format json` first (zero-config for any
Claude Code user), API fallback only if configured. A spike task in PLAN.md
verifies invocation + measures cost/latency before anything is built on it —
00266's rule that per-invocation cost is MEASURED, never estimated, applies.

00274 is thereby the concrete use-case 00266 was waiting on — but note it does
NOT trip 00266's revival conditions (this is not a handler *decision* made by
AI; no hook outcome depends on model output), so 00266 stays Dormant and is
cited as reference, not reopened.

## 4. Architecture: who runs the pipeline?

Options considered for the SessionStart side:

- **(a) Inline in the handler** — rejected outright. Session start must stay
  fast; a multi-second (potentially multi-minute over 74k-line files) scan plus
  a network model call inside SessionStart dispatch violates the daemon's core
  latency premise and 00266's latency findings.
- **(b) Daemon spawns a background process** — workable but adds process
  lifecycle, log, and failure-surfacing machinery the daemon does not have for
  this, and puts the model call inside daemon-owned code paths.
- **(c) Advisory delegation** — the SessionStart handler ONLY checks the TTL
  state file and, when a scan is due, injects an advisory: "a skill-scan is due
  — run `bin/hooks-daemon skill-scan`". The agent (or human) runs the CLI in a
  normal Bash turn. **Chosen.** It matches Plan 00161's report-first
  advisory-delegation pattern exactly, keeps Haiku entirely out of the daemon
  process, makes the pipeline trivially manually runnable (the CLI *is* the
  pipeline), and costs the session nothing when not due (one small file stat).
  Cost: the scan only happens when an agent acts on the advisory — acceptable
  for a ≥weekly cadence, and the advisory can repeat next session if ignored.
  The CLI records "scan completed" in the TTL state on success, so an ignored
  advisory re-fires while a completed scan silences it for the interval.

Statelessness details: TTL state is one JSON sidecar under
`ProjectContext.daemon_untracked_dir()` (never `/tmp` — B108), e.g.
`skill_scan_state.json` with `{last_scan_at, last_report_path, last_result}` —
the exact `version_check.py` cache pattern (`cached_at` + TTL compare,
corrupt/missing file treated as expired, write failures logged and swallowed).
Corrupt state therefore means "scan is due", which fails toward a suggestion,
never toward silence forever.

## 5. Privacy — the load-bearing constraint

Transcripts contain everything the user ever typed, including secrets discussed
in chat, and this repo is PUBLIC, so a report could plausibly be pasted into a
GitHub issue.

- **Only Stage-1-extracted USER PROMPT text ever leaves the transcript.** Tool
  results, assistant output, file contents, hook payloads: never read past the
  type filter.
- **Redaction before Haiku and before the report**: run every representative
  prompt through `utils/secret_redaction.redact_text` with the project's secret
  word list — that module is already the ONE place daemon-owned outputs get
  redacted, and its own docstring notes Claude Code's transcripts are NOT
  redacted at source, which is precisely the gap this closes for our outputs.
  Plus the normalisation placeholders (§3) which strip paths/quoted material.
- **Report style**: summarised clusters with SHORT redacted representative
  snippets, not verbatim prompt dumps. The report template should carry a
  standing header: "derived from private session transcripts — review before
  sharing outside the project". (This is deliberately tighter than
  CREATING_REPORTS.md's "quote, don't paraphrase" default; that guide's rule
  serves diagnostic evidence, and a standing exception for transcript-derived
  content is worth a line in that guide as part of this plan.)
- **What still goes to Anthropic**: redacted, truncated cluster
  representatives. Via `claude -p` this is the same channel the user's own
  sessions already use, so no NEW disclosure surface — worth stating in docs,
  along with the residual risk that redaction is list-based and cannot catch
  unlisted secrets. Config ships with the feature **disabled upstream**; a
  project enabling it is the explicit opt-in.
- Reports live in git-ignored `untracked/reports/` (00161 convention), so
  nothing lands in tracked history by default.

## 6. Config surface (sketch)

```yaml
handlers:
  session_start:
    skill_opportunity_detector:
      enabled: false            # ships OFF upstream; dogfood-enabled here
      options:
        check_interval_days: 7  # TTL floor; never advise more often
        transcript_window_days: 14
        model: haiku            # passed to claude -p --model
        max_prompts: 100        # digest cluster cap (token budget)
        extra_exclude_patterns: []   # content-level noise markers, additive
```

CLI: `bin/hooks-daemon skill-scan [--force] [--window-days N] [--dry-run]` —
`--force` ignores the TTL, `--dry-run` runs Stages 1–2 and prints the digest
without calling Haiku (also the cheap way to eyeball what WOULD be sent —
doubling as the privacy audit tool). The CLI reads the same config block so
handler and CLI cannot drift. Open question: whether the CLI should work with
the handler disabled (leaning yes — manual runs are consent by definition;
`enabled` gates only the SessionStart advisory).

Transcript directory discovery: derive the project slug the way Claude Code
does (project path with `/` → `-`) under `~/.claude/projects/`; overridable via
an option for tests and unusual layouts.

## 7. Failure modes

| Failure                                           | Behaviour                                                                                                                                                                                                                                                                                                                        |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `claude` CLI absent / no auth / offline / timeout | Skip Stage 3, log reason, write a Stages-1–2-only report noting the judgement step was skipped; still update TTL? — NO: leave TTL unset so it retries next interval-due session, but rate-limit the advisory so a permanently-offline box is not nagged every session (record `last_attempt_at` separately from `last_scan_at`). |
| Unparseable Haiku output                          | Append raw output to the report under "unparsed model notes"; suggestions section says so.                                                                                                                                                                                                                                       |
| Transcript dir missing / empty window             | Report "nothing to scan", update TTL (a successful no-op scan).                                                                                                                                                                                                                                                                  |
| Corrupt TTL state                                 | Treated as expired (scan due) — version_check pattern.                                                                                                                                                                                                                                                                           |
| Huge transcripts                                  | mtime windowing + per-file streaming line parse + digest cap; no whole-file loads into memory beyond line iteration.                                                                                                                                                                                                             |
| Schema drift in jsonl                             | Unknown records skipped and counted; canary line in report.                                                                                                                                                                                                                                                                      |

The SessionStart handler itself does file-stat work only and is advisory —
it can never block a session start under any failure.

## 8. Dogfooding

Enable in this repo's `.claude/hooks-daemon.yaml`; the 10 real transcript files
here (spanning weeks of heavy use, including exactly the repeated-explanation
patterns this repo's CLAUDE.md grew to answer) are an ideal evaluation corpus.
Acceptance: run `skill-scan --force` here and review whether suggestions are
sane (e.g. it should plausibly rediscover release/QA/plan-hygiene workflows —
some already skills, which tests the existing-skill suppression, since
`.claude/skills/` here contains `acceptance-test`, `configure`, `mode`,
`optimise`, `release`).

## 9. Open questions for the user

1. Should the CLI run with the handler disabled (manual-only mode)? Leaning
   yes.
2. `claude -p` reuses the user's Claude subscription/auth — is metered API
   fallback wanted at all, or is CLI-only acceptable for v1? Leaning CLI-only.
3. Report retention: one dated file per scan accumulating in
   `untracked/reports/`, or overwrite a `-latest` symlink/pointer? Leaning
   dated files (00161 convention) + the state file remembering the latest path.
4. Should repeated USER CORRECTIONS (the "explaining every session" signal) be
   a distinct report section from repeated WORKLOADS? They suggest different
   remedies (a CLAUDE.md/rules line vs a skill) — leaning yes, and the report
   may legitimately conclude "this wants a doc, not a skill".
5. Cross-project ambition (scanning other projects' transcript dirs from one
   daemon) — out of scope for v1?
