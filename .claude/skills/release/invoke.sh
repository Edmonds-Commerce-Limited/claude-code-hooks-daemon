#!/usr/bin/env bash
# /release skill - prints the orchestration prompt. The procedure itself lives
# in CLAUDE/development/RELEASING.md and is not restated here.

set -euo pipefail

VERSION="${1:-auto}"
# Plan 00359: `accept-wip` is the ONLY way to proceed over in-flight work, and
# it has to be typed by the human on the invocation — silence never proceeds.
WIP_MODE="${2:-}"
SLATE_ACCEPT_FLAG=""
if [[ "${WIP_MODE}" == "accept-wip" ]]; then
    SLATE_ACCEPT_FLAG="--accept"
fi

cat <<PROMPT
# Release Orchestration for Version: ${VERSION}

**The procedure is CLAUDE/development/RELEASING.md. Read its "Pipeline
Overview", "The release state file" and "The Release Pull Request and the
Merge Freeze" now, then follow its numbered steps in order.** This prompt adds
only what depends on this invocation.

## Resuming?

If \`untracked/release-state.json\` exists, a release is already authorised and
in flight: do NOT run Stage 0 again and do not open a second pull request.
Resume from its \`last_completed_step\` per RELEASING.md "The release state
file".

## Stage 0: Slate-Clean Gate (RELEASING.md Step 1a) — before anything else

Run this yourself, in the main thread:

\`\`\`bash
bin/hooks-daemon release-slate-check ${SLATE_ACCEPT_FLAG}
\`\`\`

Read the exit code, not the prose:

- **0** — clean. Write the state file now (RELEASING.md, "The release state
  file"), then continue at Step 1b.
- **2** — something is in flight. **STOP HERE.** Show the human the report
  verbatim and end your turn with \`STOPPING BECAUSE: [awaiting-human] the
  release slate is not clean\`. Do NOT proceed, do NOT ask "shall I continue?".
  The human proceeds, if they choose to, by re-invoking
  \`/release ${VERSION} accept-wip\`.
- **1** — the check could not be made. **ABORT** the release. \`accept-wip\`
  does not rescue this.

## Then: RELEASING.md Steps 1b to 15

- Target version: **${VERSION}** (\`auto\` = the release agent proposes the
  bump from the commits since the last tag, RELEASING.md Step 2).
- The release branch is \`release/<version>\`; every preparation commit goes on
  it, never on \`main\`.
- There is NO local full QA run: the release pull request's CI is the gate
  (RELEASING.md Step 8). Targeted checks are fine.
- Spawn the release agent (\`.claude/agents/release-agent.md\`) with the Task
  tool for the preparation it owns; you orchestrate everything else.
- Acceptance testing (RELEASING.md Step 12) routes each test by the playbook's
  \`Requires Main Thread\` field and batches the rest by \`Recommended Model\`;
  invoke the \`acceptance-test\` skill for it.
- Update \`last_completed_step\` in the state file as each step completes.
PROMPT
