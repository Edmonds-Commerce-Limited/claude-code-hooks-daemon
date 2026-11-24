# Decoupling build slice 5: report

Previous handoff: `261124-decoupling-build-slice4.md`. Same branch and
worktree (`plan-00635-host-seat-lane-guard`, PR 250, name historical). Not
merged. Paperwork only; no source change in this slice.

## Done

1. **Release notes** (`CLAUDE/UPGRADES/UNRELEASED/release-notes/`, commit
   `c8a7af637`, then `c1aed71e2`):
   - 102 overstated: "a probe that gives no answer at all keeps the guard
     armed". It now says that holds only in a session that already resolved a
     seat, a bare session is never armed, and a sub-agent is armed only on its
     seat's declared `host` duty and is advised, never denied.
   - 091 carried the same overstatement ("or whose teamchat probe gives no
     answer"). It is now scoped to a session that resolved a seat.
   - 099 and 103 checked: no overstatement (099 already leaves a worker, no
     team and a sub-agent untouched; 103 judges a sub-agent only for a
     declared coordinator seat).
2. **CLAUDE.md `<hooksdaemon>` block**: not hand-edited. It is regenerated on
   the daemon restart after merge; noted in the PR body.
   `test_cli_claude_md_block_is_stale` and `test_claude_md_guidance_coverage`
   pass on the branch as it stands.
3. **Release note 105**:
   `105-team-guards-arm-on-evidence-and-team-guidance-is-opt-in.md`. 104 is
   the highest on `origin/main`; the only other open PR is dependabot, so no
   clash. The holding-area shape tests pass.
4. **Pre-push checklist**, all green, nothing needed changing:
   - `team_seat.teams_in_use` is under `added:` in
     `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`;
   - `scripts/qa/audit_error_hiding.py`: no violations; `test_audit_error_hiding`
     passes; the exclusions file is untouched;
   - `test_session_mode_readers` passes;
   - `scripts/qa/check_declared_invariant_pairs.py`: all 18 rows hold;
   - every touched handler has at least one acceptance test, and no unit test
     asserts an empty acceptance list; the acceptance coverage and the
     touched handlers' unit suites pass;
   - bandit: the only finding is a pre-existing B101 in `cli.py`; every
     `import subprocess` in changed files has `# nosec B404` with a reason;
   - black `--check` and mypy are clean on every changed `.py`.
5. **PR 250** marked ready, body updated. See the PR for the final text.

## Left

Nothing for this build. The coordinator runs the full QA gate and the merge.
