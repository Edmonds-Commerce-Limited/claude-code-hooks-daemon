# Security review — D-DEP (delta)

**Check**: `D-DEP` — "Dependencies added or bumped in the interval, and what the
new code is trusted to do."
**Run**: Routine 00002, run 2026-001, DELTA sweep.
**Interval**: `v3.63.0 -> v3.64.0`.
**Reviewer**: security-reviewer (opus), read-only.
**Check answerable**: yes. The interval diff was produced, both manifest changes
were read, and the installed wrapper for the one new third-party package was read
off disk at
`/workspace/untracked/venv-workspace-py311-81c29529/lib/python3.11/site-packages/pyright`.
Nothing was skipped for want of a tool or a path.
**Findings**: 4 (1 medium, 2 low, 1 correction to a full-sweep finding), plus one
clean-but-fragile observation.

## Boundary held

One check, this one. `F-CVE` was not attempted: no advisory database was
consulted and no pin was judged against one. Every claim below comes from this
repository's diff plus the bytes of the installed `pyright` wrapper. No network
request was made.

## The interval's dependency changes, in full

The manifest delta for the interval — `pyproject.toml` and `uv.lock` — is the
whole of it: 29 insertions, 2 deletions, two substantive entries, nothing bumped.

| Change                          | Where               | Scope         | Reaches a client? |
| ------------------------------- | ------------------- | ------------- | ----------------- |
| `typing-extensions>=4.12` ADDED | `pyproject.toml:39` | runtime       | yes               |
| `pyright==1.1.413` ADDED        | `pyproject.toml:70` | `[dev]` extra | no                |

`uv.lock` gained exactly one new package block (`pyright`, sdist + wheel both
sha256-pinned) and two `requires-dist` lines. `nodeenv`, which `pyright` pulls
in, was already locked at 1.10.0 via `pre-commit` — it is not new to the
closure, only newly reachable from a second parent.

**Widened and found empty.** No `package.json`, no `requirements*.txt`, no
vendored tree. No new GitHub Actions `uses:` entry in the interval's
`.github/workflows/` diff. No new remote pre-commit repo. No
`CLAUDE/remote-docs` addition. Every `uv sync` the interval touched still
carries `--frozen` (the CI Install step, rewritten in this interval to target
the fingerprint venv, keeps `--frozen --all-extras`).

## Relationship to the full sweep

Routine 00001's run 2026-001 covered `74b0989c -> 5d59f7ff`, which contains this
interval, and reported `pyright` as **D-DEP-06** and `typing-extensions` inside
its resolved-closure listing. So the *existence* of both is already on record
and is not re-reported here.

What follows is the part a whole-repo brief did not produce: three properties of
the **new gate code** the pin exists to serve
(`scripts/qa/run_pyright_check.py`, a 278-line file new in this interval), and
one correction to D-DEP-06's central mechanism claim. Each is marked for what it
is.

---

## D2-DEP-01 (MEDIUM) — the pyright gate accepts an unpinned analyser by three routes and asserts nothing about which one ran

**Citations** — `scripts/qa/run_pyright_check.py`:

```python
# :100-101  the PATH fallback
    found = path_lookup(_BINARY_NAME)
    return Path(found) if found else None

# :191-205  the spawn, with no env=
        completed = subprocess.run(  # nosec B603 — argv form, resolved binary, no shell
            [str(binary), "--project", str(root), "--pythonpath", str(interpreter), "--outputjson"],
            capture_output=True, text=True, cwd=str(root),
            timeout=_PYRIGHT_TIMEOUT_SECONDS, check=False,
        )

# :157  the running version is recorded and never compared
            "pyright_version": str(raw.get("version", "")),
```

**What it allows.** `pyproject.toml:66-70` states the pin's purpose: *"pinned
exactly because the gate is zero-errors and a new pyright release can add
diagnostics, which must arrive as a deliberate bump, not as a red CI run one
morning."* Three routes defeat that, and all three report a normal pass or fail:

1. **PATH fallback.** `resolve_pyright_binary` looks beside `sys.executable`
   first, then takes any `pyright` on `PATH`. A QA venv built without
   `--all-extras` — exactly what `create_venv_at_path` produces
   (`scripts/install/venv.sh:774`) — has no pyright, so
   `scripts/qa/run_all.sh:120` falls through to whatever `PATH` offers: a
   globally npm-installed pyright, an editor-managed one, any version. The
   docstring calls this "the fallback", which is accurate about the mechanism
   and silent about the consequence.
