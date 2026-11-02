# N568: the mkroutine/mkplan scaffold-lock race (CI run 41488623264)

Branch `worktree-mkroutine-race`. The full write-up is NIGGLES.md N568. This file holds the evidence.

## Defect found and fixed

`acquire_lock` set `trap release_lock EXIT INT TERM` in `CLAUDE/Routine/mkroutine.bash`, `CLAUDE/Plan/mkplan.bash` and
`src/claude_code_hooks_daemon/install/templates/mkplan.bash`. When bash receives a trapped INT or TERM, it runs the
handler and then resumes the script. So a holder that got a signal removed its lock, went on to allocate a number,
created the folder and exited 0. Two runners then sat inside the critical section together. That gives exactly the CI
signature: both runners exit 0, and both folders are numbered `00001`.

The fix keeps `trap release_lock EXIT`, with `trap 'exit 130' INT` and `trap 'exit 143' TERM`. The EXIT trap then
releases the lock as the script exits. The deployed template was re-synced and `test_mkplan_template_parity` passes.

## Red evidence

`tests/unit/scripts/test_scaffold_lock_signal.py` puts a `git` shim on PATH that blocks on the counter read
(`config --get`), so the holder waits inside the lock. The test checks the lock dir exists, sends the signal, releases
the shim, and then requires a non-zero exit, no numbered folder and no leftover lock.

Against the unfixed scripts it failed 4/4, deterministically:

```
AssertionError: (0, ['00001-signalled-run'], 'mkplan: counter ... unset; ...')   assert 0 == 143
AssertionError: (0, ['00001-signalled-run'], 'mkroutine: counter ... unset; ...') assert 0 == 143
(same pair for SIGINT: assert 0 == 130)
4 failed in 1.14s
```

After the fix, that test plus test_mkroutine_scaffolder, test_mkplan_template_parity and test_mkplan_worktree_lock
gave 30 passed.

## What is NOT confirmed

I have not found what sent the signal on CI. Without a signal the lock holds:

- 100 concurrent pairs pinned to one CPU (`taskset -c 0`): 0 duplicates.
- 12 harnesses × 60 pairs at once on 2 CPUs: 720 pairs, 0 duplicates.
- 20 pairs with `SIGCHLD=SIG_IGN` inherited from Python, and 20 with the default: 0 bad. Bash resets SIGCHLD.
- Only bash 5.2.37 is available here. No other bash version could be tested.

Ruled out:

- **EXIT trap in a subshell.** `x=$(exit 3)`, a function `exit` inside `$( )` and `( exit 0 )` do not run the parent's
  EXIT trap. The trap ran once, in the main PID. So 63a58352d's diagnosis was wrong, though its guard is harmless.
- **Pre-lock work.** Before `acquire_lock`, mkroutine only runs `git rev-parse --show-toplevel`. Nothing touches the lock
  or the counter.
- **git config races.** The second runner's collision guard (`existing=(...00001-*/)`) would have died on the first
  runner's folder. Both folders being numbered 00001 proves the critical sections overlapped, whatever the counter read.
- **The test.** Each run gets a fresh `tmp_path`, and the test sends no signals. The suite routes `killpg`/group kills
  through `tests/signal_safety_net.py`. No daemon code touches `.mkroutine.lock`.
- **The script under contention.** Removing the lock any other way needs an external `rmdir`, and nothing in the repo
  does that.

What would decide it: the two runners' stderr on the next CI failure. The concurrency test used to print stderr only
when an exit code was non-zero. This branch changes it to print both runners' stderr on any failed assertion. `strace -f -e trace=signal` over the pair on a
runner would also settle it. If the next failure shows no signal, the remaining suspects sit outside bash: an external
`rmdir` of the lock, or a filesystem that does not give atomic `mkdir`.
