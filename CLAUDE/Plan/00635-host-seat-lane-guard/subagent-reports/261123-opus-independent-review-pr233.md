# Independent review: PR #233 (Plan 00635 host_seat_lane_guard)

Reviewer: independent Opus sub-agent, read-only. Branch
`plan-00635-host-seat-lane-guard` (head `dca1d84c3`), diff
`origin/main...HEAD`. Nothing in the PR was edited. No seat password file, seat
store, run dir or kit was read. Probe scripts live in
`untracked/scratch/review-pr233/` (`run_cases.py` + `cases.json`,
`diff_classify.py`, `handler_checks.py`). They import the worktree `src/`
through `PYTHONPATH`, use stub seat resolvers, and run no real `whoami`.

## Verdict

**Safe to merge as shipped (`mode: advise`). Not yet safe to promote to
`mode: block`.**

None of the merge blockers showed up:

- A session with no team sees no change. With no runtime signal the guard
  returns before any probe (`host_seat_lane_guard.py:216-217`).
- `long_running_command_guard` has no regression. The 16 behaviour
  differences against main are all the intended wrapper-value correction
  (finding 6).
- The registry does inject `_team_seat`, so the guard honours
  `detection: off` and the configured TTL (`registry.py:906-909`).
- An ALLOW in advise mode does not end the PreToolUse chain (`core/chain.py`
  header and lines 1087-1093). The terminal flag only matters under `block`.
- The added code opens no files, has no v1 verbs or fixtures, and has no
  approval or bypass path. `extra_lane_patterns` can only add patterns, and
  `exempt_patterns` is not exposed.

Findings 1 to 3 should be closed, or recorded as accepted, before anyone
rules on promotion to `block`. A one-quote-character bypass and some
deploy-command false positives matter much less while the guard only advises.

## Tests run (nice -n 19, `PYTHONPATH=<worktree>/src`)

- Every changed test file, plus
  `tests/unit/handlers/pre_tool_use/test_long_running_command_guard.py` and
  `tests/integration/test_handler_scope_defaults.py`: **1332 passed**.
- Doc, config and priority drift tests (`test_docs_generator`,
  `test_generated_doc_hand_edit`, `test_handler_key_audit`,
  `test_generated_config_validity`, `test_handler_profiles`,
  `test_documentation_config`, `test_handler_reference_check`,
  `test_declared_behaviour_matches_source`,
  `test_priority_bands_match_the_code`,
  `test_project_handler_priority_collisions`, `test_doc_truth_check`):
  **216 passed**.
- `test_long_running_command_guard.py` is not modified by the PR. In
  `tests/unit/utils/test_long_running_command.py` the diff only adds lines; no
  existing expectation was removed.
- `test_safety_handlers_hostile_input_performance.py` on **main**
  (`/workspace`): `double_star_glob` FAILS on main as well. Two other cases
  also failed or errored there (`quote_run`, `wildcards`). This supports the
  builder's note: the failure is not caused by this PR. The run is weak
  evidence, though. It was a timing test, run under `nice -n 19` on a loaded
  host, and that is a confound. The same file on the PR branch was still
  running when this report was written.

## Findings

### 1. Quoting the program name bypasses the classifier. Severity: HIGH for block promotion, LOW while advise. Present on main.

`'pytest'`, `"pytest" tests/` and `p\ytest` are all missed. The program word
keeps its quotes, or the backslash, so `^pytest\b` never matches. Main's
classifier has the same gap: `classify` gives `unbounded '"pytest"'` on both
main and the PR. It is a two-character respelling that bash runs exactly like
the bare command.

Reproduce: `is_lane_command('"pytest" tests/')` returns False. The same holds
for `"'pytest'"` and `'p\\ytest'`.

Location: `utils/long_running_command.py` `_segment_words` / `_peel` (the
program basename is not dequoted).

### 2. Wrapper and launcher gaps the classifier misses. Severity: MEDIUM for block promotion.

All of the commands below run a lane command, and `is_lane_command` returns
False for every one. The fix belongs in the shared `_peel_wrapper` /
`_RUN_LAUNCHERS` / value-option tables, or in `LINT_PATTERNS`
(`host_seat_lane_guard.py:79-104`).

