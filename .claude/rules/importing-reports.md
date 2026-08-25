---
paths:
  - "untracked/hooks-daemon-*"
  - "untracked/hooks-daemon-*/**"
description: How an incoming report becomes tracked source — sanitise before committing, this repo is public
---

# Importing a report from `untracked/hooks-daemon-*`

`untracked/hooks-daemon-*` is the drop point for reports arriving from
elsewhere: field reports from projects that install this daemon, bug reports,
incident write-ups, audit output. You are reading this because you touched one.

**This repository is PUBLIC.** A report written elsewhere describes *elsewhere*,
and importing it publishes it.

## The one rule that is easy to get wrong

**Read the report in full before committing it.** Not skimmed for the argument —
read for identifiers. A report is imported precisely because its reasoning is
worth keeping, and the reasoning never depends on the reporter's names.

This has actually gone wrong: a report was moved into a plan folder and
committed verbatim, carrying another project's playbook filename, its directory
layout, one of its build scripts and an issue number from its tracker. It was
pushed before anyone read it.

## Strip these; keep the reasoning

| Remove                                                      | Replace with                                                 |
| ----------------------------------------------------------- | ------------------------------------------------------------ |
| Filenames and paths from the reporting project              | a generic description (`a playbook`, `the config file`)      |
| Directory layout (`service/`, `apps/app/…`)                 | omit, or a neutral placeholder                               |
| Host, server and service names                              | `host-a`, `host-b` (the existing convention)                 |
| Client / employer / org names                               | `client-a`, `ClientA` (the existing convention)              |
| Branch names, ticket and issue numbers from another tracker | omit — they carry roadmap detail and resolve to nothing here |
| Domain class, table and column names                        | `SamplePolicy`, `FooRule`                                    |
| Quoted user utterances                                      | paraphrase                                                   |
| Real session UUIDs and transcript paths                     | `00000000-0000-0000-0000-000000000000`, or delete the line   |
| Personal home directories                                   | `/home/user`                                                 |

Add a header saying the document has been generalised, so the next reader does
not take it as an account of work in *this* repository.

## Do NOT rely on the automated guards for this

`sensitive_content` (PreToolUse) and the `sensitive_content` / `git_history` QA
checks all match a **configured deny-list plus a secret word list**. They see
only identifiers someone has already enumerated. A report from a project nobody
has listed passes every one of them cleanly — the whole-history sweep has
passed while a leak sat in history.

Those guards exist to stop *recurrence* of known identifiers. Reading the file
is the only thing that catches new ones. If you find a new identifier that is
likely to recur, add it to the deny-list as well as removing it.

## Then give the report one of its two fates

Per the Report Handling rule in `CLAUDE.md`, a report never lingers in
`untracked/`:

1. **Delete it** once the work it describes is done — git history, the
   regression test and the commit message are the durable record.
2. **Track it** — `mv` (not `git mv`; the source is gitignored and untracked)
   into the relevant plan folder as a supporting document, named for what it
   contains (e.g. `ANALYSIS-<topic>.md`, `FIELD-REPORT.md`), and link it from
   that plan's `PLAN.md`.

Prefer tracking over deletion when in doubt — but sanitise first, and never
leave it in limbo.

## Filing a plan from a report

Check nothing already covers it (the `hooks-daemon-plan-dedupe-scout` agent
reads the live plans), then scaffold with `CLAUDE/Plan/mkplan.bash "<name>"` —
hand-creating the folder is blocked, because the number is only claimed when
`PLAN.md` is written.

**Carry the report's nuance into the plan.** A good report often argues
*against* the obvious fix; flattening that into "add the handler it mentions"
throws away the most valuable thing in it. If the report rejects an approach,
record that as a **Non-Goal with its reason**, not as an omission.
