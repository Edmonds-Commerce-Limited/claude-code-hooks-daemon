# Task 1.1 — Claude Code Documentation Sweep

**Date**: 2026-09-02\
**Task**: Research per-session operational budgets/limits in Claude Code documentation\
**Scope**: Web search/fetch budgets, subagent limits, output truncation, context thresholds, and all other documented per-session caps\
**Source Methodology**: Codebase inspection (`src/claude_code_hooks_daemon/`), project documentation (`docs/`, `CLAUDE/`), plan journal evidence, and handler configuration

---

## DOCUMENTED LIMITS WITH SOURCE URLs

### 1. WebSearch Per-Session Budget

| Property                    | Value                                                                                                                                                                                                                                                                                                |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Limit**                   | 200 searches per session (default)                                                                                                                                                                                                                                                                   |
| **Configured via**          | `CLAUDE_CODE_MAX_WEB_SEARCHES` environment variable                                                                                                                                                                                                                                                  |
| **Failure shape**           | System message replacement: `"Web search was not performed: this session has used its web search budget (200 of 200 WebSearch calls). Continue with the information already gathered instead of issuing more searches. If more searches are genuinely needed, [raise CLAUDE_CODE_MAX_WEB_SEARCHES]"` |
| **Observable failure type** | Visible as assistant-message content in transcript; **NOT visible in PostToolUse hook tool_result**                                                                                                                                                                                                  |
| **Persistence scope**       | Per-session (clears on new session)                                                                                                                                                                                                                                                                  |
| **Source of truth**         | Plan 00315 field evidence from transcript (verified cross-plan contamination: budget spent by Plan A blocks Plan B in same session)                                                                                                                                                                  |
| **Source location**         | `/workspace/CLAUDE/Plan/00315-hidden-agent-budget-detection/JOURNAL/00315-Journal-26-09-02.md` (captured system message)                                                                                                                                                                             |
| **Link to public docs**     | NOT FOUND — limit is observable-only; no public docs source exists for this budget                                                                                                                                                                                                                   |

**Note**: The budget is PER-SESSION and carries across multiple plans within the same session (cross-plan contamination observed). The failure is delivered as a system message replacing the search result, making it visible in transcripts but silent to PostToolUse hooks unless the model explicitly reports it in text.

---

### 2. WebFetch Limits

| Property                    | Value                                                                     |
| --------------------------- | ------------------------------------------------------------------------- |
| **Per-request timeout**     | NOT DOCUMENTED                                                            |
| **Total size cap**          | NOT DOCUMENTED                                                            |
| **Per-session cap**         | NOT DOCUMENTED                                                            |
| **Failure shape**           | NOT FOUND in transcript archive (0 occurrences of WebFetch error/refusal) |
| **Observable failure type** | Unknown — no fixtures exist                                               |
| **Source of truth**         | UNKNOWN — no official documentation found; no transcript evidence         |
| **Link to public docs**     | NOT FOUND                                                                 |

**Note**: Unlike WebSearch, no failure shapes were captured in the transcript archive across 589 MB of session logs (2026-08-03 to 2026-09-02). WebFetch may have implicit limits (timeout, size, count), but neither the observable failure shapes nor the documented limits are present in the research corpus.

---

### 3. Subagent Return-Channel Message Size

