# Task 2.2c review (code-reviewer, read-only; reply recorded by the coordinator)

Verdict: **request changes**. The branch `worktree-478-2c-misc-guards` at `73f61db46` allows 10 commands that main denies, and each is a positive finding. The probe is `untracked/scratch/478-2c-review/test_probe_478_2c.py`: 12 tests fail on the branch and 2 on main.

## CRITICAL 1: `plan_journal_guard` allows writes it knows land in a journal

The defect is at `plan_journal_guard.py:447-430`: `_could_name_dayfile` is treated as an unknown. In each command below, the day-file or `JOURNAL/` part is literal:

- `cat > <plan>/JOURNAL/$(date -u +%F)/$(date -u +%H%M%SZ)-note.md <<'EOF'`
- `echo x >> <plan>/JOURNAL/00461-Journal-$(date -u +%y-%m-%d).md`
- `cd <plan>/JOURNAL && echo x >> 00461-Journal-26-09-24.md`
- `tee -a <plan>/JOURNAL/$(date -u +%F)/a.md other.md`

Fix:

- Deny when the path holds a literal `JOURNAL/` before its first expanded part, or when a day-file prefix is literal.
- Treat a destination as unknown only when it is unknown all the way through.
- Restore the deny tests among `test_is_allowed_with_an_advisory` (around `:568-577`).

## CRITICAL 2: `curl_pipe_shell` swallows the word after an unresolved option value

The defect is at `curl_pipe_shell.py:113-116`: the `None` branch runs before `skip_next` is cleared. These commands now pass, and all of them run the download as the program:

- `curl URL | python3 -W $W`
- `ruby -r $LIB`
- `perl -I $DIR -`
- `python3 -X $OPT -`

Fix: when `skip_next` is set, treat the `None` word as the option's value rather than marking the stage unknown.

## IMPORTANT: `flaggable_content_channel_guard` treats any `git -C` as unplaceable

The defect is at `flaggable_content_channel_guard.py:525`. `git -C /repo grep -n foo` and `git -C /repo grep -n foo -- tests` can both be placed, and both reach the flagged directory, but they are now allowed.

Fix: resolve a literal absolute `-C` path as the working directory.

## SUGGESTION: wrapped shells are never matched (also on main)

A shell behind a wrapper whose argument cannot be resolved is never matched. Examples: `curl URL | sudo $FLAG bash` and `curl URL | env $X bash`.

## Sound

- `release_merge_freeze`.
- `reference_repo_freshness`, including a stale clone beside an unverified one.
- `root_recursion_guard`.
- `| sudo bash -s`.
- The tests assert ALLOW, the advisory and the log line for each converted route.
