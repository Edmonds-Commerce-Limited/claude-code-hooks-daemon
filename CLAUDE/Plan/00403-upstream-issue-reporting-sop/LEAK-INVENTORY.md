# Plan 00403: the three leaking surfaces, as measured

Findings from reading each reporting path's source, not from reading its
documentation. They are what reordered the plan: Phase 1 became "stop the
bleeding" rather than "write the SOP", because every existing route already
leaked and the documented one leaked worst.

`utils/secret_redaction.py`, whose own threat model says its output "may be
pasted into a bug report", was called by **no reporting path at all**.

| Surface                                                                            | Emits                                                                                                      | Redaction | Where the docs send it                                                             |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | --------- | ---------------------------------------------------------------------------------- |
| `scripts/debug_info.py` — what `BUG_REPORTING.md` actually prescribed              | `.claude/hooks-daemon.yaml` verbatim (`:352-357`) and **`.claude/hooks-daemon.env` verbatim** (`:361-368`) | none      | "Paste the contents of the report file" into a GitHub issue                        |
| `bin/hooks-daemon bug-report` — the real CLI verb, which the guide never mentioned | config verbatim (`cli.py:7167-7172`), `HOSTNAME`/`VIRTUAL_ENV` (`cli.py:7060-7068`), 100 log lines         | none      | —                                                                                  |
| the `report` skill subcommand                                                      | LLM narrative + **session transcript** excerpts (`report.md:53-59`, which warns they are unredacted)       | none      | **the wrong GitHub org** — `anthropics/claude-code-hooks-daemon` (`report.md:204`) |

An `.env` file is a conventional home for credentials. Nothing stopped a client
putting a token in `hooks-daemon.env`, and the guide gave no warning before
telling them to paste the result into a public issue.

The wrong-org link is not merely a broken URL. It pointed a client's
diagnostics at a repository this project does not control, so following the
documentation exactly would have published them to strangers.

## Why the ordering mattered

Each row is a different KIND of failure, and only the first is the one people
expect:

- **`debug_info.py`** did what it was asked to do and the instruction was
  wrong. Fixing the tool alone would have left the instruction.
- **`bug-report`** was undocumented, so nobody had ever reviewed what it emits
  against a threat model. The absence of documentation was the defect.
- **the `report` skill** carried an explicit warning that its content is
  unredacted, immediately followed by a link telling the reader where to post
  it. Both halves were written down; nobody read them together.

The third is the one worth remembering: a warning and an instruction that
contradict each other will be resolved by the reader in favour of the
instruction.
