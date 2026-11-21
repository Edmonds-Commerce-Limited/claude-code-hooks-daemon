## 15:16 · action · — — RC code merged to main; rc/3.74.0

The release-candidate code is merged to main (8f00c69c8, CI green). It covers Tasks 2.1, 2.2, 3.3 and 4.5. It went through three review rounds before the merge:

- Round 1 had 5 important and 7 minor findings: a quadratic lock scan in a guard path, an unresolvable default branch left silent, the home_commit pull deadlock, stale upgrade text, and no upgrade task.
- Round 2 had 4 important findings: init.defaultBranch naming a missing branch, regenerate-docs writing on a PR-protected home, a notice that could be missed or go stale, and a slow nested-clone walk.
- Round 3 had 1 important finding: a clone with no local default branch got a notice nothing could silence.

All were fixed with tests shown failing first, except where the implementer said otherwise and a reviewer then confirmed the tests fail against the pre-fix code.

rc/3.74.0 now points at main and supersedes rc/3.73.3. The client seats are not re-installing during their acceptance round. The coordinator will ask the owner for v3.74.0.

Lessons:

- Main went red twice for things the targeted runs did not cover:
  - a release note missing its Plan/Audience lines (holding-area test);
  - a source skill page changed without redeploying its deployed copy (deployed-skill-tree drift test);
  - two semgrep rules (shlex and pathlib containment) in a merged agent branch where semgrep was not in the agent's QA list.
- From now on, the merge QA here includes semgrep, test_pending_release_notes_holding_area.py and test_deployed_skill_trees.py.
