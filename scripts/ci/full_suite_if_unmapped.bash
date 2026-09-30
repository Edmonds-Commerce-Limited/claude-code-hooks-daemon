#!/usr/bin/env bash
# Run the whole suite on this one Python when the change mapper cannot cover a
# changed file (unmapped, which includes too broad). Otherwise do nothing: the
# targeted step before this one already ran every mapped test.
#
# Reads RANGE (A..B) from the environment. The mapper is asked with
# --select-only, so no test runs here for the question itself.
set -euo pipefail

selection="$(mktemp)"
python scripts/qa/run_changed_tests.py --range "${RANGE}" --select-only > "${selection}"
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
pytest tests/ -rs
pytest .claude/project-handlers --import-mode=importlib