2. **Environment passthrough.** No `env=` is given, so the wrapper inherits the
   caller's whole environment. Read from the installed wrapper:
   `pyright/_utils.py`'s `_get_configured_pyright_version()` honours
   `PYRIGHT_PYTHON_FORCE_VERSION` (any value, including `latest`) and
   `PYRIGHT_PYTHON_PYLANCE_VERSION`; `install_pyright()` honours
   `PYRIGHT_PYTHON_USE_BUNDLED_PYRIGHT`. Any one of them takes the run off the
   bundled, hash-covered payload (see D2-DEP-03) and onto
   `npm install pyright@<version>` from the public registry.
   `PYRIGHT_PYTHON_PYLANCE_VERSION` additionally causes an HTTPS GET to
   `raw.githubusercontent.com/microsoft/pylance-release/...` to *choose* the
   version — an env-var-driven network fetch inside a QA gate.
3. **No assertion on the result.** The report carries `pyright_version`, and the
   only test touching it is `tests/unit/qa/test_run_pyright_check.py:146`,
   `assert report["summary"]["pyright_version"]` — a truthiness check.
   Repo-wide, the string `1.1.413` exists in exactly two places:
   `pyproject.toml:70` and two fixtures in that test file, both as input, never
   as an expected value.

The concrete wrong outcome: CI or a developer runs the zero-errors gate under a
pyright that is not 1.1.413, the diagnostics set differs from the one the tree
was cleaned against, and the run is reported as an ordinary pass or an ordinary
failure. A green run under the wrong analyser is the expensive half — it is
indistinguishable from the guarantee the pin was bought to provide.

**The class.** A tool version pinned for a stated *behavioural* reason (stable
output), invoked through a resolver that can return a different copy, with
nothing asserting that the copy that ran is the copy that was pinned. Membership
test, decidable without me: does the project pin X with a rationale about output
stability, AND locate X through a `which`/`PATH`/venv-sibling search or an
overridable environment variable, AND never compare the version X reports
against the pin? All three must hold. A tool invoked by absolute path, or one
whose output stability nobody relies on, is not a member.

This generalises past pyright. `black`, `ruff`, `mypy`, `bandit` and `deptry`
are invoked as bare names in `.github/workflows/qa.yml`, resolved through a
`GITHUB_PATH` entry; the lock pins them and `assert_venv_matches_lock` checks
the venv, but no step asserts the *invoked* binary came from it.

**Why the test suite does not catch it.** `tests/unit/qa/test_run_pyright_check.py`
tests the script against synthesised pyright JSON — the tests supply the
`version` field themselves. The gate's verdict is byte-identical whichever
binary produced it, so a test asserting on the verdict would pass under a wrong
analyser too. Catching this needs a test about the *environment* the gate ran
in, and the environment is precisely what the suite mocks away.

**Detector hypothesis.** Assert, in `scripts/qa/`, that
`untracked/qa/pyright.json`'s `summary.pyright_version` equals the `==` pin
parsed from `pyproject.toml`, and that `run_pyright_check.py` passes an `env=`
that removes every `PYRIGHT_PYTHON_*` key. Both halves are mechanical and both
fail loudly.

*False positives*: near zero. The cost is a maintenance edge — the artefact must
exist, so the rule belongs after the gate in `run_all.sh`, not in a pure source
lint; and each deliberate bump touches one more line, which is the same line the
bump already touches. A generalised version covering black/ruff/mypy would need
each tool's `--version` captured, a real cost and probably not worth it until
one of them drifts; the narrow version is the one to land.

**Confidence**: high on all three routes. Each was read — the fallback and the
missing `env=` from this repository's new file, the three environment variables
from the installed wrapper's source, the absent assertion from a repo-wide grep.
**What would settle the impact**: run the gate with
`PYRIGHT_PYTHON_FORCE_VERSION=latest` set and confirm the artefact records a
version other than 1.1.413 while the exit code is unchanged. I did not run it —
that would trigger the npm fetch this review is describing.

---

## D2-DEP-02 (LOW) — a missing `node` does not fail the gate; it downloads a Node.js runtime, and the script says the opposite

**Citation**: `scripts/qa/run_pyright_check.py:213-216`

```python
        return None, (
            f"pyright output was not JSON (exit {completed.returncode}){detail}. "
            "A pyright that cannot start usually means `node` is missing from PATH."
        )
```

**What it allows.** That sentence describes a failure that does not happen. Read
from the installed wrapper, `pyright/node.py`'s `_resolve_strategy()` tries, in
order: the `nodejs_wheel` package (not in `uv.lock`, so absent), then
`shutil.which('node')` (`PYRIGHT_PYTHON_GLOBAL_NODE`, default on), and if
neither is found calls `_ensure_node_env()` -> `_install_node_env()`:

