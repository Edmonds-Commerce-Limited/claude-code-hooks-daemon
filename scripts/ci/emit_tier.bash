#!/usr/bin/env bash
# Print the CI tier outputs (tier=, base=, head=) for $GITHUB_OUTPUT.
#
# Reads EVENT, REPO, GH_TOKEN, PR_BASE_SHA and PR_HEAD_SHA from the environment
# (the workflow passes them through env, never interpolated into script text).
# The tier rules live in classify_changes.py; this script only decides the
# range to hand it:
#   push          base = the head sha of the newest main qa.yml run that reached
#                 a verdict (last_verdict_sha.py; needs GH_TOKEN and REPO). A
#                 run superseded while pending is cancelled and tests nothing,
#                 so the sha before the push may never have been tested. No such
#                 run, or one that is not an ancestor of head: the full tier.
#   pull_request  base = merge base with the PR base branch, head = the PR tip
#   anything else (schedule, workflow_dispatch): no base, so the full tier
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
base=""
head="${GITHUB_SHA:-HEAD}"

if [ "${EVENT:-}" = "push" ]; then
  base="$(python3 "${here}/last_verdict_sha.py" --repo "${REPO:?REPO is required for a push}")"
elif [ "${EVENT:-}" = "pull_request" ]; then
  if ! base="$(git merge-base "${PR_BASE_SHA}" "${PR_HEAD_SHA}")"; then
    echo "no merge base for the PR: the full tier will be chosen" >&2
    base=""
  fi
  head="${PR_HEAD_SHA}"
fi

python3 "${here}/classify_changes.py" --base "${base}" --head "${head}"
echo "base=${base}"
echo "head=${head}"
