# py3.11 integration-slow red leg (run 43835672595, attempt 1, job 133191797837)

Verdict: INFRASTRUCTURE / setup step, not a test. No test ran (job ended ~40 s after start).

## Failing step
Step "Run rustup target add x86_64-unknown-linux-musl; bash relay/build.sh; install -D ... untracked/bin/hooks-relay"
(runs after `./bin/hooks-daemon restart`, before pytest). Exact error text, in order:

    info: downloading component rust-std
    strip: .../untracked/relay-build/hooks-relay-x86_64-unknown-linux-musl[.rodata]: invalid operation
    ##[error]Process completed with exit code 1.

`relay/build.sh` line 32 (`strip "$OUT"`, the belt-and-braces strip after `rustc -C strip=symbols`) failed with
binutils `strip` "invalid operation" on the `.rodata` section of the musl binary. `set -e` then aborted the step.
rust-std download took ~10 s (08:59:48 -> 08:59:58), i.e. a fresh toolchain component fetch on that runner.

## Side observations (not the cause)
- Daemon warnings "DAEMON VENV NOT BUILT FOR THIS SOURCE" and "relay binary missing" appear before the step; expected on a fresh runner (the relay is what this step builds).
- Only this one leg failed on the first attempt, so the strip failure is runner/toolchain-intermittent, not deterministic on the tip.

## Known?
- niggles ledgers (CLAUDE/Plan/**/NIGGLES.md): grep for strip / rodata / relay/build / invalid operation found no matching entry (only unrelated Python `.strip()` hits).
- `gh issue list --search "strip rodata invalid operation relay build" --state all`: no results.
=> NEW. A ledger entry should say: "relay/build.sh `strip "$OUT"` intermittently fails on a GitHub runner with
`strip: ...[.rodata]: invalid operation` (musl binary, py3.11 integration-slow, run 43835672595 attempt 1); the
second strip is redundant after `-C strip=symbols`; candidate remedy: make the belt-and-braces strip non-fatal
or drop it, and verify the binary after, rather than trust strip's exit status."

## Re-run (attempt 2) at time of check
`gh run view 43835672595 --json status,conclusion,jobs`: run status in_progress, no conclusion yet; 28 jobs.
The re-run of this leg (job 133209089936, "Full suite / tests py3.11 integration-slow") is in_progress; the
other non-success jobs are the expected skipped ones. Result of this leg not yet known.

Log saved at /workspace/untracked/scratch/py311slow.log.
