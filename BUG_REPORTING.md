# Reporting a hooks daemon defect

**This is the whole procedure.** Every other document that mentions reporting a
daemon bug points here rather than describing its own version.

File at:
<https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues>

## The one rule: that tracker is PUBLIC and an issue cannot be retracted

Editing an issue leaves the original in its edit history. Deleting it does not
reach the copies GitHub has already served, notified by email and indexed. So
the cost of disclosing something private here is **permanent and yours**, while
the cost of leaving something out is one comment asking for it. Those two are
not comparable, and everything below is arranged around that.

**Never file:**

| Do not include                                          | Why                                                            |
| ------------------------------------------------------- | -------------------------------------------------------------- |
| `hooks-daemon.yaml` or `hooks-daemon.env` in full       | An `.env` file is a conventional home for credentials          |
| Daemon logs, hook payloads, transcript excerpts         | They carry whatever your session happened to be handling       |
| Absolute paths with a username, hostname or client name | They identify you and your customers, permanently              |
| Git remote URLs, internal hostnames, any credential     | A private remote URL is often the client's name and their host |

Where you need a path, write `<project>/src/thing.py`. Where you need a config
value, name the option and give the value only if it is not specific to you.

## Step 1 — check it is really a defect

A defect is a gap between the daemon's BEHAVIOUR and a promise its
documentation makes. Three checks, in the order that eliminates the most
reports soonest:

**Is it configuration?** Most reported bugs are a handler doing exactly what
its configuration asks. `bin/hooks-daemon explain-handler <name>` prints what
that handler honours, and
[docs/guides/HANDLER_REFERENCE.md](docs/guides/HANDLER_REFERENCE.md) has every
option and default. You will be asked which options you ruled out and why each
one is insufficient — finding the answer yourself costs one command, and
finding it out through triage costs you days.

**Read the source.** `src/claude_code_hooks_daemon/` is on your disk, and it is
the only place that settles what the daemon actually does. Cite the line you
read as `file.py:123`. That citation is a lower bound rather than a proof — it
shows you looked, not that you were right — and it is still worth far more than
nothing, because a report from someone who has read the code and a report from
someone who has not need different answers.

**Are you on the latest release?** `bin/hooks-daemon release-notes` names the
version you have in its first heading; `--latest` lists what you would gain and
`--from <yours> --to <latest>` shows everything in between.

**Reporting from an older version is fine** provided nothing in those notes
touched the subsystem you are reporting. If something did, the fix may already
be out, and the report costs you both a round trip — upgrade first:

```bash
TARGET="$(git -C .claude/hooks-daemon describe --tags --abbrev=0)"
bash .claude/hooks-daemon/scripts/upgrade.sh --project-root "$PWD" "$TARGET"
```

Use that entry point rather than `upgrade_version.sh` directly: the inner
script checks out the target mid-run, so invoking it yourself runs the
PREVIOUS release's step list and any step the new release added never
executes.

## Step 2 — generate the report

```bash
bin/hooks-daemon issue-report --fields <file.json>
```

In a client project the daemon lives under `.claude/hooks-daemon/`, so the path
is `.claude/hooks-daemon/bin/hooks-daemon issue-report`.

The fields file is JSON:

```json
{
  "summary": "sed_blocker denies a command containing no sed",
  "expected": "The deny message lists four exemptions; this command matches the fourth.",
  "observed": "Denied with R-SED-COMMAND regardless.",
  "reproduction": "1. echo x > untracked/scratch/probe.txt\n2. Run: grep x untracked/scratch/probe.txt | wc -l\n3. Observe the denial",
  "handler": "sed_blocker",
  "source_citation": "src/claude_code_hooks_daemon/handlers/pre_tool_use/sed_blocker.py:212",
  "config_considered": [
    {
      "option": "sed_blocker.extra_whitelist",
      "why_insufficient": "It whitelists a pipe PRODUCER, and this command has sed in no pipe stage at all."
    }
  ]
}
```

Add `--latest <version>` when you know the newest release, so the currency
check can read the notes between yours and it.

**What it collects is the guarantee.** It gathers the fields above plus your
daemon version, platform and install mode — and it does not gather your
hostname, git remote, environment file, config dump or logs. Those are not
scrubbed out afterwards; they are never collected, which is a promise a
scrub-the-output pass cannot make, because a scrubber only removes what it
recognises.

**It refuses before it writes, and gives every reason at once.** A missing
source citation, a citation that does not resolve in your installed version, a
handler name this daemon does not have, a reproduction naming a path from your
own tree, or no configuration ruled out — each is a refusal, and on refusal no
file is written at all, because a file that exists is a file that can be filed
by mistake.

One refusal looks like a defect and is the rule working: an install BEHIND the
newest release cannot answer the currency question offline, because the release
notes that shipped with it stop at its own version. The remedy is to upgrade.

## Step 3 — read it, then file it

The generator prints the exact `gh issue create --body-file …` command when it
writes the report, with the real filename already in it. Run that rather than
retyping one: the filename is timestamped, and a `--body-file` pointing at a
path that does not exist is a confusing failure from `gh` rather than a clear
one from here.

**Read the report first.** The generator proves the body is the one it built.
It cannot prove the prose YOU wrote inside it is safe to publish — that
judgement is yours, and it is the one thing no check makes for you.

Do not edit the generated file. It carries a digest of its own body, so an edit
is refused — which is exactly the failure this catches: a clean report,
edited to paste in "just the relevant bit of the log", and filed. Extra detail
belongs in the `reproduction` field, where the checks still run over it.

In a client project, `gh issue create` against this repository is DENIED unless
`--body-file` names a generator-produced document
(`R-UPSTREAM-ISSUE-UNVERIFIED-BODY`). Issues on your own repository are
untouched, and so are `gh issue comment`, `list` and `view` anywhere.

## If you cannot run the generator

Use the **Daemon defect** issue form in the browser. It asks for the same
fields and carries the same rule about private material — it just cannot refuse
anything, so the checks in Step 1 are yours to do.

That is the route for a machine without the install, a defect that stops the
CLI itself, or anyone reporting from outside a project.

## Before you open an issue at all

**The daemon is not misbehaving; it will not start, or hooks are not firing.**
That is [docs/guides/TROUBLESHOOTING.md](docs/guides/TROUBLESHOOTING.md) — a
known-failures guide, and it resolves most of these without an issue.

**You are inside a client project and found the bug in daemon source.** Do not
fix it there. `src/` and `tests/` under `.claude/hooks-daemon/` are an upstream
dependency: an edit is overwritten by the next upgrade and blocks the one after
it. Write the report to `untracked/scratch/` — inside the working tree, so it
survives a container restart, and gitignored, so it never reaches review — and
follow the steps above.

## If you have a fix

Write the failing test first, then the fix, then run
`./scripts/qa/llm_qa.py all`. Open the issue as well as the pull request: the
issue is where the behaviour is agreed, and the pull request is where the
change is reviewed.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution workflow.