| Command                                                                                                                          | Cause                                                                                                         |
| -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `find tests -name '*.py' \| xargs pytest`, `xargs pytest < f`                                                                    | `xargs` is not peeled                                                                                         |
| `eval pytest`, `eval 'pytest tests'`                                                                                             | `eval` is not peeled                                                                                          |
| `echo $(pytest)`, `` echo `pytest`  ``                                                                                           | a command substitution in argument position is not judged                                                     |
| `echo pytest \| bash`                                                                                                            | the stdin body of a shell is not seen (the heredoc forms ARE caught)                                          |
| `P=pytest; $P`                                                                                                                   | variable expansion (out of reach for text parsing; noted only)                                                |
| `python3 -I -m pytest`, `python3 -X dev -m pytest`                                                                               | `-m` is recognised only as the first word after python (`long_running_command.py:373`)                        |
| `python3 -c 'import pytest; pytest.main()'`                                                                                      | inline code                                                                                                   |
| `coverage run -m pytest`, `python -m coverage run -m pytest`                                                                     | `coverage` is neither a wrapper nor a pattern                                                                 |
| `uv run -p 3.12 pytest`, `uv run --python 3.12 pytest`                                                                           | launcher options are taken as valueless (`:369-371`)                                                          |
| `stdbuf -o L pytest`, `exec -a x pytest`, `env -C /x pytest`, `sudo -h h pytest`, `sudo -T 5 pytest`                             | value options missing from `_WRAPPER_VALUE_OPTIONS` (env handles only `-u`)                                   |
| `taskset -c 0 pytest`, `flock /tmp/l pytest`, `chronic pytest`, `unbuffer pytest`, `script -qc pytest /dev/null`, `watch pytest` | wrappers that are not peeled                                                                                  |
| `make -C sub test`, `make -f Makefile.ci test`                                                                                   | `LANE_MAKE_PATTERNS` accepts only valueless flags (`:90-91`); `make -j4 lint` and `make -j 4 test` are caught |
| `gmake test`, `just test`, `task test`, `hatch test`, `hatch run test`                                                           | runners not listed                                                                                            |
| `npm t`, `npm run-script test`, `npm run check`, `pnpm vitest`, `pnpm exec vitest`, `yarn jest`, `bunx vitest`                   | package-manager spellings not listed                                                                          |
| `cargo +nightly test`                                                                                                            | toolchain selector before the subcommand                                                                      |
| `pre-commit run --all-files`, `./scripts/qa/run_autofix.sh`                                                                      | QA entry points not covered by the QA and lint name patterns                                                  |
| `docker exec app pytest`, `docker compose run app pytest`, `ssh host pytest`                                                     | remote or container execution; may be intended, the owner should rule                                         |

These were caught (good): `bash -c`, `bash -lc`, `sh -c "cd x && pytest"`,
`env`, `env -i`, `nice` (all spellings), `ionice`, `sudo -u` / `--user=` /
`-E` / `-s`, `timeout N` (any N), `setsid`, `nohup ... &`, `time`, `exec`,
`command`, `stdbuf -oL`, `&&` chains, `( )`, `{ }`, `if`, `for`, `!`,
`bash <<'EOF'`, `cat <<'EOF' | bash`, `python -m pytest`, `python -m mypy`,
`python3 -m ruff`, `python -m unittest`, `.venv/bin/pytest`,
`"$HOME/.venv/bin/pytest"`, `/usr/bin/env pytest`, `npx jest` / `tsc`,
`npm test`, `npm run test`, `npm run lint`, `make`, `make test`, `cargo test`,
`go test`, `tox`, `ruff`, `black`, `pyright`, `mypy`, `llm_qa.py` (direct and
via `python`), `run_all.sh`, `run_tests.sh`, `run_type_check.sh`, `pytest &`.

### 3. A sub-agent of a host seat is never judged. Severity: MEDIUM (design question).

`duty_gate` returns NOT_APPLICABLE for any event that is not main-thread
(`utils/team_role_gate.py:97-98`). The handler's test
`test_subagent_is_silent` pins this, and HANDLER_REFERENCE says "sub-agents
... are untouched". So a host-duty seat can dispatch an Agent whose Bash runs
`pytest`, and nothing is refused. The owner's ruling is that host seats are
not workers, and the static `cc-deny.json` layer would still apply to a
sub-agent. Even so, this is the easiest lane escape and it is not called out
as accepted.

Reproduce: a hook input carrying `teamchat_runtime`, a stub resolver
answering duty `host`, `agent_id` set (the sub-agent shape) and `pytest`.
`matches()` returns False.

The owner should rule on it: either accept it and document it under the
ruling, or arm sub-agents for this duty.

### 4. The "probe gave no answer" text is false when the probe did answer with a null duty. Severity: LOW (honesty requirement).

