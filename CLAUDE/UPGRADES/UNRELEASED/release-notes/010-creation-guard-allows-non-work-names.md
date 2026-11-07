# Callout: creating the default branch (or an exempt or protected name) is never denied by the branch cap

**Plan**: 00474 (N593)
**Audience**: client projects

The branch creation guard allowed a name already in `refs/heads` (a reset or a checkout), but treated any other name as new open work. A checkout with no local copy of the default branch (a detached CI pull-request checkout, or a clone that deleted its local `main`) was therefore denied `git branch main origin/main` or `git checkout -b main` whenever the repository sat at `branches.wip.cap` or held a dormant branch. The default branch and any name matched by `branches.exempt`, `branches.integration_lines` or `branches.protected_names` are never counted as work, so creating one cannot raise the count the cap and dormancy judge, and it is now allowed.