```python
    args = [sys.executable, '-m', 'nodeenv']
    ...
    subprocess.run(args, check=True)
```

`nodeenv` is installed (locked at 1.10.0). So on a machine with no `node`, the
QA gate does not report a missing dependency — it **downloads a Node.js
distribution from the network** into `~/.cache/pyright-python/nodeenv` and runs
the analyser under it. No version is pinned (`PYRIGHT_PYTHON_NODE_VERSION` is
unset, so nodeenv picks its own default), and nothing in this repository records
a hash for those bytes. The 600-second timeout at `run_pyright_check.py:62` is
the only bound, and it was sized for analysis, not for a runtime download.

The runtime that executes the analyser is therefore outside `uv.lock`'s
authority on exactly the machines least likely to notice — a fresh container, a
CI image without node, a developer's first run. GitHub-hosted runners ship node,
so CI as configured today takes the `which('node')` branch; the exposure is
local and container installs.

**The class.** A dependency that, when its own prerequisite is absent, acquires
that prerequisite over the network instead of failing — and project code that
documents the absence as a failure. Membership test: on the
missing-prerequisite path, does the tool *install* rather than *refuse*? This is
narrower than "downloads a payload": the payload case (D2-DEP-03) is about the
analysed code, this is about the interpreter that runs it.

**Why the test suite does not catch it.** The tests stub the subprocess entirely
(`tests/unit/qa/test_run_pyright_check.py:192` feeds a shell script that echoes
JSON), so no test has ever run a real pyright, let alone one with no node
present. And on every machine where the suite does run, node exists — the branch
is unreachable there by construction.

**Detector hypothesis.** This one is weak and is reported as weak. "A dependency
that self-provisions a runtime" has no static signature; any rule degrades to a
curated list of known wrapper packages, which rots the moment someone adds a
package nobody listed. The honest remedy is not a Detector: it is
`run_pyright_check.py` pre-checking `shutil.which("node")` and failing with the
install instruction the file already carries at `:71-77`. The one mechanical
piece worth having is the `env=` allowlist from D2-DEP-01, which closes this as
a side effect.

