## 22:00 · decision · — — handler built, advise mode

Built host_seat_lane_guard (priority 21, R-HOST-SEAT-LANE, mode advise) on branch plan-00635-host-seat-lane-guard.

Arming is duty_gate(host): APPLIES and ROLE_UNKNOWN both refuse, following the settled Q64 D3 text (unreadable whoami = guards armed) over the section 4 "B7 goes quiet" recommendation; the first ROLE_UNKNOWN refusal per session adds "the probe gave no answer". No runtime on the payload means no probe and no change.

Classification reuses classify/FindingKind: DEFAULT_SLOW_PATTERNS was split into named groups (test, build, make, QA, install, container, watch; default unchanged as their concatenation) and the lane takes test, build and QA plus lint, make test/build targets and test/QA-named scripts. Installs, docker, make deploy and log tails stay untouched. classify gained include_background so `pytest &` is judged, and the lane policy uses threshold 0 so a timeout-bounded test run is still seen.

Found and fixed in the shared classifier: `nice -n 19 pytest` was read as a program named `19`, so long_running_command_guard missed it too; wrapper value options are now peeled for nice, ionice and sudo.

Left: live verification in a host-duty seat; promote to block when ruled.
