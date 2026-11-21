## 02:22 · finding · —

Live-daemon check closed; Task 3.4 drafted, not sent; plan archived.

**Live socket, isolated daemon** (`tests/integration/test_secret_file_guard_seeded_link_reads_live_daemon.py`, commit 2f1c14e80 then the follow-up on branch `plan-00613-finish`). A git repo on `main` commits a seed list holding `conf` in symlink mode and protects `conf/vault.txt` by a project glob. A hand-made `git worktree add` worktree is seeded by the real `seed-worktree` CLI, then a daemon process is started (rooted at the main checkout, and separately at the worktree) and PreToolUse events go over its socket with cwd in the worktree. Observed, both roots: deny for `cat conf/vault.txt`, `cat conf/*`, `grep -r secret conf`, `grep -R secret .`, `rg -L secret`, `find -L . -type f -exec cat {} +`, `tar -chf out.tar .`, `cp -L`, Read, Edit, the Grep tool on `conf`, and a hand-typed `ln -s`/`cp -s` to the protected file (all R-SECRET). Not denied: `cat plain.txt`, `cat conf/plain.txt`, `grep -r secret .` (non-following; its allow against the `grep -R` deny shows the link was judged, not the spelling). 34 cases pass, plus `test_live_probes_are_marked.py`.

**This worktree's own daemon, through the hook entry point.** `bin/hooks-daemon restart` in the worktree (PID 1253944, socket `untracked/daemon-be685870fc74.sock`), then `bin/hooks-daemon probe PreToolUse --file` with cwd the worktree: session `manual-probe-00613-link`, `ln -s ../../../<default vault-pass name> <same>`, answered deny `R-SECRET-BASH-MENTION`; session `manual-probe-00613-control`, `ln -s ../../../README.md readme-link.md`, answered allow. Both session ids appear in this worktree's daemon log, so this daemon answered, not main's. This probe exercises the spelling deny only; link resolution is covered by the isolated-daemon file above.

**Carried exceptions** (not asserted, not fixed here): ledger 00474 N683 (interpreter tree walk/copy), N684 (`fd | xargs`), N685 (`parallel`, two fd options). Confirmed present in `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`, all Open.

**Task 3.4.** Reply drafted in `subagent-reports/261121-peer-reply-draft.md`, UNSENT: the owner sends it. The repo does not record which peer or channel the request came from. The draft flags the open N683 to N685 gaps for the owner to decide how much to disclose, and that the route is in UNRELEASED notes 009 and 019.

Archived on the owner's brief: everything but the outward reply is done, and every success criterion now has evidence.
