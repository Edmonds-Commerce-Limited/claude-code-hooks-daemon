# Callout: waiting on a wrapper's `$!` is now caught

**Plan**: 00363
**Audience**: everyone

`self_matching_process_probe` gained `R-WAIT-ON-WRAPPER-PID`: when a Bash
command backgrounds a job behind a wrapper and then asks about `$!`, that pid
belongs to the wrapper, not the job. `setsid` is denied — it forks and its
parent exits at once, so `kill -0 $!` reports the job finished while it is
still running, which is exactly how the reported incident lost its first
waiter. `nohup sh -c`, `timeout` and `env` are advisory, since whether those
hand the pid on or keep it turns on what they were asked to run. The message names the
three remedies: a pidfile the job writes itself, `pgrep -P <wrapper-pid>`, or
waiting on a log marker. A plain `./job.bash & pid=$!` is untouched — with no
wrapper, `$!` already is the job.
