#!/usr/bin/env bash
# Run the whole suite on this one Python when the change mapper cannot cover a
# changed file (unmapped, which includes too broad). Otherwise do nothing: the
# targeted step before this one already ran every mapped test.
#
# Reads RANGE (A..B) from the environment. The mapper is asked with
# --select-only, so no test runs here for the question itself.
set -euo pipefail

# The interpreter the Install step provisioned (the same resolver call it checks),
# not a python found on PATH. A missing venv fails here, loudly.
python="$(bash scripts/lib/resolve_venv.sh python "${PWD}")"
if [ ! -x "${python}" ]; then
  echo "the provisioned interpreter is missing: '${python}'" >&2
  exit 1
fi

selection="$(mktemp)"
"${python}" scripts/qa/run_changed_tests.py --range "${RANGE}" --select-only > "${selection}"
unmapped="$(jq '.unmapped | length' "${selection}")"
echo "unmapped files: ${unmapped}"
if [ "${unmapped}" = "0" ]; then
  echo "every changed file is mapped; no full-suite fallback needed"
  exit 0
fi

echo "the mapper cannot cover ${unmapped} changed file(s); running the whole suite"
jq -r '.unmapped_reasons | to_entries[] | "  \(.key): \(.value)"' "${selection}"

# tests/conftest.py refuses a whole-suite-sized run without the host-wide
# full-QA lock; take the same lock file the qa job takes.
git_common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
exec {lock_fd}>> "${git_common_dir}/hooksdaemon-full-qa.lock"
flock "${lock_fd}"
# The daemon the job started earlier shuts itself down after
# daemon.idle_timeout_seconds (600s) without a hook call, and the static and
# targeted steps before this one can outlast that; the release-gate tests then
# error on a missing socket (Plan 00474 N431). Start it again just before use.
./bin/hooks-daemon restart
./bin/hooks-daemon status
# CPU-timing sweeps (perf_sweep) miss their bounds under this run's own load;
# the perf-sweep job runs them alone, with the same thresholds.
pytest tests/ -rs -m "not perf_sweep"
pytest .claude/project-handlers --import-mode=importlib
