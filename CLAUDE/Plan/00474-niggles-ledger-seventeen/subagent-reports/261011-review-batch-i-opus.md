STOPPING BECAUSE: the review is complete. The verdict and findings are below.

# Review: Batch I, N409 (subagent_full_qa_blocker, Python literal reachability)

**Verdict: CHANGES REQUIRED.** One small fix is required: two entries in the sink list let a real full run through.

I ran a probe of 34 Python scripts that each really run the full QA, against both main and this branch. Main passes 4 of them; the branch passes 9. The 5 new misses come from the `_TEXT_SINKS` exemption. All the routes in the brief still deny: join, f-string, `%`, `.format`, `+`, `os.system` on a variable, `execvp`, `pty.spawn`, `.extend`, `*args`, `**kw`, `partial`, `getattr`, `import ... as r`, `sh = subprocess.run`, lambda, comprehension, class attribute, `dict.get`, tuple unpack, parameter passthrough and method return. The new tests pass (85 passed, run with `-k`).

## Required

**R1. `write` and `writelines` are not text sinks** (`subagent_full_qa_blocker.py:3395-3396`). They are how bytes reach a pipe or a script file, so a write that later runs is now missed. Both cases below deny on main and pass on the branch:
- `p = Popen(['bash'], stdin=PIPE, text=True); p.stdin.write('./scripts/qa/llm_qa.py all\n')`
- `open('go.sh','w').write('./scripts/qa/llm_qa.py all\n'); subprocess.run(['bash','go.sh'])`

The rule is also inconsistent: `Path('go.sh').write_text(...)` followed by the same run still denies, because `write_text` is not in the list.

A careless agent writing a helper script and then running it, or feeding a shell's stdin, is an ordinary shape. Keeping `write` costs only the leftover false positive of `sys.stdout.write('pytest')` beside a process call, which is rare.

Fix:
- Remove `write` and `writelines` from `_TEXT_SINKS`.
- Add both probe shapes to `_PYTHON_FULL_RUNS`.

## Non-blocking (file as plan tasks)

**N1. A sink name rebound to a runner is still treated as a sink** (`:3486-3494`). `defined` only collects `def` names. These cases now pass and denied on main:
- `log = lambda c: subprocess.run(c, shell=True); log(Q)`
- `echo = subprocess.run; echo([...])`
- `from subprocess import run as echo`

Fix: treat any name in `_bindings(...)`, plus `ast.alias.asname`, as defined, i.e. `defined |= set(bound) | {a.asname for ImportFrom/Import aliases}`. Add the three cases as deny tests.

**N2. Misses that already exist on main** (unchanged by this branch):
- A list built with `a.append(...)` or `a += [...]` and then passed to `Popen(a)`: probably `_python_argvs` only judges a literal list as a whole argv.
- `asyncio.create_subprocess_exec(...)`
- `exec(open('runner.py').read())`

The `.append`/`+=` case is a plausible careless shape. File it with the probe cases.

**N3. Redundant first clause** (`:3657`). `_PYTEST in literals` is implied by `_PYTEST in _passed_literals(code)`, which falls back to all literals if parsing fails. `_process_arguments` also runs twice per script, once through `_python_strings` and once through `_passed_literals`. Either drop the clause or say it is a cheap short-circuit, and parse once.

**N4. The report's residual note doesn't match what I saw.** It cites "class attribute via `getattr`" as a remaining miss, but my `getattr` and class-attribute probes both deny. The misses that actually remain are R1, N1 and N2; the residual note should list those instead.

## Proportionality

For a careless-not-hostile threat model, this is proportionate. A simpler rule ("a literal counts unless its only consumer is print/logging") would still deny `TOOLS = [..., 'pytest']` beside an unrelated `subprocess.run`, and that table case is the false positive N409 reports. The reachability walk is about 100 lines, works through the code with a loop rather than recursion, and over-approximates: any non-sink call, even `len(TOOLS)`, counts as reaching the literal. So it errs toward denying, which is the right direction. The risk sits only in the sink list, which is where R1 and N1 come from.

## Tests and acceptance

The deny tests are real, not theatre: each one names a pattern id, and every case runs twice, on stdin and as a script file. The defined-sink and unparseable fail-closed cases are pinned. The missing coverage is deny cases for sink names (R1, N1).

Not adding an acceptance test is sound. `bash -n` makes the handler treat the command as parse-only, so an acceptance test can't show a deny, and in-process payloads add nothing over the unit tests.

## Positive

- Unparseable Python still judges every literal, so it stays fail-closed.
- Attributes are keyed by attribute name alone, which over-approximates as designed.
- The corpus rows pin the false positive from the ledger.

The probe file is `/workspace/untracked/scratch/review-batch-i/test_probe.py`; use it as evidence for R1, N1 and N2. Point `PYTHONPATH` at `<worktree>/src` or `/workspace/src` to compare the branch with main.