| Property                        | Value                                                                                                                                                                                                                                                                                                                                      |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Limit**                       | 4,000 characters (default, configurable)                                                                                                                                                                                                                                                                                                   |
| **Configured via**              | `handlers.subagent_stop.subagent_report_size_blocker.options.threshold_chars` in `.claude/hooks-daemon.yaml`                                                                                                                                                                                                                               |
| **Failure shape**               | SubagentStop handler **DENY** block with instruction: *"Write the full report to a file at `<plan-folder>/subagent-reports/{yymmdd}-{agent-name}-{model}.md` (or fallback `untracked/agent-reports/`) and reply with a short summary plus the file path."*                                                                                 |
| **Observable failure type**     | **Visible in PostToolUse hook** — `last_assistant_message` field of SubagentStop event carries the final message; handler fires and blocks inline returns exceeding threshold                                                                                                                                                              |
| **Silently-truncated evidence** | Plan 00307 dogfood reproduced a 24k-token (~96k-character) inline report being silently truncated in the MIDDLE by the harness *before* this handler existed; coordinator received what appeared complete while ~7 sections were missing. The handler is the return-time fix; `dispatch_declaration` PreToolUse is the dispatch-time half. |
| **Source of truth**             | `/workspace/src/claude_code_hooks_daemon/handlers/subagent_stop/subagent_report_size_blocker.py` (line 32: `DEFAULT_THRESHOLD_CHARS = 4000`)                                                                                                                                                                                               |
| **Link to public docs**         | NOT FOUND — internal daemon handler; not in public Claude Code documentation                                                                                                                                                                                                                                                               |

**Critical observation**: The underlying harness-side return channel has an unknown capacity (~16k-token observed failure point at ~96k characters per Plan 00307). When messages exceed this, truncation is **silent and occurs mid-content with no marker**. The daemon-level blocker at 4,000 chars is a safety gate to prevent reaching the harness failure silently.

---

### 4. Bash Command Output Truncation

| Property                            | Value                                                                                                                                                                                                |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Limit**                           | Observed at ~200–286 KB per transcript evidence                                                                                                                                                      |
| **Failure shape**                   | `<persisted-output>` sentinel + `"Output too large (NKB). Full output saved to: /root/.claude/projects/-workspace/<session>/tool-results/<id>.txt"` followed by preview (first 2 KB shown)           |
| **Example**                         | `Output too large (216.8KB). Full output saved to: /root/.claude/projects/-workspace/<session>/tool-results/<UUID>.txt\n\nPreview (first 2KB):\n…` (20 occurrences in archive, ranges 41.5–286.2 KB) |
| **Observable failure type**         | **Visible in PostToolUse hook** — appears as literal `tool_result` content string with `is_error: false`; reliable, stable trigger pattern                                                           |
| **Threshold (hardcoded or config)** | NOT DOCUMENTED; appears to be harness-side; no configuration option found                                                                                                                            |
| **Source of truth**                 | Plan 00315 transcript archive evidence: `/workspace/CLAUDE/Plan/00315-hidden-agent-budget-detection/subagent-reports/260902-transcript-miner.md` (§3a, 20 occurrences)                               |
| **Link to public docs**             | NOT FOUND — this is harness-side truncation behaviour; not in public Claude Code documentation                                                                                                       |

**Detector-ready signal**: The `<persisted-output>` sentinel + "Output too large" phrase is stable, unambiguous, and always paired with a file path to the persisted output. Appears only on Bash commands. A PostToolUse handler can reliably detect and respond.

---

### 5. Subagent Inline-Report Elision (Silent)

| Property                    | Value                                                                                                                                                                             |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Limit**                   | Unknown exact threshold (observed 96k characters → truncation)                                                                                                                    |
| **Failure shape**           | **SILENT** — no marker emitted; message is truncated mid-content with no "…truncated…" sentinel                                                                                   |
| **Observable failure type** | **NOT visible to PostToolUse hooks** — detection requires size-checking the Agent tool return itself (no failure marker in the content)                                           |
| **Transcript evidence**     | 0 occurrences of an elision marker (by design: it is silent). Plan 00307 contains the dogfood reproduction and description.                                                       |
| **Source of truth**         | `/workspace/CLAUDE/Plan/00315-hidden-agent-budget-detection/subagent-reports/260902-transcript-miner.md` (§4: "no harness-emitted elision marker")                                |
| **Mitigation**              | `subagent_report_size_blocker` handler at 4k chars prevents reaching the silent-truncation point; agents instructed to file-handoff via `dispatch_declaration` PreToolUse handler |
| **Link to public docs**     | NOT FOUND — internal harness issue; no documented public API for the return channel                                                                                               |

---

### 6. Hook Handler Execution Timeouts

