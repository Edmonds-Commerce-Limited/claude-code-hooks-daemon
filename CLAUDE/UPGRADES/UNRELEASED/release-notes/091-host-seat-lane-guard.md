# Callout: a teamchat seat with duty host is told not to run tests, builds, linters or QA

**Plan**: 00635
**Audience**: operators

The new `host_seat_lane_guard` handler (priority 21, `R-HOST-SEAT-LANE`) watches sessions that hold a teamchat seat whose duty is `host` in any team, or whose duty cannot be read. When such a session runs a test, build, lint or QA command (`pytest`, `npm test`, `make test`, `cargo build`, `ruff`, `mypy`, `llm_qa.py`, a `run_tests.sh`-style script, also through `sh -c`, `uv run`, `nice`, `timeout` or a trailing `&`), it is refused with a message naming the lane: host seats are for deployment and triage, so run it in a worker seat. Installs, `docker compose`, `make deploy`, log tails and other deployment or triage commands are never refused. A session with no team seat is unaffected and never runs the probe; worker and coordinator seats are unaffected.

It ships in `mode: advise`, which only adds the refusal as context; `mode: block` denies. Promote to `block` once the owner rules on it after a live check in a host-duty seat. `extra_lane_patterns` adds project-specific test or build commands.

The shared long-running classifier also now reads a wrapper option's value as a value, so `nice -n 19 pytest` is seen as the slow test run it is (it was read as a program named `19`); `long_running_command_guard` changes behaviour with it: a foreground main-thread `nice -n 19 pytest`, `nice -n 19 sleep 600` or `ionice -c 3 make` used to draw only the no-timeout advisory (the wrapper value was read as the program) and is now DENIED like its bare form (`slow-command` or `long-sleep`). Run such commands in the background or with a `timeout`. The classifier also reads a quoted program name (`"pytest" tests/`) as the program, and `command -v pytest` as a lookup, not a run.