**Confidence**: high on the mechanism (read from `node.py`'s own source). Low on
likelihood in CI today, which is why this is LOW rather than MEDIUM — it needs a
node-less machine first. The docstring being wrong is not conditional, though:
that is true on every machine.

---

## D2-DEP-03 (CORRECTION) — full-sweep D-DEP-06 misstates where the analyser comes from

**What the full sweep recorded**
(`260915-secreview-D-DEP-opus.md:398-408`): *"the code that actually analyses
this project is an npm tarball plus possibly a node runtime, fetched at QA time,
with no hash in `uv.lock` and no integrity check by this repository."*

**What the installed package actually does.** `pyright/_utils.py`'s
`install_pyright()`:

```python
    if version == __pyright_version__ and env_to_bool('PYRIGHT_PYTHON_USE_BUNDLED_PYRIGHT', default=True):
        bundled_path = Path(__file__).parent.joinpath('dist')
        if bundled_path.exists():
            return bundled_path
```

`pyright/_version.py` has `__version__ = '1.1.413'` and
`__pyright_version__ = '1.1.413'`, and `pyright/dist/` exists on disk, carrying
`index.js`, `langserver.index.js`, `package.json` and the analyser's own
`dist/`. That is why the wheel is 6.2 MB. **In the default configuration no npm
install happens at all**: the analysing JavaScript ships inside the wheel whose
sha256 *is* in `uv.lock`, and `cli.py` runs it directly via
`node.run('node', str(script), *args)`.

**Why the correction matters rather than being pedantry.** D-DEP-06's framing
points a fixer at the npm fetch, which in the default path does not exist. The
lever that does exist is the three environment variables and the PATH fallback
(D2-DEP-01) — each of which *diverts* the run off the bundled payload and onto
`npm install pyright@<version>`. So the exposure is real but conditional, and it
is reached through this repository's own gate script rather than through the
dependency. A fix aimed at "pin the npm tarball" would land in the wrong file.

D-DEP-06's other two claims stand and are confirmed here: the wrapper does
honour `PYRIGHT_PYTHON_FORCE_VERSION`, and the package is dev-only (no shipped
handler invokes `run_all.sh` or `llm_qa.py`; `create_venv_at_path` passes no
`--all-extras`).

**Confidence**: high. Read from `_utils.py`, `_version.py`, `cli.py` and a
directory listing of `dist/`, all in the venv the project's own QA uses.

---

## D2-DEP-04 (LOW) — `typing-extensions` as a direct runtime dependency: correct, with one stale enumeration

**Citation**: `pyproject.toml:36-39`, and the import it exists for,
`src/claude_code_hooks_daemon/core/hook_result.py:14`:

```python
from typing_extensions import TypeVar
```

**Verdict: clean.** This is a module-scope import in the daemon's core result
type, so the dependency is genuinely a runtime one and declaring it is right —
relying on pydantic to drag it in would have been the defect. The package is
pure Python with no native extension, maintained by the CPython typing team, and
it reaches client venvs through `uv sync --frozen`, so the client gets the
hash-pinned locked version, not the `>=4.12` floor. Nothing here is trusted to
do anything beyond providing a `TypeVar` implementation.

**The one thing to record.** Full-sweep D-DEP-04 enumerates the floors that the
lock-bypassing `uv pip install -e` path would resolve, and lists six —
`pyyaml`, `pydantic`, `jsonschema`, `psutil`, `mdformat`, `mdformat-gfm`. It
omits `typing-extensions>=4.12`, which was already declared at that sweep's HEAD
(the same report counts "7 runtime dependencies" two paragraphs earlier). The
finding's verdict does not change — `install_package_editable` still has no
caller, re-verified here — but a reader using that list as the inventory of what
an unlocked install would resolve gets an incomplete one, and the missing entry
is the one this interval added.

**Class and Detector**: none new. This is an instance of the existing D-DEP-04
class (a provisioning path that installs without consulting `uv.lock`), and its
Detector hypothesis is stated there.

**Confidence**: high. Import site, sync commands and the prior report's text
were all read directly.

---

## Examined and clean, and one that is clean only by accident

- **No network request in the default gate invocation.** The wrapper's PyPI
  version check (`pyright/utils.py`'s `get_latest_version()`, GET
  `https://pypi.org/pypi/pyright/json`) is reached only through
  `_should_warn_version()`, which returns `False` early when `--outputjson` is
  in the args. `run_pyright_check.py:198` always passes `--outputjson`. So the
  default path makes **no** outbound request: bundled payload, global node, no
  npm, no PyPI.

  **This is a side effect, not a decision.** `--outputjson` is there because the
  script parses JSON, and the suppression of the network call is incidental to
  that. Dropping or conditionalising that flag re-arms a PyPI GET on every QA
  run, and nothing in the file records that the flag is load-bearing for a
  second reason. Worth one sentence in the docstring; below the bar for a
  finding of its own.
- **`nodeenv` is not a new supply-chain entrant.** Already locked at 1.10.0 via
  `pre-commit`; `pyright` only adds a second parent.
- **`uv.lock` authority over the addition.** Both the `pyright` sdist and wheel
  carry sha256 entries, and `requires-dist` records the `==` specifier, so
  `uv lock --check` will catch a pyproject/lock divergence on this pin.
- **Provisioning paths touched in the interval.** The CI Install step was
  rewritten to build at the fingerprint venv path; `--frozen --all-extras`
  survived the rewrite. `scripts/venv-include.bash`'s change is a fix-message
  improvement only. `scripts/install/branch_install.sh` is new in this interval,
  and it decides which commit of THIS codebase a project ends up running rather
  than which third-party package is installed — that is `D-RULE`'s question, not
  mine. I note only that no full-sweep report mentions that file or its two
  environment variables at all, so somebody should confirm it was reviewed under
  some check.
- **pyright does not reach the daemon's runtime.** Every `pyright` reference in
  `src/` is a string, a config-file name or a process name
  (`strategies/lsp_noise/python_strategy.py:31-34`,
  `strategies/qa_suppression/python_strategy.py:16`). No shipped code executes a
  pyright binary, so D-DEP-01's "guard executes a binary from the guarded tree"
  class does not extend to this addition.

## Cross-check against the register

`CLAUDE/Security/README.md` holds four categories. D2-DEP-01 and D2-DEP-02
belong to none of them. The nearest is **fail-open boundaries**, and it does not
fit twice over: that category's scope is explicitly F-BYPS's daemon enforcement
path (`FailOpenBoundaries.md:98-103`), and D2-DEP-01 is not a stand-down at all
— the gate reaches a verdict, just with an analyser nobody checked. Both are new
classes. D2-DEP-01's Detector is the one worth building; D2-DEP-02's, as stated
above, should not be built as a Detector at all, and saying so is part of the
finding.