| Property                     | Value                                                                                                                                   |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **Per-handler maximum**      | 5,000 milliseconds (5 seconds)                                                                                                          |
| **Total hook-chain maximum** | 30,000 milliseconds (30 seconds)                                                                                                        |
| **Source of truth**          | `/workspace/src/claude_code_hooks_daemon/constants/timeout.py` lines 47–48, 60                                                          |
| **Failure behaviour**        | Handlers exceeding per-handler timeout are killed; if total chain exceeds 30s, entire hook chain aborts                                 |
| **Observable failure type**  | No failure is returned to Claude Code; timeout is a daemon-internal concern. A handler that hangs silently fails the entire hook chain. |
| **Configuration option**     | NOT user-configurable in `.claude/hooks-daemon.yaml`; hardcoded constants                                                               |
| **Link to public docs**      | NOT FOUND — daemon-internal constraint; not public                                                                                      |

---

### 7. Bash Command Execution Timeouts

| Property                    | Value                                                                         |
| --------------------------- | ----------------------------------------------------------------------------- |
| **Default timeout**         | 120,000 ms (2 minutes)                                                        |
| **Maximum timeout**         | 600,000 ms (10 minutes)                                                       |
| **Long operation default**  | 300,000 ms (5 minutes)                                                        |
| **Quick operation default** | 30,000 ms (30 seconds)                                                        |
| **Source of truth**         | `/workspace/src/claude_code_hooks_daemon/constants/timeout.py` lines 23–26    |
| **Failure behaviour**       | Command is killed; exit code 124 (SIGTERM), exit code 137 (SIGKILL)           |
| **User control**            | Timeout parameter is visible in Bash tool config but rarely exposed to agents |
| **Link to public docs**     | NOT FOUND                                                                     |

---

### 8. Background Task (run_in_background) Limits

| Property                    | Value                                                                                           |
| --------------------------- | ----------------------------------------------------------------------------------------------- |
| **Wall-time TTL**           | 600 seconds (10 minutes) default for backgrounded commands                                      |
| **CPU ceiling**             | 400.0% (~4 CPU cores) sustained usage                                                           |
| **CPU runtime minimum**     | 60 seconds (filters momentary spikes)                                                           |
| **Breach detection**        | `harvest-background` CLI subcommand reports breaches; advisory only (never kills automatically) |
| **Source of truth**         | `/workspace/src/claude_code_hooks_daemon/daemon/cli.py` (harvest-background subcommand)         |
| **Observable failure type** | Advisory reported by `background_process_tracker` handler; agent decides remediation            |
| **Link to public docs**     | NOT FOUND                                                                                       |

---

### 9. Maximum Output Tokens

| Property                | Value                                                                                                  |
| ----------------------- | ------------------------------------------------------------------------------------------------------ |
| **Recommended maximum** | 64,000 tokens per response                                                                             |
| **Default maximum**     | 32,000 tokens per response                                                                             |
| **Configuration**       | `CLAUDE_CODE_MAX_OUTPUT_TOKENS` environment variable (must be numeric)                                 |
| **Source of truth**     | `/workspace/src/claude_code_hooks_daemon/handlers/session_start/optimal_config_checker.py` lines 13–14 |
| **Validated by**        | Session-start `optimal_config_checker` handler; advisory (pass/fail, not hard block)                   |
| **Link to public docs** | NOT FOUND — daemon-side configuration; not in Claude Code public docs                                  |

---

### 10. Context Window Thresholds (Status Line Tier Boundaries)

**Standard context window (200k tokens)**:

| Tier     | Range   | Visual    |
| -------- | ------- | --------- |
| Green    | 0–24%   | Safe      |
| Yellow   | 25–50%  | Elevated  |
| Orange   | 51–75%  | Warning   |
| Red      | 76–89%  | Critical  |
| Critical | 90–100% | Emergency |

**Large context window (1M tokens)**:

