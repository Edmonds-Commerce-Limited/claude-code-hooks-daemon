# Callout: a subagent's claimed report path must exist

**Plan**: 00446
**Audience**: operators

A new SubagentStop handler, `subagent_report_path_verifier`, ships **enabled**
at priority 8. When a subagent's final message says it WROTE a file and that
file is not on disk, the stop is blocked and the missing path is named.

The incident behind it: a dedupe scout ended its report with
`Report written to:` and a path that was well-formed, matched this project's
filename convention exactly, and named a file nobody ever created. That time
the verdict had also arrived inline, so it cost nothing. What it costs
otherwise is a plan citing evidence at a path that resolves to nothing.

**A coordinator cannot catch this by reading the report**, which is the whole
reason the check lives on the subagent side. A fabricated path looks exactly
like a real one, so there is nothing in the message to inspect; the one moment
at which the claim and the filesystem are both in reach is the subagent's own
stop. This is the same argument `subagent_report_size_blocker` makes, and it
transfers unchanged.

**It is built to under-fire rather than over-fire**, because it blocks a stop
and honest reports cite files constantly. A claim is only recognised when a
past-tense or passive WRITE verb governs the path (`written`, `wrote`, `saved`,
`created`); fenced blocks are stripped before matching, so a `cat some/report.md`
you are showing the coordinator is not a claim; only `.md` paths are judged; and
a path resolving outside the project root is never judged at all. A message that
merely mentions a path it READ, or recommends one the coordinator should create,
passes untouched. Anything unreadable — no message, a non-string message — fails
open.

The deny offers two routes and states the second as equal to the first: write
the file at the path you named, **or** stop without naming a path. Delivering a
short report inline was always legitimate. It also says outright not to create
an empty file to clear the check — an invented report is worse than the claim it
replaces, because it looks like evidence.

Non-terminal, and at 8 it runs ahead of the terminal `subagent_report_size_blocker`
at 15, so a report that is both unwritten and oversized produces both messages in
one stop rather than one per round trip.

**To disable it**:

```yaml
handlers:
  subagent_stop:
    subagent_report_path_verifier:
      enabled: false
```
