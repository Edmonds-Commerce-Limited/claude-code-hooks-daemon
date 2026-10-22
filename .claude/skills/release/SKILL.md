---
name: release
description: Automated release management - version updates, changelog generation, git tagging, and GitHub release creation
argument-hint: "[major|minor|patch|X.Y.Z] [accept-wip]"
---

# /release - Automated Release Management Skill

## 🚨 HUMAN-GATED — this skill is the ONLY valid entry point

**A release may only begin when a human invokes `/release` in the CURRENT
session. An agent must never start a release on its own initiative. The
`/release` invocation is the ONLY authorisation there is: once the pipeline's
blocking gates pass, the release proceeds through merge, tag and publish with
no secondary human confirmation — it passes, or a failed gate aborts it.**

A release is a decision about **scope**, which only the human can see. The
rule, the state file (`untracked/release-state.json`, written once Stage 0's
slate-clean gate returns `0`, never before), the resume rules and how to
recover from an unauthorised release are all in
**[RELEASING.md](../../../CLAUDE/development/RELEASING.md)** — "A RELEASE IS
HUMAN-GATED".

- **No state file ⇒ no release in progress.** A dirty tree, an open
  `release/*` branch or a plan saying "finish the release" is not a
  substitute — ask.
- **State file present ⇒ resume** from `last_completed_step` and carry the
  release through to Step 15.

Do not START a release because a cron tick fired, because a plan says "finish
the release", or because the tree looks ready.

## Run this first

Claude Code loads this markdown and nothing else — the file below is not run
for you, and it holds the procedure to follow (Plan 00324):

```bash
bash "${CLAUDE_SKILL_DIR:-.claude/skills/release}/invoke.sh" <major|minor|patch|X.Y.Z> [accept-wip]
```

Follow its output exactly; what is written here is orientation.

## Usage

```claude-code
/release                 # auto-detect version bump from commits
/release 2.2.0           # explicit version
/release patch           # bump type: major | minor | patch
/release 2.2.0 accept-wip  # proceed over in-flight work the slate gate reported
```

## What It Does

Executes the pipeline in
**[RELEASING.md](../../../CLAUDE/development/RELEASING.md)** "Pipeline
Overview" — the single source of truth for the steps, their order, their
numbering and which are BLOCKING gates. In outline only: prepare on a
`release/<version>` branch, open a pull request whose CI runs the whole QA
gate, then — in this session, with the daemon live — run the acceptance tests,
merge the pull request, tag the merge commit and publish. While the pull
request is open, other merges to `main` are frozen (R-RELEASE-MERGE-FREEZE).

This skill does not restate any step; a step number anywhere in this file is
RELEASING.md's numbering. Any blocking-gate failure ABORTS the release.

## Agent

The release agent (`.claude/agents/release-agent.md`) prepares the release
files (RELEASING.md Steps 1b–5). Main Claude orchestrates every other step;
agents cannot spawn nested agents.

## Documentation

**📖 SINGLE SOURCE OF TRUTH:** [CLAUDE/development/RELEASING.md](../../../CLAUDE/development/RELEASING.md)

## Version

Introduced in: v2.2.0