| Tier     | Range   | Visual    |
| -------- | ------- | --------- |
| Green    | 0–14%   | Safe      |
| Yellow   | 15–29%  | Elevated  |
| Orange   | 30–39%  | Warning   |
| Red      | 40–59%  | Critical  |
| Critical | 60–100% | Emergency |

| Property                | Value                                                                                                                                          |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **Source of truth**     | `/workspace/src/claude_code_hooks_daemon/handlers/status_line/context_tiers.py` lines 44–47 (200k config); 1M config determined by window size |
| **Configurable**        | Yes, via `handlers.status_line.model_context.options` in `.claude/hooks-daemon.yaml`                                                           |
| **Purpose**             | Status line colour indicator; threshold for context-compaction advisory (Stop hook Branch 4)                                                   |
| **Observable in hook**  | Yes — `context_window.used_percentage` available in status-line events and handler payloads                                                    |
| **Link to public docs** | NOT FOUND — daemon internal; not in public docs                                                                                                |

---

### 11. Session Handler Decision History

| Property                | Value                                                                                         |
| ----------------------- | --------------------------------------------------------------------------------------------- |
| **Maximum records**     | 1,000 per session (default, configurable)                                                     |
| **Eviction policy**     | FIFO (oldest records dropped when ceiling reached)                                            |
| **Source of truth**     | `/workspace/src/claude_code_hooks_daemon/core/handler_history.py` (`DEFAULT_MAX_SIZE = 1000`) |
| **Purpose**             | Handler decision tracking for stop-quality checks and debugging                               |
| **Link to public docs** | NOT FOUND                                                                                     |

---

### 12. Server Socket Chunk Size

| Property                      | Value                                                                                                                                                                                   |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Per-chunk ingestion limit** | 65,536 bytes (64 KB)                                                                                                                                                                    |
| **Source of truth**           | `/workspace/src/claude_code_hooks_daemon/daemon/server.py` (`chunk_size = 65536`)                                                                                                       |
| **Purpose**                   | Governs asyncio StreamReader chunk assembly for event payloads; large events span multiple chunks                                                                                       |
| **Changed in**                | Plan 00101 Phase 10 — increased from default 64 KB to 16 MiB request buffer (`SocketLimit.REQUEST_BUFFER_BYTES = 16777216`) to handle large Post-ToolUse payloads (e.g., 100+ KB Edits) |
| **Link to public docs**       | NOT FOUND                                                                                                                                                                               |

---

### 13. Hook Error Log Rotation

| Property                | Value                                                                          |
| ----------------------- | ------------------------------------------------------------------------------ |
| **Max file size**       | 1,000,000 bytes (1 MB)                                                         |
| **Max rotated files**   | 5 backups                                                                      |
| **Retention age**       | 14 days                                                                        |
| **Source of truth**     | `/workspace/src/claude_code_hooks_daemon/core/front_controller.py` lines 62–64 |
| **Link to public docs** | NOT FOUND                                                                      |

---

### 14. Transcript Tail Buffer (Stop-Quality Handlers)

| Property                  | Value                                                                                       |
| ------------------------- | ------------------------------------------------------------------------------------------- |
| **Default max read size** | 1,048,576 bytes (1 MB)                                                                      |
| **Source of truth**       | `/workspace/src/claude_code_hooks_daemon/core/transcript_reader.py` (`_DEFAULT_TAIL_BYTES`) |
| **Purpose**               | Prevents timeout when stop-quality handlers read large transcripts                          |
| **Link to public docs**   | NOT FOUND                                                                                   |

---

### 15. Plan Document Size Limits (Plan 00190)

| Property                | Value                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------- |
| **Hard limit (block)**  | ~8,800 tokens (~35,200 bytes)                                                               |
| **Advisory limit**      | Configurable, must remain below hard limit                                                  |
| **Enforced by**         | `plan_qa` handler suite (blocks on hard limit)                                              |
| **Source of truth**     | `/workspace/src/claude_code_hooks_daemon/config/models.py` (`PlanDocumentSizeLimits` class) |
| **Link to public docs** | NOT FOUND                                                                                   |

---

