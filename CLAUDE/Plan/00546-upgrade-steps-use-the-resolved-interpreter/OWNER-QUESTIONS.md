# Owner questions: Plan 00546 Task 3.1 (Defence Before Fix, GitHub issue #130)

The DBF conformance review found that three decisions were taken without the owner, and they are the owner's to make. Task 3.1 stays open until each is ruled on. The rule (`bare-python-invocation`) is blocking and reports 0 on this branch only because of Q1's allowlist.

## Q1: Approve the 8 allowlist entries (11 lines), or direct an alternative

`scripts/qa/bare-python-allowlist.json` accepts 11 bare `python3` lines unfixed: 10 in `init.sh` (the hook forwarder hot path) and 1 in `install.sh` (bootstrap). Each entry now pins the whole line, indentation included, and an `occurrences` count, so a new or copied line is always reported.

| #   | File:line(s)                    | What it is                                         | Why it is not run on the resolved interpreter                             |
| --- | ------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------- |
| 1   | init.sh:325, 344, 360, 1728 (4) | Recovery-command snippets (`$recovery_py`)         | Run when the daemon or venv is wedged, absent or not yet trusted          |
| 2   | init.sh:390                     | Recognises the provision command                   | Unprovisioned checkout: no venv exists                                    |
| 3   | init.sh:581                     | needs-provision JSON encoder when `jq` is absent   | Unprovisioned checkout: no venv; the next fallback is a constant `printf` |
| 4   | init.sh:1128                    | `emit_hook_error` JSON encoder when `jq` is absent | Reached because the daemon or venv is missing                             |
| 5   | init.sh:1394                    | `_detect_unsupported_python` version probe         | Its job is to report that the PATH `python3` is too old                   |
| 6   | init.sh:3041                    | Socket transport rung after `nc` fails             | Resolving a venv interpreter would add a lookup to every hook             |
| 7   | init.sh:3727                    | `forward_stop_event` response reader               | Runs with no venv resolved; unparseable input allows the stop             |
| 8   | install.sh:123                  | `python3 install.py --force`                       | Bootstrap; `install.py` refuses below 3.11 in one line                    |

Evidence: entries 1 to 4, 6 and 7 are stdlib-only, written to a 3.8 floor, and pass on 3.8 and 3.9 in `tests/integration/test_init_sh_hot_path_runs_on_old_python.py`. Entry 8 was verified on 3.8 and 3.9. **The remaining hazard:** a PATH `python3` older than 3.8, such as 3.6 on old LTS hosts, is not tested and not excluded.

Options:

- **A. Approve all 8 as they stand.** Record the residual hazard as below 3.8, untested.
- **B. Approve 5 and 8 only.** Their whole job is to find or validate an interpreter. Rewrite 1 to 4, 6 and 7 so they do not need Python, using `jq`/`printf` or the venv where one exists. This has a hook latency cost to measure first (`bench_forwarder.sh`).
- **C. Approve all 8 and add a 3.6 interpreter to the old-Python test**, which makes the floor proven rather than assumed.

**Recommendation: C.** It keeps the hot path as it is and turns the doubt into evidence. If 3.6 fails, fall back to B for the snippets that fail.

## Q2: Rule scope: widen now, or record as known gaps

The independent search found these forms. The rule does not cover any of them, and none has been fixed (0 fixed of each).

| Form                                                       | Count                                                                                                                                                                              | What stopped the fix                                                                                                                   |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `#!/usr/bin/env python3` shebangs                          | 54 files; about 5 plausibly run on a client (`install.py`, `scripts/debug_info.py`, `scripts/handler_status.py`, `core/error_response.py`, `scripts/audit_handler_config_keys.py`) | A different detector is needed (Python files, not shell)                                                                               |
| `command -v python3` probes whose result is executed later | 4 sites: `scripts/bootstrap-self-install.sh:55`, `bin/hooks-daemon:193` and its template, the `.claude/ccy/claude-supervise` candidate loop                                        | These are interpreter-finding bootstraps; a fix needs a decision on what the bootstrap may assume                                      |
| `.github/workflows/qa.yml` `run:` lines                    | 7 bare `python` commands and 8 `$(command -v python)` probes, in 5 jobs                                                                                                            | None is needed. Every one follows `actions/setup-python` (3.11, 3.12 or 3.13) in its own job, so PATH python is the pinned interpreter |

Options:

- **A. Widen now.** Add a shebang rule for client-run Python entry points and a probe-result rule. Fix the 5 shebangs and the 4 probe sites in this plan.
- **B. Record as known gaps.** File a follow-up plan for the shebang rule and the probe-result decision. CI stays out of scope with the sentence above.

**Recommendation: B for CI, which carries no hazard.** For the shebangs and probes, take **A in a follow-up plan** rather than this branch. The probe sites need a ruling on what a bootstrap may assume, and that is a design question, not a sweep.

## Q3: Build the next wider rule (heredoc bodies that generate agent-run shell)

The one instance found, `.claude/skills/acceptance-test/invoke.sh` line 72, `TOTAL_TESTS=$(python3 -c ...)`, sat inside a heredoc that writes a skill document. It was fixed with `jq`. The rule today does not read heredoc bodies. The harness cannot tell a heredoc that generates shell an agent will run from a data heredoc.

Options:

- **A. Build it.** Scan heredoc bodies whose receiver writes a file that is later executed or read as instructions. This carries a false-positive risk that has to be measured.
- **B. Do not build it now.** Record it as a known gap, with 0 instances today.

**Recommendation: B.** No instance exists today. Revisit it if a second instance appears.

## Note: how the search was ordered relative to the rule

The claim that the independent search was done without sight of the rule is supported by dispatch records, not by commits. The coordinator dispatched the searcher and the rule writer in the same turn. The searcher was given the rule's file paths only so that it would keep out of them. Its report was committed after the rule's red commit, and all fourteen commits fall within the same minute, so git order proves nothing either way. The first text pass and the reading shared a blind spot (`${VAR:-python3}` defaults), so they count as one technique. The second regex pass is the independent one.
