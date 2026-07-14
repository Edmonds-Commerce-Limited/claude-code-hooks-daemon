# Creating Reports

A **report** is a self-contained markdown file that captures findings,
diagnostics, or suggestions in enough detail that someone else — a teammate, the
public, or another agent — can act on it without needing the original session.

Reports are deliberately **markdown files**, not chat-window summaries, because a
file has **no practical size limit**. That freedom is the point: a good report is
_verbose_. Include the full transcript excerpt, the complete log, the entire
failing test output, the relevant code snippets. Do not trim for brevity — trim
only for relevance.

The [idle housekeeping advisor](../../src/claude_code_hooks_daemon/handlers/user_prompt_submit/idle_housekeeping_advisor.py)
(Plan 00161) produces reports of this shape, but the convention is general —
use it for any finding worth sharing.

## Where reports live

Write reports to an **untracked** directory so they never clutter the tracked
repository but remain easy to find and share:

```
untracked/reports/YYYY-MM-DD-<short-topic>.md
```

`untracked/` is git-ignored and is already an allowed markdown location, so the
`markdown_organization` handler permits reports there without extra config. One
file per report; date-prefix the filename so reports sort chronologically.

## What a report contains

There is no rigid schema, but a useful report almost always has:

| Section          | Purpose                                                                        |
| ---------------- | ------------------------------------------------------------------------------ |
| **Title + date** | One line naming the report and when it was produced.                           |
| **Summary**      | 2–4 sentences: what this is, why it matters, the headline finding.             |
| **Context**      | What was being done, which project/branch/commit, how the report was produced. |
| **Findings**     | The substance — one clearly-headed subsection per finding.                     |
| **Evidence**     | Verbatim logs, transcripts, code snippets, command output. Be exhaustive.      |
| **Suggestions**  | Optional, clearly separated from findings. What _could_ be done, not decided.  |
| **Reproduction** | Exact commands / steps so a reader can verify independently.                   |

Rules of thumb:

- **Report, don't decide.** Surface issues and options; leave choices that are
  the reader's to make to the reader.
- **Quote, don't paraphrase.** Paste the real error, the real diff, the real log
  line. Paraphrase only to add commentary around the evidence.
- **Attribute severity honestly.** Say what is confirmed vs. suspected.

### Skeleton

````markdown
# <Report title>

**Date**: YYYY-MM-DD · **Project**: <name> · **Branch/commit**: <ref>

## Summary

<2–4 sentences: what this is and the headline finding.>

## Context

<What was being done and how this report was produced.>

## Findings

### 1. <finding>

<Description.>

​```text
<verbatim log / output / transcript excerpt — as long as needed>
​```

## Suggestions

- <optional, clearly separated from findings>

## Reproduction

​```bash
<exact commands>
​```
````

## Sharing a report

The same file travels through three channels, no reformatting required:

1. **Agent-to-agent** — hand the file path to another agent (or paste its
   contents) so a specialist can pick up the work with full context. This is the
   dogfooding path: the housekeeping sub-agents write reports that the main
   thread (or a follow-up agent) then acts on.
2. **Colleague / Slack** — attach or paste the markdown. Because it is
   self-contained and evidence-rich, a colleague can act on it without a live
   session. Markdown renders acceptably in Slack and perfectly in most editors.
3. **GitHub issue (public)** — paste the report body straight into a new issue.
   The verbose, evidence-first structure is exactly what maintainers need. For
   this project, see [BUG_REPORTING.md](../../BUG_REPORTING.md) for the issue
   destination and the `debug_info.py` diagnostic that pairs well with a report.

Because the report is a plain file, you can share the _same_ report through all
three channels — no channel-specific rewriting.

## Size is a feature, not a problem

Do not apologise for a long report. A 2,000-line report containing the full
failing-test log and the complete offending function is more useful than a
tidy 20-line summary that forces the reader to reconstruct the evidence. The
file format exists precisely so length costs nothing.
