**Review of Plan 00555 DBF remediation (`p555-dbf-fix`, final commit `f5a225d4c`)**

**Reproduction**
- **Red at `b0dbbe5e4`:** I ran that tree's detector with the project interpreter. It exited 1 with "Found 64 venv interpreter(s) trusted without a version check". That includes the originating site `paths.py:960` and `resolve_venv.sh:216/221`. This confirms the report's 64, which the report itself says it did not re-run. Output is in `/workspace/untracked/scratch/red.txt`.
- **Green at the final tree:** `./scripts/qa/llm_qa.py venv_interpreter_trust` exited 0 with "0 violations (1024 files scanned)" and "QA: 1/1 PASSED". The detector's own tests also pass (124). I did not run `llm_qa.py all`, so the full-gate claims in the report are unverified by me.
- **Worktree cleanup:** I removed the scratch worktree `p555-review-red`. I did not modify `p555-dbf-fix`.

**Caveat on clause citations.** `/root/.cache/defence-before-fix/spec/SPEC.md` does not exist in this environment. I searched the repo for a copy and found none. The report also admits the cache was missing at drafting and that version 1.1.0 was fetched later. I cannot quote sections 3, 4, 7 or 8, so the clause references below are by topic and unverified. Findings that rest on the report alone are marked.

**Findings, by severity**

1. **High. The original defect was fixed before the defence, not last.** (method, section 3, "original defect last")
   - Evidence: `e936d4538` and `8bfcf9ab1` (Task 2.2 drift fix) precede `b0dbbe5e4` in `git log main..p555-dbf-fix`. The report concedes this under "The original defect": "Task 2.2, merged onto the branch at `6edb526c7`".
   - Consequence: the red proof at `b0dbbe5e4` is red against code where the drift fix already exists. The detector flags `paths.py:960` as a weak probe even though the defect there was already fixed. So red was never shown on a tree that still had the user-visible defect.
   - Resolve: either state this as a recorded deviation, or show the defect reproduced on the pre-Task-2.2 tree. The report cannot claim the ordering is conformant.

2. **High. The rule was narrowed after the red proof, and the narrowing is loose.** (section 3, rule width; section 4, last bullet)
   - Evidence: the diff from `b0dbbe5e4` to final adds `_runs_package_import` and `_SH_PACKAGE_IMPORT`. Any scope containing `-c "import claude_code_hooks_daemon..."` without a `sys.path` edit counts as proof.
   - The shell regex matches anywhere in the scope text. It is not tied to the interpreter being tested. An unrelated import line in a function clears every finding in it.
   - The report records the narrowing and the five findings it removed, but justifies it only by citing the searcher's "no" ratings. It cites no fixture showing the import fails under a mismatched minor, and no test that the shell exemption is bound to the same variable.
   - Resolve: bind the shell exemption to the tested interpreter, add a red fixture for an unrelated import line, and record why importing is equivalent to the version check, including editable or `.pth` installs.

3. **Medium. The fix tests were written after the code.** (section 3, "prove before fixing")
   - Evidence: the report states that fix-core's tests "were written after the code". Fix-b re-ran them at `6edb526c7`, where 11 of 14 and 5 of 9 failed. One test was red for the wrong reason, and the (f) tests were green on the old code.
   - `upgrade_version.sh` was tested statically only, and the by-pattern sites have "no separate sample recorded".
   - The rule's red proof is sound, but per-fix red proof is partial.
   - Resolve: label (f) and `upgrade_version.sh` as unproven by reproduction, and record a sampled by-pattern check.

4. **Medium. Several "false positives" were resolved by changing the detector.** (section 3, "reconciled in the rule's favour")
   - Evidence: `0298f52c5` (local-shadow rule) and `5ad3529b8` (`_without_protected` replacing `_sig._without_protected_paths`) changed detector behaviour late. The `_VENV_BIN_VARIABLE` widening is the opposite direction and is fine.
   - Whether each loosening is a real false positive is asserted in the report, not shown. `upgrade.sh:967` is cited as the case.
   - Resolve: record one fixture per loosening showing the code is safe, and keep the report's "0 left excluded" claim tied to those fixtures.

5. **Medium. Section 4 referrals are unresolved, and the rule is not wired at full width as a merge-ready state without an owner.**
   - Evidence: the report states that decisions 1 to 3 have "not been taken". The class is partly undefended, with 13 search items having no lexical signature. The wider rule is unbuilt.
   - The counts are given (13 fixed by hand, 0 left) and what stopped a rule is given. Decision 4 is internally consistent: the rule is blocking and the branch is unmerged.
   - Resolve: have the owner accept or reject decisions 1 to 3 before merge, and state who the owner is.

6. **Low. The report has staleness and consistency defects.**
   - Evidence: the report says it is "checked against 1.1.0 sections 3.4, 3.5 and 4" while nothing on the branch shows which version the practitioners read.
   - The "Green run" block is dated at `879f6c66c` and `f43d472fb`, not the final commit, and the report's own line numbers are at `879f6c66c`.
   - Resolve: re-stamp the green run at `f5a225d4c` (I observed the same line there) and the line numbers.

7. **Low. `venv.sh` keeps three `shellcheck disable=SC1090` lines (135, 356, 528).**
   - Whether they name a reason for the `inline_suppressions` checker (the report's `e59cfa07a`) I did not verify. They are not suppressions of the new rule, and the report says the checker reports 0.
   - Resolve: confirm each carries a reason.

**Checked and found conforming (from the commits and files)**
- The red commit `b0dbbe5e4` holds the detector and its tests only. It stays red at 64 and survives as its own commit.
- `feab6a3c8` wires the check into `run_all.sh` (a failing check at `:457`), `llm_qa.py` and `qa-rules.json`, and adds the rule doc `UntrustedVenvInterpreter.md`. The messages and the `qa-rules.json` entries carry the stable identifiers `venv-exec-bit-trust` and `venv-weak-liveness-probe`. The remediation text now builds from `GATES`.
- There is no exemption marker, baseline or suppression. The 64 findings went to 0 by site fixes plus the detector changes in findings 2 and 4.
- The next wider rule is named, with the reason it was not built and what to try next (CodeQL, with shell uncovered).
- The independent search is documented as pre-rule and blind, with a list of what text search and reading each found alone. The detector was widened for the three cases it missed.
- The sweep scope is stated: tracked first-party Python and shell. The exclusions are `tests/`, fixtures, worktrees, `untracked/` and vendored code. The workflow YAML gap is disclosed.
- The Toolchain gap section is present and the template is largely complete.