# Niggles found during the desktop-team liaison session

The open ledger (00474) could not take these: its plan header names issue #59, which is assigned to another account,
so `github_issue_assignment_guard` denies edits to it. Move them there once the owner settles that.

## The flaggable-path deny says to add an exclude glob, but not that it must come last

`rg -il PATTERN -g '!tests/fixtures/cyber-flag/**' -g '*.md' .` was denied by `flaggable_content_channel_guard`,
although it carried the exact exclusion the deny text asks for. The guard is right: in ripgrep a LATER `-g` overrides
an earlier one, so `-g '*.md'` re-includes `.md` files inside the flagged directory (verified in a scratch tree). The
deny text only says "Add `-g '!<dir>/**'`", so a caller who already has the exclusion reads the deny as a false
positive. Fix direction: when the exclusion is present and a later include defeats it, say "move the exclusion after
the include; in rg the last matching glob wins".

## The plan-start advisory demands a failsafe cron that the session has paused

The owner said "do not create any crons", so both declared jobs were paused with `hooks-daemon cron-pause`, and the
stop enforcer accepted them as missing. `mkplan.bash` still drew the plan-start "Recovery-cron setup is part of
executing this plan ... ONLY IF none is listed, create it" advisory. The advisory does not read the session's
cron-pause state that the stop enforcer reads. Fix direction: when `failsafe-recovery` is paused for the session, name
the pause and its reason instead of asking for a CronCreate.

## A quoted heredoc piped to `pingbus say` is scanned by pipe_blocker

`cat <<'EOF' | pingbus say --to ...` with a body mentioning `go test ... | tail` was denied: `pingbus` is not on the
data-receiver allowlist, so the body is scanned. This is the documented conservative default, not a defect;
`pingbus say < file` avoids it. It is listed in case `pingbus` should join the allowlist (it reads stdin as message
text and executes nothing).