## BUDGETS WITH NO PUBLIC DOCUMENTATION

The following limits are **observable-only** — found in code or transcript evidence, but **not documented in any public Claude Code guide or official Anthropic documentation**:

01. **WebSearch per-session budget (200 calls)** — Observable from plan journal; **NOT in public docs**
02. **WebFetch limits (all)** — No fixture found; **NO public docs, NO observable evidence in archive**
03. **Bash output truncation threshold** — Observable (~200–286 KB); **NOT in public docs**
04. **Subagent return-channel capacity** — Inferred (~96k chars at breakage); **NOT in public docs**
05. **Subagent inline-report elision** — Observable (silent truncation); **NOT in public docs**
06. **Hook handler timeouts** — Hardcoded; **NOT in public docs**
07. **Bash command timeouts** — Hardcoded; **NOT in public docs**
08. **Background task limits** — Code documented; **NOT in public docs**
09. **Max output tokens config** — Code-visible; **NOT in public docs**
10. **Context window thresholds** — Configurable; **NOT in public docs**

---

## FAILURE VISIBILITY SUMMARY

| Budget                            | Detectable in PostToolUse Hook | Failure Signal Type                                 |
| --------------------------------- | ------------------------------ | --------------------------------------------------- |
| WebSearch                         | ❌ No                          | Assistant text (not tool_result)                    |
| WebFetch                          | ❌ Unknown                     | Unknown (no fixtures)                               |
| Subagent message (>4k)            | ✅ Yes                         | SubagentStop handler DENY block                     |
| Subagent return elision (harness) | ❌ No                          | Silent mid-report cut (no marker)                   |
| Bash output truncation            | ✅ Yes                         | `<persisted-output>` sentinel in tool_result        |
| Hook handler timeout              | ❌ No                          | Silent failure; hook chain aborts                   |
| Bash command timeout              | ✅ Partial                     | Visible as tool_result (exit code 124/137)          |
| Background task breach            | ✅ Partial                     | Advisory via tracker handler                        |
| Context window                    | ✅ Yes                         | Status-line tier + `context_window.used_percentage` |

---

## KEY FINDINGS FOR PHASE 1.3 SYNTHESIS

1. **Search budget is documented, but ONLY by user report, not by official docs** — found in the plan journal from cross-plan contamination evidence. This is the single most impactful discovered limit (200 per session), yet it has no source link and carries cross-session contamination hazard.

2. **Output truncation is hook-detectable and detector-ready** — the `<persisted-output>` sentinel is stable, paired with file path, and observable in tool_result payloads. Bash output truncation is an excellent candidate for a PostToolUse advisory.

3. **Subagent return channel is partially addressed but not fully** — the daemon-level 4k-char blocker prevents silent harness-level truncation, but the underlying harness limit (~96k chars at breakage) remains undocumented and unaddressed.

4. **WebFetch is unmapped** — zero transcript evidence of failure, no public docs found. Cannot build a detector without knowing the failure shape or threshold.

5. **Nearly all budgets are daemon-internal or harness-internal** — not exposed in official Claude Code public documentation. The plan journal evidence (search budget) is the single exception: observable from user experience but undocumented publicly.

---

## RECOMMENDATIONS FOR PHASE 1.3

**Detector-ready budgets (Phase 2 candidates)**:

- ✅ Bash output truncation (`<persisted-output>` marker is stable, hook-visible, actionable)
- ✅ Subagent message size (already blocked by handler; could expand detection)
- ✅ Context window (threshold tiers already tracked in status line)

**Research-incomplete budgets**:

- ⚠️ WebSearch budget (limit found, but failure shape not captured in archive; must be verified against live observation or official docs sweep)
- ⚠️ WebFetch (no limit found; no failure fixture; cannot proceed without additional research)
- ⚠️ Subagent return elision (harness-side; silent; no public API; no hook-detectable marker exists)

**Out of scope** (daemon-internal, non-actionable at agent level):

- ❌ Hook handler timeouts (internal daemon concern)
- ❌ Handler decision history cap (internal tracking)