`_judge` appends `_NO_ANSWER` ("The teamchat whoami probe gave no answer.") on
a session's first ROLE_UNKNOWN refusal (`host_seat_lane_guard.py:276-279`).
ROLE_UNKNOWN is also produced by a RESOLVED context whose seat has an empty
duty (`teamchat_seat.py:303-307`, `duty: null` on the wire), and there the
probe answered.

Reproduce (`handler_checks.py`):
`SeatContext(RESOLVED, ..., seats=(TeamSeat("t", DECLARED, "worker", "h", ""),))`
leads to a refusal containing "The teamchat whoami probe gave no answer."

Fix: append `_NO_ANSWER` only when `context.state is SeatState.UNRESOLVED`.
For a null duty, say instead that "the seat's duty is not declared".

### 5. Errors before arming fail open even when a runtime signal is present. Severity: LOW (documented).

`matches()` returns False when `_verdict` raises (`:235-243`), even after
`signals.runtime` was truthy, so a team is signalled. Reproduced with a
resolver whose `resolve` raises: `matches=False`. The docstring and the
`log_and_continue` reason state this choice. `SeatContextResolver.resolve` is
documented never to raise (probe failures become UNRESOLVED, which fails
closed), so the window is only a code bug inside the resolver. It is still a
departure from "unknown keeps the guard armed". One alternative is to fail
open only when `signals.runtime` is empty, which is already checked before
the resolver call, and to fail closed otherwise.

### 6. The shared classifier fix tightens `long_running_command_guard`. Severity: LOW (release-note wording).

The differential `diff_classify.py` compared main's `classify` with the PR's
over 196 commands and found 16 differences. All of them are wrapper-value
corrections. For example, `nice -n 19 pytest` changes from `unbounded '19'`
to `slow-command pytest`, `sudo -u root ls` changes from `unbounded 'root'`
to nothing, and `nice -n 19 sleep 600` changes to `long-sleep`. The
correction is right. But for `long_running_command_guard` it turns a
foreground main-thread `nice -n 19 pytest`, `nice -n 19 sleep 600` or
`ionice -c 3 make` from the no-timeout ADVISORY into a SLOW_COMMAND / LONG_SLEEP
DENY.

`nice -n 19 pytest` is a shape this repo's own agents use. The release note
says only that "long_running_command_guard benefits too". It should say that
these wrapped shapes are now denied in the foreground like their bare forms.

### 7. False positives on deployment and triage work. Severity: MEDIUM for block promotion.

The PR and HANDLER_REFERENCE say deployment and triage commands are "never
refused". These are refused:

| Command                                                       | Why                                                           | Note                                             |
| ------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------ |
| `mvn deploy`, `gradle publish`                                | `BUILD_PATTERNS` matches every `mvn` / `gradle`               | real deploy commands                             |
| `./deploy-qa.sh`                                              | `QA_SCRIPT_PATTERNS` matches `-qa.sh`                         | a deploy script named for its target environment |
| `./deploy_test.sh`, `./smoke_test.sh`, `./test-connection.sh` | `QA_SCRIPT_PATTERNS`                                          | post-deploy smoke checks are triage              |
| `command -v pytest`, `command -v make`                        | `command` is peeled as a wrapper; `-v` only looks the name up | also misread by main's classifier (not new)      |
| `pytest --version`, `ruff --version`                          | any invocation counts                                         | minor                                            |

Tolerable under advise. Under block, the deploy rows in particular contradict
the stated contract. Either narrow the patterns (exclude `mvn deploy`,
`gradle publish`, and a `deploy` prefix on QA-named scripts) or soften the
"never refused" wording.

### 8. Release-note numbering collision risk. Severity: LOW (not fixed, as asked).

