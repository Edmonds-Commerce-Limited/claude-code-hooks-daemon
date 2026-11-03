# Plan 00560: design questions for Phase 1

The code facts in [CODE-FACTS.md](CODE-FACTS.md) do not settle these. Each has a working answer to start from; Phase 1 records the decision in `DESIGN.md`.

- **D1. What counts as consumption.** Working answer: a later tool call in the same session (main thread or any of its sub-agents) names the file as an INPUT. That covers:

  - `Read` of the file;
  - a Bash command reading it as an operand: `git commit -F`, `gh ... --body-file`/`-F`, `mkplan.bash --journal`, `git apply`/`am`, `cat`, `grep`, `jq`, `diff`;
  - an Agent dispatch whose prompt names the file (a brief). The dispatched agent's own `Read` counts too, since it is the same session.

  A Bash write that only appends to the file is not consumption. Read alone must not launder an asset: a review written to scratch and read back once would pass. That is why Goal 6 denies a non-scratch shape at creation, so read-back only ever clears a capture-like file. Phase 1 confirms that the two layers close the gap together.

- **D2. Where the ledger lives and how it is keyed.** Working answer: the session's spend-ledger state, keyed by `session_id`, with `agent_id` recorded per entry, matching Plan 00558 DESIGN.md section 13's evacuation records. A linked worktree has its own `untracked/`, so a worktree's scratch is judged under that worktree's root. Phase 1 decides whether the ledger follows the checkout or the session.

- **D3. How files from earlier sessions are judged.** Working answer: never at Stop; a stop judges only the files its own session created. At SessionStart, a ledger entry from an ended session that is still unconsumed is reported as "unconsumed from session X". A file with no ledger entry (made before the feature, or by a human) is judged by age only.

- **D4. What the scratch-shape allowlist holds.** Working answer: name patterns, configurable, matched under `untracked/scratch/`:

  - message and body files: `commit-msg*`, `*-commit*.txt`, `pr-body*`, `issue-*.md`, `issue-*.json`, `comment-*.md`. Journal bodies have no fixed name (CODE-FACTS.md F9), so they cannot be on this list: either `mkplan.bash` documents a `journal-*.md` convention that this allowlist then holds, or a journal body is admitted at creation and judged only by consumption. Phase 1 decides which;
  - briefs: `brief-*.md`;
  - captures: `*.txt`, `*.log`, `*.out`, and `*.json` read back.

  Registered stores (any file allowed inside):

  - `untracked/captures/`, `untracked/issue-reports/` and `untracked/agent-reports/auto/`;
  - `untracked/worktrees/`, `untracked/qa/` and the daemon's own runtime files. `untracked/qa/` already holds a hand-written report (`00552-full-gate-report.md`), so a store that admits any file would admit that shape too: Phase 1 decides whether a store admits only the files its owning tool writes;
  - Claude Code's `.claude/worktrees/`.

  A `*.patch` or `*.diff` is NOT a scratch shape: that is the evacuation Plan 00558 Goal 12 forbids. Phase 1 settles the list against CODE-FACTS.md F10's prefix counts.

- **D5. Scope of "the ignored root".** Working answer: configured roots, defaulting to `untracked/`. That avoids a `git check-ignore` subprocess on every write; PLAN.md Q3 asks whether to widen it.

- **D6. The tracked counterpart of a saved reply (Goal 3).** Working answer: the dispatch's declared tracked destination exists and is committed, recorded at dispatch time. CODE-FACTS.md F5 shows `untracked/agent-dispatch-registry/` cannot carry it as it stands (keyed by session and name, named dispatches only, overwritten on a repeated name), so Phase 1 either extends it to a per-dispatch key or records the destination elsewhere. A reply whose dispatch declared nothing tracked is listed.
