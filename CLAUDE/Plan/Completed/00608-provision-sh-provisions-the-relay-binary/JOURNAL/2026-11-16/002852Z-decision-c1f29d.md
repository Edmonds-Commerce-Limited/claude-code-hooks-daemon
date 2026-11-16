## 00:28 · decision · — — provision.sh relay fix is on main (71bc70cfd); follow-ups and the worktree forwarder-test defect remain

The provision.sh relay fix is on main: merge commit 71bc70cfd (00:26 UTC, authored by another session in this repository, not by this one; my own `git merge --no-ff` afterwards was a no-op because the branch was already an ancestor of origin/main).

Evidence before the merge: CI run 43776073561 on the branch tip went green on the re-run of its one red leg (py3.12 integration: two forwarder socket tests). `test_stop_forwarder_exits_2_on_block_with_socket_stdin` reproduces on a detached origin/main worktree, so the branch does not cause it; it passes in the main checkout (7 of 7) and fails in a worktree (1 failed, 6 passed, 14 s). Not a defect of this plan; it needs its own unit (a forwarder socket-stdin test that depends on the checkout being the main one, or a real worktree fault in the forwarder).

Still open in this plan: follow-ups (a) start the relay repair where the daemon starts, (b) log the silent failure branch, (c) show repair state in status, (d) make .venv-bootstrap.result per view; the semgrep-under-uv fault is no longer a gate here (CI ran semgrep). A release is human-gated and has not been cut.