Main holds release notes 087 to 089. This PR uses `091` (CLAUDE/UPGRADES/UNRELEASED/release-notes/091-host-seat-lane-guard.md),
on the understanding that PR #231 takes 090. PR #232 will need a number too,
so whichever of the three merges later must check, and may need to renumber.
Also, the header comment of `config-changes/v3.77.0.yaml` ("Drafted by
...") does not list Plans 00634 and 00635 although both add entries
(cosmetic).

### 9. Each handler runs its own whoami cache. Severity: INFO.

`_seat_resolver()` builds a private `SeatContextResolver` per handler
instance, as `human_approval_check` does. Each team-aware handler therefore
probes `whoami` separately, once per TTL. The cache key is
`(runtime, kit)` and the TTL defaults to 60 s, so a duty change takes up to
one TTL to apply. That matches the documented `team_seat` contract. Every
Bash call in a team session resolves the seat before the command is
classified. That ordering is deliberate (a failure before arming stays
silent), and the TTL keeps the cost bounded.

### 10. An unknown duty arms worker seats on a kit that sends no duty. Severity: INFO (rollout).

Duty `null` arms the guard by design (Q9). If any team runs a teamchat kit
whose `whoami` does not yet emit `duty`, every worker seat in that team gets
the lane advisory on every test run, and under `block` could not test at all.
Check the kit version before promoting.

## Mode handling

Default is `advise` (`_mode` class attribute). `validate_options` rejects any
value outside `off | advise | block`. The registry withholds the bad value
(`registry.py:_withhold_invalid_options`), so the handler **falls back to
`advise`** and the problem is reported in the session-start option-failures
alert. This means `mode: Block` silently stays advisory apart from that
alert. That is acceptable, but worth knowing. `mode: off` makes the handler
dormant.

## Registry, config and doc drift

- The constants (HandlerID, Priority 21, RuleID), the init template, both
  YAML files, the config-changes entry and HANDLER_REFERENCE all agree on the
  key, priority 21 and `mode: advise`.
- `.claude/HOOKS-DAEMON.md`: the PreToolUse count went from 89 to 90. The
  generator sorts rows on `(priority, config_key)` (`docs_generator.py:231`),
  so `host_seat_lane_guard` before `human_approval_check` at priority 21 is
  correct.
- CLAUDE.md: the marker and the table row are placed in alphabetical and ID
  order next to `host-command-guard` / `R-HUMAN-APPROVAL-MISSING`. I did not
  render it through the generator (`bin/hooks-daemon generate-docs` needs a
  worktree venv, and I did not run a writing generator in the PR), so the
  exact generator output is **unverified**. The drift tests listed above pass.
- Priority 21 is shared with `human_approval_check` and `pip_break_system`.
  The command sets are disjoint apart from compound commands, and there the
  first terminal deny wins. Harmless.

## False-positive table (host work that must not be refused)

| Command                                                                                                                               | Refused?                          |
| ------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| `git status`, `git log --grep=pytest`, `git commit -m 'run pytest and make test'`, `git -C /x pull`                                   | no                                |
| `gh pr view ...`, `gh run watch`, `gh pr checks --watch`                                                                              | no                                |
| `ls tests/`, `cat tests/test_x.py`, `less run_tests.sh`, `vim tests/test_x.py`, `mkdir -p tests`, `cd tests && ls`                    | no                                |
| `grep -r pytest .`, `rg 'make test'`, `echo pytest`, `printf 'npm test'`, `ps aux \| grep pytest`, `pgrep -f pytest`, `pkill pytest`  | no                                |
| `type pytest`, `which pytest`, `hash pytest`, `man pytest`                                                                            | no                                |
| `docker build`, `docker compose up -d`, `docker logs -f`, `docker ps`                                                                 | no                                |
| `pip install`, `uv sync`, `npm ci`, `npm install`, `apt-get install`                                                                  | no                                |
| `make deploy`, `make install`, `make -C infra deploy`, `./deploy.sh`, `./deploy.sh & wait`                                            | no                                |
| `ansible-playbook`, `terraform plan`, `kubectl get pods`, `systemctl restart`, `sudo systemctl restart nginx`, `journalctl -u app -f` | no                                |
| `tail -f /var/log/app.log`, `tail -n 50 build.log`                                                                                    | no                                |
| `CLAUDE/Plan/mkplan.bash x`, `bin/hooks-daemon status/restart`, `pingbus inbox`                                                       | no                                |
| `rsync`, `scp`, `curl -s .../health`, `python3 scripts/deploy.py`, `bash scripts/deploy.sh`                                           | no                                |
| `cat <<'EOF' > notes.md` with pytest in the body                                                                                      | no                                |
| `test -f x`, `[ -f run_tests.sh ]`, `latest.sh`, `./contest.sh`, `./attest.py`                                                        | no                                |
| `mvn deploy`, `gradle publish`, `./deploy-qa.sh`                                                                                      | **yes** (finding 7)               |
| `./deploy_test.sh`, `./smoke_test.sh`, `./test-connection.sh`                                                                         | **yes** (finding 7)               |
| `command -v pytest`, `command -v make`                                                                                                | **yes** (finding 7, also on main) |
| `pytest --version`, `ruff --version`, `npx prettier --write docs/x.md`                                                                | **yes** (minor)                   |
