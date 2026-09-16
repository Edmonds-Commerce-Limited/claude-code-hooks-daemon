# Security review (delta) — check `D-SEC`

**Routine**: 00002 security review delta, run 2026-001
**Interval**: `v3.63.0..v3.64.0`
**Check answerable**: yes — the diff was produced and read, and no protected
file was opened.

## Provenance of this document — read this first

**This report was RECOVERED FROM THE AGENT'S RETURNED MESSAGE, not written by
its author.** The `security-reviewer` agent type is declared with tools
`Read, Grep, Glob, Bash` and no `Write`, and this dispatch could not persist its
report at all; the findings reached the dispatching agent only as the returned
summary and were transcribed here.

Two consequences a reader must carry:

- **The author could not verify what was persisted.** Nothing below has been
  checked against the evidence by the person who gathered it, so a transcription
  error is possible and would be invisible.
- **It is a summary, not the full report.** Excerpts, the full citation set and
  the reviewer's own confidence wording are lost. What survives is what the
  return message carried.

The cause is recorded as a finding of this run — see "The dispatch defect" at
the foot of this file, and Task 3.4 in
[PLAN.md](../PLAN.md).

## Finding D-SEC-D1 — the issue-filing gate reads any `--body-file` with no protected-path consultation, and echoes its exact size

`src/claude_code_hooks_daemon/handlers/pre_tool_use/issue_filing_gate.py:320-342`,
new in this interval.

The handler reads any file named by `--body-file` on a `gh issue create`,
without consulting whether the path is protected, and echoes the **exact byte
size** when the file exceeds 64 KiB — where `secret-meta` deliberately BUCKETS a
size rather than stating it, precisely so a size cannot become an oracle.

There is no content echo today, and the reason is worth stating because it is
not a guarantee: `provenance.verify_document` happens not to quote the body. A
later change that quotes it would turn an existing unconditional read into a
disclosure with nothing in between to object.

**Class**: a guard reading a path without asking whether the path is protected —
the same shape as D-SEC-1 from the full sweep.

**Confidence**: HIGH that the read occurs; MEDIUM that the size disclosure
matters today, since exploiting it needs a protected file above 64 KiB.

## Correction to the full sweep — and the delta routine's reason to exist

Run 2026-001 of Routine 00001 dismissed the sibling `--body-file` route with:
*"closed by handler ORDER … terminates the chain. Correct today, by alphabet."*

**That reading is wrong, and the diff is what shows it.**
`src/claude_code_hooks_daemon/core/chain.py:465` makes termination conditional:

```
ends_on_restrictive = restrictive and not collect_all
```

With `daemon.chain.collect_all_violations: true` the guard's terminal deny does
**not** stop the chain. The option defaults to False, but
`init_config.py:31` scaffolds it into every generated config, so it is a value
clients actually hold. With it set, both `block-sensitive-content` and the new
`issue-filing-gate` go on to read the file the guard just refused, and
`sensitive_content.py:1136-1138` can put `Matched: <bytes>` into the merged deny
reason.

`priority.py:72-76` claims that ordering within band 14 changes no verdict.
**For this command shape that claim is false.** The full sweep saw one handler
depending on the unstated invariant; this interval added a second.

This is the clearest evidence so far for keeping Routine 00002 beside 00001: a
whole-repository brief judged the route closed, and reading one release's diff
found the condition that opens it.

**Class**: a stated invariant (`band-14 order changes no verdict`) that the code
does not hold, with guards silently depending on it.

## Finding D-SEC-D2 — the GitHub-URL checker re-derives a tree walk and drops its sibling's exclusions

`scripts/qa/check_github_urls.py:112-121`, new in this interval.

It walks `rglob("*")` with hidden directories **included**, does not carry
`.claude/` in `_SKIP_DIRS`, and reads every file whole. Its sibling
`scripts/qa/check_sensitive_content.py:391-394` excludes the daemon config and
the secret word list; this one re-derives the walk and omits that.

The echo is narrow — a path, a line number and a GitHub org — but the READ is
unconditional and happens on every QA run.

**Class**: `asymmetric sibling protection`, already in the register with a
Defence (`scripts/qa/check_declared_invariant_pairs.py`). The two walks are a
candidate row.

**Confidence**: HIGH that the read occurs; LOW that it echoes protected content.

## Detector hypothesis

Two parts:

1. Extend the full sweep's proposed protected-path-read rule to cover
   **stat-derived** values, not only content — a size, an mtime and a mode are
   each an oracle, and `secret-meta` buckets them for that reason.
2. A cheap **declared-pair** check over priority band 14, asserting that no
   handler in the band reads a path a band-mate has already refused. That second
   rule would have caught D-SEC-D1 on the commit that introduced it.

## Why the test suite does not catch these

Each handler's own suite asserts its own contract, and each contract is
satisfied. The band-14 interaction is not in any one handler's fixture, because
a fixture is built from one module's imports — the defect lives in the
RELATION, plus a config option no single handler's tests set.

## Looked at and found clean

- the interval **fixed** a verbatim `.env` dump in `debug_info.py`;
- the new `issue_report/` stack, with its scrubbing and elision, holds up;
- `reference_repos/` captures no remote URLs;
- the 14 new `explain_segment()` surfaces expose no credential source.

## Boundary held

No protected path was opened. No full-only check was attempted: `F-HYG`
(on-disk hygiene of protected material) and `F-PRIV` (what the public surface
has actually disclosed) belong to Routine 00001 and are not answerable from a
diff.

## Not fixed, deliberately

Every finding here is **already shipped in v3.64.0** — the interval ends at that
tag — so none is a regression this release introduces and none blocks the next
one. They are recorded per Defence Before Fix (class, Detector hypothesis, why
the suite misses them) and left unpatched, the same boundary the
`security-downgrade-inventory.yaml` rows are held to.

## The dispatch defect

Routine 00001 step 3 requires each dispatch to state "where to write its
report", and the `security-reviewer` agent type has no `Write` tool. The
contract and the tool list disagree.

Every dispatch in this run hit it. Three reached for a Bash heredoc — the one
write path that routes around the pre-write content guards — and this one lost
its report entirely. Recorded as a finding of the run rather than quietly
worked around.
