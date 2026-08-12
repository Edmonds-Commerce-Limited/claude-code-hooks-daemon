# `planlib` — a proposal to promote plan-folder orchestrator tooling into the hooks daemon

**Status**: proposal for upstream. Everything below is running in a private infrastructure repo;
this document is the generic extraction, not a copy-paste of that repo.

**What is being proposed**: the daemon already owns the *plan lifecycle* — it scaffolds plan
folders (`mkplan.bash`), tracks the plan number in a git config counter, lints `PLAN.md` at
Write/Edit, gates plan invariants at `git commit`, and advises on journals. It does **not** own
the other half: what happens when a plan needs something *run*. That half currently gets
hand-rolled per plan, per project, and it is where the expensive mistakes are.

This proposes three artefacts, in descending order of value:

| #   | Artefact            | What it is                                                                  | Depends on            |
| --- | ------------------- | --------------------------------------------------------------------------- | --------------------- |
| 1   | `_planlib.inc.bash` | A sourced bash library of safety-critical primitives for plan orchestrators | nothing but bash 4.2+ |
| 2   | `plan_script_qa`    | A PreToolUse/commit handler enforcing that orchestrators are built on it    | 1                     |
| 3   | `test-planlib.bash` | The suite that makes 1 safe to change                                       | 1                     |

They are separable. (1) alone is worth having. (2) without (1) is a rule with no implementation.

---

## 1. The problem this solves

### 1.1 The concrete incident

A plan shipped a `triage.bash` that resolved its repository root like this:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"     # WRONG
```

`git rev-parse` answers about the **current working directory**, not about the script. The
operator ran the script *by path* from inside a different checkout. `REPO_ROOT` resolved to that
other repository. The script wrote its report there, and the probe that existed to detect
launcher drift compared a checksum against a path that does not exist:

```
sha256sum: /home/user/Projects/other-repo/files/var/local/tool/tool:
           No such file or directory
```

It then printed `Could not checksum both files` and **exited zero**.

That is the failure class this whole proposal is about: **a control that reports success without
having done its job.** The script did not crash. It did not warn. It degraded the one check that
mattered into a shrug, and the shrug looked like a pass.

### 1.2 Why fixing that script would have fixed nothing

The guidance it followed was wrong, and the guidance was a ~40-line safety preamble that gets
**hand-copied into every new plan script**. Measured in the project this came from: a fix landed
in one plan's script and regressed in the next plan's the following day, because the fix lived in
a comment the next author did not copy.

A hand-copied preamble diverges on every copy. That is not a discipline problem; it is a
structural one. The dangerous primitives belong in one tested library where the correct behaviour
is the **only** behaviour on offer.

### 1.3 Why this belongs in the daemon rather than in each project

The daemon already asserts that plans exist, are numbered, are indexed, are journalled and are
archived atomically. A plan that needs something *run* is the overwhelmingly common case, and
right now the daemon says nothing about it — so each project invents its own, badly, and the
daemon's own `plan_script_qa`-shaped guidance has nowhere to live.

Three projects in one organisation independently grew a variant of this library. Three libraries
with a shared ancestor **will** drift. Drift that is upstream is visible; drift that is
per-project is invisible.

---

## 2. Design: what is generic and what is not

The library that exists today is Ansible-flavoured. That flavour is **one seam**, not a design
assumption. The split:

```
┌──────────────────────────────────────────────────────────┐
│ GENERIC CORE — proposed for the daemon                   │
│                                                          │
│  · script-relative, boundary-bounded root resolution     │
│  · run log: named pipe, deterministic drain, ANSI strip  │
│  · signal handling (EXIT + INT/TERM/HUP)                 │
│  · log scrubbing via a SEPARATE process, with quarantine │
│  · /dev/tty prompts that do not race the log             │
│  · the change gate + the backstop assertion              │
│  · mode (deploy|gather) and leg semantics                │
│  · shared flag vocabulary (--check / -y / -h)            │
│  · ssh-agent key loading, fingerprint-idempotent         │
│  · plan_finish: exit status agrees with the text         │
└───────────────────────────┬──────────────────────────────┘
                            │  ONE seam
┌───────────────────────────▼──────────────────────────────┐
│ PROJECT ADAPTER — supplied per project                   │
│                                                          │
│  · PLANLIB_ROOT_MARKER      what marks the repo root     │
│  · PLANLIB_DELEGATE         the command runner, if any   │
│  · PLANLIB_SCRUBBER         the secret scrubber          │
│  · PLANLIB_PLAN_DIR         where plans live             │
│  · plan_target_valid()      optional target validation   │
└──────────────────────────────────────────────────────────┘
```

An Ansible project sets `PLANLIB_DELEGATE` to its `ansible-run.bash` wrapper. A Kubernetes
project sets it to a `kubectl` context wrapper. A project with no delegate at all leaves it unset
and calls commands directly through the leg runners — everything else still applies, because
nothing above the seam knows what a playbook is.

---

## 3. The generic core

Presented as a single file. Every design decision that is load-bearing carries its reason inline,
because these are the comments that stopped being copied.

### 3.1 Header and configuration seam

```bash
# shellcheck shell=bash
#
# _planlib.inc.bash — sourced helper library for plan-folder orchestrators.
#
# WHAT THIS IS
#   The one tested implementation of the safety-critical primitives a plan's
#   deploy/verify/triage script needs: script-relative repo-root resolution,
#   ssh-agent loading, a tee'd run log with a deterministic drain, /dev/tty
#   prompts, the change gate, and fail-fast-vs-continue leg semantics.
#   A conforming orchestrator is BOOTSTRAP + MODE + LEGS and hand-rolls none of it.

if [[ -n "${PLANLIB_SOURCED:-}" ]]; then
    return 0
fi

PLANLIB_VERSION="1.0.0"
PLANLIB_SOURCED=1
export PLANLIB_VERSION

# ── CONFIGURATION SEAM ───────────────────────────────────────────────────────
# Every project-specific fact lives here and nowhere else. Each may be set by
# the project before sourcing, or left at its default.

# What file marks the repository root? The walk stops at this. A project using
# Ansible sets "ansible.cfg"; one using Node sets "package.json"; the safe
# universal fallback is a file the project guarantees exists at the root.
PLANLIB_ROOT_MARKER="${PLANLIB_ROOT_MARKER:-}"

# Where plans live, repo-relative. Used only for messages and for `auto` log
# placement; the library never enumerates it.
PLANLIB_PLAN_DIR="${PLANLIB_PLAN_DIR:-CLAUDE/Plan}"

# The command runner a leg delegates to, repo-relative. Optional. When set, it
# MUST already handle credentials, targeting and cleanup — the library refuses
# to re-derive any of that (see §3.7).
PLANLIB_DELEGATE="${PLANLIB_DELEGATE:-}"

# The secret scrubber, repo-relative. Optional but strongly recommended when
# run logs are tracked. Contract: `<scrubber> <file>` rewrites the file in
# place and exits 0 on success. See §3.5.
PLANLIB_SCRUBBER="${PLANLIB_SCRUBBER:-}"

# ── run state ────────────────────────────────────────────────────────────────
PLAN_SCRIPT_DIR=""
PLAN_REPO_ROOT=""
PLAN_MODE=""
PLAN_LOG_STARTED=0
PLAN_RUN_DIR=""
PLAN_RUN_LOG=""
PLAN_GATE_PASSED=0
PLAN_CHECK="${PLAN_CHECK:-0}"
PLAN_ASSUME_YES="${PLAN_ASSUME_YES:-0}"
PLAN_USAGE="${PLAN_USAGE:-}"
PLAN_TTY_PROBE_ERR=""
PLAN_TEE_PID=""
PLAN_TRAP_DONE=0
PLAN_FAILED_LEGS=""
PLAN_CHECK_ARGS=()
PLAN_REMAINING_ARGS=()
_PLAN_ARGV=()

export PLAN_MODE PLAN_CHECK PLAN_GATE_PASSED
```

**Why `PLANLIB_ROOT_MARKER` has no default.** A wrong default resolves to *something*, and
something is worse than nothing here — that is the original incident. An unset marker must be a
hard error at `plan_init`, not a fallback to `.git` (see §3.3 for why `.git` is the *boundary*
and must not also be the *marker*).

### 3.2 Loud failure, and why `_plan_err` never exits

```bash
# _plan_err <message> — print loudly and return 1. It never calls `exit`, so callers
# choose between fatal (deploy) and record-and-continue (gather), and every path stays
# testable. Call it as `_plan_err "..." || return 1`: that form is errexit-safe, whereas
# a bare call followed by `return 1` would abort the caller before the return.
_plan_err() {
    printf '[FATAL] %s\n' "$*" >&2
    return 1
}

_plan_banner() {
    printf '============================================================\n'
    printf '==> %s\n' "$*"
    printf '============================================================\n'
}
```

The `|| return 1` calling convention is not stylistic. Under `set -e`, a bare `_plan_err "..."`
returns non-zero and terminates the *caller* at that line — so the `return 1` you wrote after it
never runs, and any cleanup between them is skipped. Writing it as one expression makes the
control flow the same whether or not errexit is on.

### 3.3 Root resolution — the primitive the incident was about

```bash
# _plan_find_repo_root <start_dir> — walk up from <start_dir> to the repo's marker,
# filesystem-only, BOUNDED BY THE REPOSITORY BOUNDARY. Echoes the root, or returns 1.
#
# Order matters: the marker is tested BEFORE the boundary, because a repo root holds both.
# The boundary test is a plain -e so it catches a worktree's `.git` FILE as well as a normal
# `.git` directory — and involves no `git` command, which is the point (a worktree's git
# links do not resolve the same way everywhere, and `git rev-parse` answers about the CWD,
# not about this script).
_plan_find_repo_root() {
    local dir="$1"
    while [[ "${dir}" != "/" ]]; do
        if [[ -e "${dir}/${PLANLIB_ROOT_MARKER}" ]]; then
            printf '%s' "${dir}"
            return 0
        fi
        if [[ -e "${dir}/.git" ]]; then
            return 1
        fi
        dir="$(dirname "${dir}")"
    done
    return 1
}
```

Three properties, each of which has been got wrong in the wild:

1. **Script-relative, not cwd-relative.** The walk starts at the calling script's own directory,
   resolved via `BASH_SOURCE` + `pwd -P`. `git rev-parse --show-toplevel` answers a different
   question and answers it confidently.

2. **Filesystem-only.** No `git` invocation at all. A worktree's git links do not resolve
   identically across git versions and mount layouts, and a subprocess is a dependency the walk
   does not need.

3. **Bounded at the repository boundary, and this is load-bearing.** Nested checkouts are
   ordinary — vendored repos, sibling projects under a scratch directory, a template checked out
   inside its consumer. An *unbounded* walk from a script in the inner repo sails past it and
   finds the **outer** repo's marker, and then appears to work. Failing loudly beats operating on
   the wrong repository.

   This is why the marker must not be `.git`: if marker and boundary are the same file, the
   boundary check can never fire.

### 3.4 `plan_init` and `plan_mode`

```bash
# plan_init "${BASH_SOURCE[0]}" — resolve the repo layout from the CALLING SCRIPT's own
# location, never from the cwd. Idempotent. Fails loudly rather than guessing.
plan_init() {
    # NOTE: no apostrophes in a ${var:?word} message. The word is quote-processed, so an
    # apostrophe opens a quoted section and breaks the parse of everything after it.
    local callerSource="${1:?plan_init requires the calling script BASH_SOURCE[0]}"
    local callerDir=""

    if [[ -z "${PLANLIB_ROOT_MARKER}" ]]; then
        _plan_err "PLANLIB_ROOT_MARKER is unset. Set it to the file that marks this repository's root BEFORE sourcing planlib. There is deliberately no default: a wrong default resolves to some other directory and the script then operates on the wrong repository." || return 1
    fi
    if ! callerDir="$(cd "$(dirname "${callerSource}")" && pwd -P)"; then
        _plan_err "plan_init could not resolve the directory holding ${callerSource}" || return 1
    fi
    PLAN_SCRIPT_DIR="${callerDir}"
    if ! PLAN_REPO_ROOT="$(_plan_find_repo_root "${PLAN_SCRIPT_DIR}")"; then
        _plan_err "no ${PLANLIB_ROOT_MARKER} between ${PLAN_SCRIPT_DIR} and its repository boundary. The walk stops at the repo boundary ON PURPOSE so a nested checkout can never resolve to its parent repo." || return 1
    fi

    if [[ -n "${PLANLIB_DELEGATE}" ]] && [[ ! -x "${PLAN_REPO_ROOT}/${PLANLIB_DELEGATE}" ]]; then
        _plan_err "the configured delegate is missing or not executable: ${PLAN_REPO_ROOT}/${PLANLIB_DELEGATE}" || return 1
    fi

    export PLAN_SCRIPT_DIR PLAN_REPO_ROOT
    return 0
}

# plan_mode <deploy|gather> — declare the run's nature up front. deploy enables fail-fast
# legs and REQUIRES the change gate before the first delegated command; gather enables
# record-and-continue legs and FORBIDS the gate.
plan_mode() {
    local mode="${1:?plan_mode requires deploy or gather}"
    case "${mode}" in
        deploy | gather) ;;
        *) _plan_err "plan_mode must be 'deploy' or 'gather', got '${mode}'" || return 1 ;;
    esac
    PLAN_MODE="${mode}"
    export PLAN_MODE
    return 0
}
```

### 3.5 The run log — the part most likely to be got wrong

This is the section worth reading closely if you read only one. It contains three separate
subtleties that each produce a **silently truncated forensic record**.

```bash
# plan_start_log [auto|<path>] — open the tee'd run log AND arm the drain handler in ONE
# call, so a log can never be opened without the handler that finalises it. `auto` puts it
# in a per-run timestamped directory under the plan folder, so no run clobbers a previous
# run's forensics.
#
# After this call the terminal is "dirty": every prompt must go through plan_confirm.
plan_start_log() {
    local where="${1:-auto}" base="" fifo="" stamp=""
    if [[ -z "${PLAN_SCRIPT_DIR}" ]]; then
        _plan_err "plan_start_log called before plan_init" || return 1
    fi
    if [[ "${where}" == "auto" ]]; then
        base="$(basename "$0")"
        base="${base%.bash}"
        stamp="$(date '+%Y%m%d-%H%M%S')"
        PLAN_RUN_DIR="${PLAN_SCRIPT_DIR}/${base}-runs/${stamp}"
        PLAN_RUN_LOG="${PLAN_RUN_DIR}/${base}.log"
    else
        PLAN_RUN_DIR="$(dirname "${where}")"
        PLAN_RUN_LOG="${where}"
    fi
    if ! mkdir -p "${PLAN_RUN_DIR}"; then
        _plan_err "could not create the run directory ${PLAN_RUN_DIR}" || return 1
    fi
    export PLAN_RUN_DIR PLAN_RUN_LOG

    # Keep the REAL stderr on fd 9 so the finalize handler can still reach the console after
    # stdout/stderr have been pointed at the fifo.
    exec 9>&2

    # Many tools emit ANSI only to a TTY, and our stdout is about to become a fifo — so
    # without this the console would go monochrome. Force colour on when the real terminal
    # is a TTY; the file branch below strips ANSI, so the log stays clean either way.
    if [[ -t 9 ]] && [[ -n "${PLANLIB_FORCE_COLOR_VAR:-}" ]]; then
        export "${PLANLIB_FORCE_COLOR_VAR}=1"
    fi

    fifo="${PLAN_RUN_DIR}/.planlib-tee.fifo"
    if [[ -e "${fifo}" ]]; then
        rm -f "${fifo}"
    fi
    if ! mkfifo "${fifo}"; then
        _plan_err "could not create the run-log fifo ${fifo}" || return 1
    fi

    # Split the stream: fd 3 carries raw bytes (with colour) to the real console, while the
    # file branch goes through an ANSI stripper that fflush()es so the log updates live.
    # Wrapping the pipeline in `{ …; } 3>&1 &` yields a SINGLE waitable PID whose completion
    # means the stripper flushed the WHOLE log — which is what makes the drain deterministic.
    # The reader is started BEFORE the write-open below, so the open rendezvous instead of
    # blocking forever.
    { tee /dev/fd/3 <"${fifo}" \
        | awk '{ gsub(/\033\[[0-9;]*[A-Za-z]/, ""); print; fflush() }' \
            >"${PLAN_RUN_LOG}"; } 3>&1 &
    PLAN_TEE_PID=$!
    exec >"${fifo}" 2>&1
    # The fd survives the unlink and the reader holds the other end; removing the path just
    # keeps a stray fifo out of the plan folder.
    rm -f "${fifo}"
    PLAN_LOG_STARTED=1

    # Arm for EXIT *and* the fatal signals. EXIT alone would miss a Ctrl-C, and the lines
    # lost would be exactly the ones written as the run died.
    trap '_plan_finalize_log' EXIT
    trap '_plan_on_signal INT' INT
    trap '_plan_on_signal TERM' TERM
    trap '_plan_on_signal HUP' HUP

    printf '==> run log: %s\n' "${PLAN_RUN_LOG}"
    return 0
}
```

**Subtlety 1 — a named pipe, not `>(…)`.** The obvious spelling is
`exec > >(tee "${log}") 2>&1`. It is wrong in a way that only shows up when it matters: a process
substitution **cannot be waited on**. There is no PID to `wait`, so when the script exits the
final buffered chunk may never reach the file — and the final chunk is the lines written as the
run was dying, which is the reason you kept a log at all. A `mkfifo` + background reader gives a
waitable PID.

**Subtlety 2 — one PID for the whole pipeline.** `{ tee … | awk … ; } 3>&1 &` backgrounds the
*group*, so `$!` is a single PID whose exit means the last stage flushed. Backgrounding the
stages separately would give you a PID whose completion says nothing about the stripper.

**Subtlety 3 — arm for signals, not just EXIT.** A `trap … EXIT` alone does not fire on `Ctrl-C`
in the way people expect, and the interrupt case is precisely the one where the tail of the log
carries the diagnosis.

```bash
# _plan_finalize_log — EXIT/signal handler. Points stdout/stderr back at the real terminal
# (which closes the fifo's write end so the log writer sees EOF), WAITS for the writer to
# flush every buffered byte, then SCRUBS the log and tells the operator where it is.
# Runs at most once.
#
# The scrub happens here rather than in `plan_finish` because a run that dies on a signal
# still produced a log, and that is exactly the log most likely to have caught something
# mid-flight.
_plan_finalize_log() {
    if [[ "${PLAN_TRAP_DONE}" -eq 1 ]]; then
        return 0
    fi
    PLAN_TRAP_DONE=1
    if [[ "${PLAN_LOG_STARTED}" -ne 1 ]]; then
        return 0
    fi
    exec 1>&9 2>&9
    if [[ -n "${PLAN_TEE_PID}" ]]; then
        if ! wait "${PLAN_TEE_PID}"; then
            printf '[WARN] the run-log writer exited non-zero (it may have been killed by the same signal); %s may be short\n' \
                "${PLAN_RUN_LOG}" >&2
        fi
    fi
    if ! _plan_scrub_log; then
        printf '==> [WARN] the run log was not scrubbed — see the reason above.\n' >&2
    fi
    printf '==> run log: %s\n' "${PLAN_RUN_LOG}" >&2
    exec 9>&-
}

# _plan_on_signal <SIG> — drain and report, then re-raise the signal's default disposition
# so the exit status still reflects the signal and the handler cannot run twice.
_plan_on_signal() {
    local sig="$1"
    _plan_finalize_log
    trap - EXIT "${sig}"
    kill "-${sig}" "$$"
}
```

**The ordering `wait` → `scrub` is load-bearing.** Scrubbing before the drain would clean the file
and then let the writer append the final buffered chunk **past** the scrubber, into a log that
now reports itself clean. That is the failure class again: a control that ran, reported success,
and left the thing it was checking untouched.

### 3.6 Log scrubbing — layered, and the layers are ordered

```bash
# _plan_quarantine_log <reason> — the scrub did NOT happen, so make the log uncommittable.
#
# Renaming to `.unscrubbed` (which the plan directory's .gitignore excludes) is the whole
# mechanism: a log nobody cleaned must not be sweepable into a commit by a later `git add -A`.
# The failure mode of this library is therefore "you lose the log from git", never "an
# unscrubbed log looks committable".
_plan_quarantine_log() {
    local reason="$1" quarantine="${PLAN_RUN_LOG}.unscrubbed"
    printf '\n==> [WARN] run log NOT scrubbed: %s\n' "${reason}" >&2
    if mv "${PLAN_RUN_LOG}" "${quarantine}"; then
        PLAN_RUN_LOG="${quarantine}"
        printf '==> quarantined as %s (gitignored) — treat it as a secret.\n' "${PLAN_RUN_LOG}" >&2
    else
        printf '==> [WARN] could not even quarantine it. DO NOT COMMIT %s\n' "${PLAN_RUN_LOG}" >&2
    fi
    printf '==> fix the cause and re-run, or scrub by hand.\n' >&2
}

# _plan_scrub_log — hand the finished run log to the SEPARATE scrubber process.
_plan_scrub_log() {
    local scrubber="" scrubOut="" scrubRc=0

    if [[ ! -f "${PLAN_RUN_LOG}" ]]; then
        printf '\n==> [WARN] there is no run log to scrub at %s\n' "${PLAN_RUN_LOG}" >&2
        return 1
    fi
    if [[ -z "${PLANLIB_SCRUBBER}" ]]; then
        return 0          # a project that does not track logs need not configure one
    fi
    scrubber="${PLAN_REPO_ROOT}/${PLANLIB_SCRUBBER}"
    if [[ ! -x "${scrubber}" ]]; then
        _plan_quarantine_log "the scrubber is missing or not executable: ${scrubber}"
        return 1
    fi

    scrubOut="$("${scrubber}" "${PLAN_RUN_LOG}" 2>&1)" || scrubRc=$?
    if [[ "${scrubRc}" -ne 0 ]]; then
        _plan_quarantine_log "the scrubber exited ${scrubRc}: ${scrubOut}"
        return 1
    fi

    printf '\n==> run log scrubbed (layer 2): %s\n' "${scrubOut}" >&2
    return 0
}
```

**Three layers, and the ORDER is the design:**

| Layer | Mechanism                                                          | Status            |
| ----- | ------------------------------------------------------------------ | ----------------- |
| 1     | The command never emits the secret (e.g. Ansible's `no_log: true`) | **primary**       |
| 2     | The finished log is handed to a separate scrubber process          | safety net        |
| 3     | A commit-time gate refuses a staged file containing secret shapes  | should never fire |

The scrubber is a **separate process on purpose**: the thing that writes the log must not also be
the thing that certifies it clean. And layer 2 must never become the reason a task omits layer 1 —
that inverts the ordering and makes the last line of defence the first.

**A clean scrub means "none of the KNOWN shapes are present"**, never "this log is safe". Whatever
the scrubber cannot reach should be listed in the scrubber's own header, not implied.

**Why `.unscrubbed` rather than deleting or failing the run**: the run already happened; its
output is the forensic record. Deleting it destroys evidence; failing loudly after the fact does
not un-write it. Renaming it into a gitignored name means the *only* thing you can lose is the
log's presence in git, and never an uncleaned log's presence in a commit.

### 3.7 Prompts, and why they must not bypass the log

```bash
# _plan_tty_openable — can the controlling terminal actually be OPENED? Existence is not
# enough: /dev/tty exists even with no controlling terminal (e.g. under `setsid </dev/null`),
# where opening it fails with ENXIO. The probe CAPTURES the failure reason into
# PLAN_TTY_PROBE_ERR rather than discarding it, so the fatal message can quote it. `true`
# (a regular builtin) is used rather than `:` or `exec` so a failed redirect cannot take the
# shell down.
_plan_tty_openable() {
    local probeErr=""
    if probeErr="$( { true >/dev/tty; } 2>&1 )"; then
        PLAN_TTY_PROBE_ERR=""
        return 0
    fi
    PLAN_TTY_PROBE_ERR="${probeErr}"
    return 1
}

# _plan_strip_cr <string> — drop a single TRAILING carriage return. A terminal in raw/mixed
# mode can leave a CR on a reply, which silently breaks an exact token match.
_plan_strip_cr() {
    local s="$1"
    printf '%s' "${s%$'\r'}"
}

# plan_confirm <prompt> [expected-token] — ask for typed consent. Returns 0 only on an exact
# token match.
#
# The prompt TEXT goes to ORDINARY STDOUT so it flows through the tee in order, behind the
# banner and log lines that precede it. Writing it straight to /dev/tty would be unbuffered,
# bypass the tee, and race AHEAD of still-buffered output — the prompt then appears above its
# own banner. The trailing newline is mandatory: a partial line block-buffers in the tee/awk
# pipeline and the run wedges with no visible prompt at all.
#
# The REPLY is read from /dev/tty because delegated commands drain the inherited stdin, so a
# plain `read` later in the run would misfire.
plan_confirm() {
    local prompt="${1:?plan_confirm requires a prompt}" expected="${2:-yes}" reply=""
    if [[ "${PLAN_ASSUME_YES}" == "1" ]]; then
        printf '==> %s [auto-confirmed via -y/--yes/PLAN_ASSUME_YES]\n' "${prompt}"
        return 0
    fi
    if ! _plan_tty_openable; then
        _plan_err "cannot prompt for '${prompt}': no controlling terminal (${PLAN_TTY_PROBE_ERR}). Re-run from a terminal, or pass -y/--yes to consent non-interactively." || return 1
    fi
    printf '\n%s\n>>> type "%s" and press Enter to proceed: \n' "${prompt}" "${expected}"
    IFS= read -r reply </dev/tty
    reply="$(_plan_strip_cr "${reply}")"
    if [[ "${reply}" == "${expected}" ]]; then
        return 0
    fi
    printf '==> not confirmed (got "%s", expected "%s")\n' "${reply}" "${expected}" >&2
    return 1
}
```

Four independent traps are closed here, and each has a visible symptom:

| Trap                                | Symptom if got wrong                                                                |
| ----------------------------------- | ----------------------------------------------------------------------------------- |
| Prompt written to `/dev/tty`        | prompt appears **above** its own banner, because it is unbuffered and races the tee |
| Prompt without a trailing newline   | run **wedges with a blank screen** — the partial line block-buffers in the pipeline |
| Reply read from stdin               | a delegated command drained stdin, so `read` gets EOF and the answer is empty       |
| `[ -e /dev/tty ]` used as the probe | passes under `setsid`, then the open fails at the worst moment                      |

### 3.8 The change gate — gate on state change, never on target name

```bash
# plan_gate_change <description> — the one gate a state-changing run passes before its first
# mutating leg. Skipped under --check: a dry run changes nothing.
plan_gate_change() {
    local desc="${1:-a change to live infrastructure}"
    if [[ "${PLAN_MODE}" == "gather" ]]; then
        _plan_err "plan_gate_change called in gather mode — a read-only run changes nothing, so there is nothing to gate. Use 'plan_mode deploy' for a state-changing run." || return 1
    fi
    if [[ "${PLAN_MODE}" != "deploy" ]]; then
        _plan_err "plan_gate_change requires 'plan_mode deploy' to be declared first (mode is '${PLAN_MODE:-unset}')" || return 1
    fi
    if [[ "${PLAN_CHECK}" == "1" ]]; then
        printf '==> [--check] change gate for "%s" auto-passed (a dry run changes nothing)\n' "${desc}"
        PLAN_GATE_PASSED=1
        export PLAN_GATE_PASSED
        return 0
    fi
    if plan_confirm "LIVE CHANGE: ${desc}. This CHANGES live state." "change-live"; then
        PLAN_GATE_PASSED=1
        export PLAN_GATE_PASSED
        return 0
    fi
    _plan_err "change gate not confirmed — aborting before the first mutating leg" || return 1
}

# _plan_assert_change_allowed — the last line of defence. In deploy mode nothing may reach a
# delegated command until the gate has passed, so a script that FORGETS plan_gate_change
# fails here instead of changing state unannounced. Gather mode passes straight through.
_plan_assert_change_allowed() {
    if [[ "${PLAN_MODE}" == "deploy" ]] && [[ "${PLAN_GATE_PASSED}" -ne 1 ]]; then
        _plan_err "a deploy-mode command was attempted before the change gate passed — call plan_gate_change '<what changes>' first" || return 1
    fi
    return 0
}
```

**The conventional model is "gate production, wave the rest through".** That model assumes most
environments are safe to break, which is true in some organisations and false in many. Where
there is one environment and it is live, name-gating gates either everything or nothing.

The axis that always carries meaning is **does this run change state**. `plan_mode deploy` gates
once; `plan_mode gather` must **not** gate at all — a read-only run has nothing to gate, and a
pointless prompt teaches operators to type through gates, which is how the real one gets waved
past.

`_plan_assert_change_allowed` is what makes the gate more than a convention: forgetting to call
it is an error, not a silent omission.

### 3.9 Legs — fail-fast versus record-and-continue

```bash
# plan_deploy_leg <name> <cmd...> — fail-fast leg for a state-changing run. On failure it
# prints [ABORT] and terminates the whole run immediately, so nothing downstream of a broken
# leg ever executes.
#
# It MUST be a bare top-level statement. Inside $(...), a pipeline, or ( ), its abort would
# terminate only the subshell and control would flow straight on to the NEXT leg — the run
# would look like it aborted while actually continuing. BASH_SUBSHELL detects that misuse and
# takes the whole run down rather than half-obeying.
plan_deploy_leg() {
    local name="${1:?plan_deploy_leg requires a leg name}"
    shift
    if [[ "${BASH_SUBSHELL}" -ne 0 ]]; then
        printf '[FATAL] plan_deploy_leg "%s" was invoked inside a subshell, pipeline or command substitution (BASH_SUBSHELL=%s). A failed leg would terminate only the subshell and the run would continue to the NEXT leg. Call it as a bare top-level statement.\n' \
            "${name}" "${BASH_SUBSHELL}" >&2
        kill -TERM "$$"
        exit 1
    fi
    if [[ "${PLAN_MODE}" != "deploy" ]]; then
        _plan_err "plan_deploy_leg used but the mode is '${PLAN_MODE:-unset}'. Declare 'plan_mode deploy' — a state-changing run is fail-fast." || return 1
    fi
    _plan_banner "[deploy leg] ${name}"
    if ! "$@"; then
        printf '[ABORT] leg "%s" failed — stopping here, nothing further will run\n' "${name}" >&2
        exit 1
    fi
    return 0
}

# plan_gather_leg <name> <cmd...> — record-and-continue leg for a READ-ONLY run. A failure
# is recorded by name and drives a non-zero final exit, so collecting as much as possible
# never turns into reporting success.
plan_gather_leg() {
    local name="${1:?plan_gather_leg requires a leg name}"
    shift
    if [[ "${PLAN_MODE}" != "gather" ]]; then
        _plan_err "plan_gather_leg used but the mode is '${PLAN_MODE:-unset}'. Declare 'plan_mode gather' — only a read-only run may continue past a failed leg." || return 1
    fi
    _plan_banner "[gather leg] ${name}"
    if ! "$@"; then
        printf '[WARN] gather leg "%s" failed (continuing)\n' "${name}" >&2
        PLAN_FAILED_LEGS="${PLAN_FAILED_LEGS}${PLAN_FAILED_LEGS:+ }${name}"
    fi
    return 0
}
```

**The `BASH_SUBSHELL` guard is the subtlest thing in the library.** `plan_deploy_leg` implements
"abort the whole run" with `exit`. Inside `$( … )`, a pipeline stage, or `( … )`, `exit` ends only
the subshell — so a *failed* leg would print `[ABORT]`, and the script would carry straight on to
the next one. The run looks aborted and is not. `kill -TERM "$$"` takes the real process down.

There is deliberately **no** "continue past a failed deploy leg to gather more". If you want
that, the run is a gather.

### 3.10 Delegation — never re-derive the runner's argv

```bash
# plan_run <cmd...> — run a command through the project's delegate, if one is configured, or
# directly if not. stdin is closed so a delegated command cannot drain the script's own stdin
# out from under a later prompt.
plan_run() {
    _plan_assert_change_allowed || return 1
    if [[ -n "${PLANLIB_DELEGATE}" ]]; then
        _PLAN_ARGV=(
            "${PLAN_REPO_ROOT}/${PLANLIB_DELEGATE}"
            ${PLAN_CHECK_ARGS[@]+"${PLAN_CHECK_ARGS[@]}"}
            "$@"
        )
    else
        _PLAN_ARGV=( "$@" )
    fi
    "${_PLAN_ARGV[@]+"${_PLAN_ARGV[@]}"}" </dev/null
}
```

**The rule this encodes: a plan script never rebuilds what the project's runner already does.**

In the originating project the delegate resolves a connect identity from an encrypted variable,
decrypts a connection key and its passphrase, loads them into a *private* ssh-agent, builds a
bastion `ProxyCommand`, and shreds every credential on the way out via an EXIT trap. A plan
script that hand-rolls `ansible-playbook --vault-id … -i …` gets the two obvious flags right and
**silently drops all of the rest** — producing a script that looks correct and cannot reach a
single host.

Generically: whatever your runner does beyond "assemble two flags" is invisible to the person
copying the two flags. Delegate, or accept that every plan script re-implements your auth.

Argv is built as an **array**, never a string, so nothing is word-split and no
shellcheck-suppression is needed to make it lint.

### 3.11 Closing, and the flag vocabulary

```bash
# plan_finish — the closing statement of every plan script: list reports, summarise failed
# legs, and terminate with a status that AGREES with the text. It ends the run deliberately,
# so anything written after a plan_finish call is dead code.
plan_finish() {
    plan_list_reports
    if [[ -n "${PLAN_FAILED_LEGS}" ]]; then
        printf '==> FAILED legs: %s\n' "${PLAN_FAILED_LEGS}" >&2
        [[ -n "${PLAN_RUN_LOG}" ]] && printf '==> run log: %s\n' "${PLAN_RUN_LOG}"
        exit 1
    fi
    printf '==> all legs OK\n'
    [[ -n "${PLAN_RUN_LOG}" ]] && printf '==> run log: %s\n' "${PLAN_RUN_LOG}"
    exit 0
}

# plan_parse_common_flags "$@" — consume the flags every plan script shares and leave the
# rest in PLAN_REMAINING_ARGS. Set PLAN_USAGE first to get a useful --help.
#
#   --check     thread a dry-run flag into every delegated command
#   -y|--yes    consent non-interactively (skips plan_confirm / plan_gate_change prompts)
#   -h|--help   print PLAN_USAGE and stop
plan_parse_common_flags() {
    PLAN_REMAINING_ARGS=()
    local arg
    for arg in "$@"; do
        case "${arg}" in
            --check)
                PLAN_CHECK=1
                PLAN_CHECK_ARGS=("${PLANLIB_CHECK_FLAG:---check}")
                export PLAN_CHECK
                ;;
            -y | --yes)
                PLAN_ASSUME_YES=1
                export PLAN_ASSUME_YES
                ;;
            -h | --help)
                if [[ -n "${PLAN_USAGE}" ]]; then
                    printf '%s\n' "${PLAN_USAGE}"
                else
                    printf 'usage: %s [--check] [-y|--yes] [-h|--help] [args...]\n' "$(basename "$0")"
                fi
                exit 0
                ;;
            *) PLAN_REMAINING_ARGS+=("${arg}") ;;
        esac
    done
    return 0
}
```

**`plan_finish` exists so that the exit status agrees with the text.** A script that prints a
summary and then falls off the end returns the status of whatever ran last, which is routinely
`0` after a `printf`. A run with failed gather legs that exits `0` is the failure class again.

### 3.12 The one deliberate deviation from "a library never exits"

Standard bash guidance — and the originating project's own bash standard — says a **sourced
library must never call `exit`**, because it runs in the caller's shell and would kill the caller
mid-script, skipping cleanup traps.

Three functions here break that on purpose: `plan_deploy_leg`, `plan_finish`, and
`plan_parse_common_flags --help`. For the first two, **"abort the whole run" is the contract**,
and delegating it to the caller (`|| exit 1` at every call site) reintroduces exactly the
catastrophe the primitive exists to prevent: one forgotten guard and a failed leg flows into the
next one.

Two things keep this honest:

- The library still sets **no** shell options. The caller owns `set -euo pipefail`.
- **The test suite pins the deviation to exactly those three functions**, so a fourth cannot grow
  one unnoticed. Extending the exception means extending that test.

---

## 4. The canonical bootstrap

Copied verbatim into every orchestrator. It is the one part that cannot live in the library,
because it is what *finds* the library.

```bash
#!/usr/bin/env bash
set -euo pipefail
scriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repoRoot="${scriptDir}"
while [[ "${repoRoot}" != "/" ]] && [[ ! -e "${repoRoot}/<MARKER>" ]]; do
  if [[ -e "${repoRoot}/.git" ]]; then
    printf '[FATAL] no <MARKER> between %s and the repo root %s\n' "${scriptDir}" "${repoRoot}" >&2
    exit 1
  fi
  repoRoot="$(dirname "${repoRoot}")"
done
[[ -e "${repoRoot}/<MARKER>" ]] || { printf '[FATAL] no <MARKER> above %s\n' "${scriptDir}" >&2; exit 1; }
# shellcheck source-path=SCRIPTDIR/..
# shellcheck source-path=SCRIPTDIR/../..
# shellcheck source=_planlib.inc.bash
source "${repoRoot}/<PLAN_DIR>/_planlib.inc.bash"
plan_init "${BASH_SOURCE[0]}"
```

### Why there are TWO `source-path` lines

This looks like redundancy and is not. `source-path=SCRIPTDIR` makes the relative `source=` path
resolve from the *script's* directory rather than shellcheck's cwd; without it, `shellcheck -x`
cannot follow the library, emits SC1091, and **every check that depended on following it silently
lapses** (`PLAN_USAGE` starts reading as an unused variable, and so on).

The subtle part: **a plan folder moves.** While the plan is active it sits at
`<plan_dir>/NNNNN-name/`, where `..` is `<plan_dir>/`. Completing the plan `git mv`s it to
`<plan_dir>/Completed/NNNNN-name/`, where `..` is `<plan_dir>/Completed/` — the library is no
longer there, SC1091 fires, and the whole cascade returns.

If CI runs a bare `shellcheck -x` with **no severity floor**, an *info*-level SC1091 fails the
build. So **archiving a plan turns `main` red**, and the commit that does it looks entirely
unrelated to shell code. Listing both `SCRIPTDIR/..` and `SCRIPTDIR/../..` makes the directive
depth-independent, so the archive move stays a pure rename.

This is not hypothetical — it is what happened the first time a library-based plan was archived.

**These are source *directives*, not suppressions.** They tell the linter where to look, which is
the opposite of hiding something.

---

## 5. Reference skeletons

Each is **bootstrap + mode + legs**; the library carries everything else.

### Read-only gather (triage / report / verify)

```bash
#!/usr/bin/env bash
# triage.bash — gather <facts>. READ-ONLY: continues past a failed leg, never gates,
# changes nothing.
#
# WHERE TO RUN: on the operator's machine, by a human.
# Usage: ./<plan_dir>/<plan>/triage.bash [--check] [-h|--help]
# Idempotent: reads only; safe to re-run any number of times.
<BOOTSTRAP>

PLAN_USAGE="usage: triage.bash [--check] [-h|--help]"
plan_mode gather
plan_parse_common_flags "$@"
plan_start_log auto

plan_gather_leg "collect facts"   plan_run <cmd…>
plan_gather_leg "reachability"    plan_run <cmd…>
plan_finish
```

### State-changing deploy (gated, fail-fast)

```bash
#!/usr/bin/env bash
# deploy.bash — deploy <thing>. STATE-CHANGING: gated once, then fail-fast.
#
# WHERE TO RUN: on the operator's machine, by a human.
# Usage: ./<plan_dir>/<plan>/deploy.bash [--check] [-y|--yes] [-h|--help]
# Idempotent: re-running converges; <state the specific idempotence claim here>.
<BOOTSTRAP>

PLAN_USAGE="usage: deploy.bash [--check] [-y|--yes] [-h|--help]"
plan_mode deploy
plan_parse_common_flags "$@"

plan_load_ssh_keys "${HOME}/.ssh/id_ed25519"   # BEFORE the log; omit if not needed
plan_start_log auto

# One gate, before the first mutating leg. --check auto-passes.
plan_gate_change "deploy <thing> to live infrastructure"

plan_deploy_leg "converge" plan_run <cmd…>
plan_deploy_leg "verify"   plan_run <cmd…>
plan_finish
```

### The "it is only one command" case still ships a script

```bash
#!/usr/bin/env bash
# verify.bash — verify the deployed version of <thing>. Read-only.
<BOOTSTRAP>
plan_mode gather
plan_parse_common_flags "$@"
plan_start_log auto
plan_gather_leg "version" plan_run <cmd…>
plan_finish
```

**One command still ships as a script.** Pasted command lists get garbled, run from the wrong
directory, lose their output, and skip legs. A committed script is reviewable, idempotent,
self-logging, re-runnable, and travels with the plan.

---

## 6. `plan_load_ssh_keys` — ordering as an enforced contract

```bash
# plan_load_ssh_keys <keyfile>... — load the operator's keys into ssh-agent.
#
# MUST run BEFORE plan_start_log: a passphrase prompt issued after the tee redirect is
# flooded and garbled, which is why the ordering is ENFORCED rather than documented.
# Per-key idempotence is by SHA256 fingerprint, so an already-loaded key never re-prompts.
plan_load_ssh_keys() {
    if [[ "${PLAN_LOG_STARTED}" -eq 1 ]]; then
        _plan_err "plan_load_ssh_keys must be called BEFORE plan_start_log — a passphrase prompt issued after the tee redirect is flooded and garbled" || return 1
    fi
    ...
}

# _plan_fingerprint_present <fingerprint> <ssh-add-l-output> — pure predicate. Kept pure
# (the listing is passed in) so key idempotence is testable with no agent running. The
# space-delimited match is deliberate: a prefix like SHA256:AA must NOT match SHA256:AAA.
_plan_fingerprint_present() {
    local fpr="$1" listing="$2"
    case " ${listing} " in
        *" ${fpr} "*) return 0 ;;
        *) return 1 ;;
    esac
}
```

Two details worth carrying upstream:

- **The ordering is a runtime error, not a comment.** "Call X before Y" in a docstring is a
  suggestion; a check that refuses is a contract.
- **Distinguish "agent up but empty" from "no agent" from "ssh-add missing".** `ssh-add -l`
  returns 0 / 1 / 2 / 127 respectively. Every failure is *reported*; the listing is simply empty
  when unknown, so the caller falls through to a load attempt rather than wrongly skipping a key.

---

## 7. The QA handler (`plan_script_qa`)

A daemon handler that enforces the above at Write/Edit and at `git add` / `git commit`.

### 7.1 The two-file split, and why it matters for CI

```
_plan_script_rules.py   the whole rule engine — patterns, scope logic, git target
                        resolution, the sweep, and a CLI. Imports NOTHING from the daemon.
plan_script_qa.py       a thin Handler wrapper around it.
```

**The reason is CI.** The daemon typically lives in a git-ignored directory and is therefore
absent from a CI checkout, so anything importing it **cannot be gated by CI**. The rules are the
part that has actually had bugs. Splitting them out means:

| Command                       | Interpreter    | Covers                                 |
| ----------------------------- | -------------- | -------------------------------------- |
| `test-plan-script-rules.bash` | bare `python3` | the rule-engine tests — **runs in CI** |
| `test-plan-script-qa.bash`    | daemon venv    | rules + handler                        |

Installing the daemon into CI was considered and rejected: it puts an upstream dependency into
the gate's critical path and pins the gate to a daemon version.

### 7.2 Orchestrator versus helper — a scope rule the gate needs

```python
_ORCHESTRATOR_BASENAMES = frozenset({
    "deploy.bash", "verify.bash", "triage.bash", "acceptance.bash", "provision.bash",
})
_LIBRARY_MARKER = "_planlib.inc.bash"

def is_orchestrator(rel: str, content: str) -> bool:
    """Structural rules apply to ORCHESTRATORS only.

    A plan-local HELPER — leg logic split out to keep shellcheck happy — gets every
    LINE-level rule but is never told to grow a bootstrap, a mode or a gate it should
    not have. Sourcing the library does NOT by itself make a script an orchestrator:
    a helper may source it purely to reuse plan_init's PLAN_REPO_ROOT.
    """
    if os.path.basename(rel) in _ORCHESTRATOR_BASENAMES:
        return True
    return bool(re.search(r"^\s*plan_mode\s+(deploy|gather)\b", content, re.M))
```

Getting this wrong in either direction is costly: too broad and the gate demands a change gate
from a helper that must not have one; too narrow and a real orchestrator escapes every structural
rule.

### 7.3 The rules

Numbered so a deviation can name one. **A deliberate deviation carries
`# STANDARD-EXCEPTION(Rn): reason` on the offending line**, which downgrades that rule to advisory
*and echoes the reason* — so it stays conscious and reviewable rather than looking like an
oversight. Crucially this is **not** a `# shellcheck disable`-style suppression: it is loud.

| #   | Rule                                                                             | Forbidden shape                                                                                 |
| --- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| R1  | Bootstrap: script-relative, filesystem-only, boundary-bounded                    | `git rev-parse --show-toplevel`/`--show-cdup`; a hardcoded absolute path; a fixed-depth `../..` |
| R2  | Keys via `plan_load_ssh_keys`, **before** the log                                | a bare `ssh-add`; keys loaded after `plan_start_log`                                            |
| R3  | Run log via `plan_start_log` only                                                | a raw `exec > >(tee …)`                                                                         |
| R4  | Prompts via `plan_confirm` / `plan_gate_change`                                  | a bare `read` after the log                                                                     |
| R5  | Never `$(… \| tee /dev/stdout)`                                                  | the "live" copy vanishes into the capture                                                       |
| R6  | Delegate to the project runner                                                   | a hand-rolled runner argv with credentials                                                      |
| R7  | Declare mode; use the matching leg runner                                        | `plan_deploy_leg` in gather mode, or vice versa                                                 |
| R8  | Gate on **state change**, not on target name                                     | a gather that gates; a deploy that does not                                                     |
| R9  | No error hiding, no QA suppressions                                              | `2>/dev/null`, `\|\| true`, `# shellcheck disable=`                                             |
| R10 | Structure: header, `WHERE TO RUN`, `-h`, strict arg parse, idempotence statement | —                                                                                               |
| R11 | Reach managed hosts through the runner                                           | raw `ssh user@host`, per-host SSH loops, hypervisor guest-exec                                  |
| R12 | Ship it executable                                                               | the agent `Write` tool creates `0644`; `./script.bash` then fails                               |
| R13 | Reports live in the plan folder, written by the tool                             | an operator shell redirect `> report.txt`                                                       |
| R14 | A state-changing script gets an adversarial review before an operator runs it    | —                                                                                               |
| R15 | A plan script **orchestrates** project code; it never **carries** any            | a `deploy` shipping its own infrastructure definitions                                          |

Two of these deserve expanding, because they are the ones people argue with.

**R12 looks trivial and is the most frequently hit.** An agent writing a file creates it `0644`.
The operator's very first action is `./deploy.bash`, which fails with `Permission denied`. It is
worth a gate purely because it is worth never explaining again.

**R15 is the counterpart to "core never depends on the plan tree", running the other way.** Plan
folders are ephemeral and get archived; if the definition that *builds* a thing lives in one, the
project stops being reproducible the moment that plan completes. A `triage`/`verify` may carry
plan-local definitions when a check genuinely has no home in the main codebase — but a **`deploy`
carrying its own is always wrong**, because whatever it builds is real state, and real state is
core code by definition. Promoting it out of the plan folder is part of *finishing* the plan.

### 7.4 A representative rule implementation

R15, which needs to distinguish "runs project code" from "carries its own":

```python
_RE_PLAN_INVOCATION = re.compile(r"\bplan_run\s+(\S+)")
_GATHER_SCRIPT_PREFIXES = ("triage", "verify", "gather", "check", "report")

def _target_is_core(path: str) -> bool:
    """A target under the project's own source tree is core; one beside the script is not.

    A variable or a command substitution is UNKNOWABLE statically, and unknowable must
    read as core: a gate that guesses 'plan-local' from an expansion it cannot resolve
    would fire on correct code, and a gate that cries wolf gets switched off.
    """
    arg = path.strip().strip("\"'")
    if "$" in arg or "`" in arg:
        return True
    return arg.startswith(PROJECT_SOURCE_PREFIXES)
```

Blocking for a `deploy`; advisory for a gather script. That asymmetry *is* the rule.

---

## 8. The test suite

`test-planlib.bash` is the artefact that makes the library safe to change. Structure worth
copying:

```bash
# Pure helpers are tested DIRECTLY, with no processes, no agent and no infrastructure.
assert_eq "find_repo_root resolves the root from a deep subdir" \
    "${TMPROOT}/a/repo" "${OUT}"

# The boundary bound gets a NEGATIVE CONTROL, because the failure mode is "appears to work".
assert_eq "nested repo with no marker FAILS rather than escaping to the outer repo" "1" "${RC}"
assert_not_contains "the outer repo path is never returned" "${TMPROOT}/b/outer" "${OUT}"

assert_eq "an inner repo WITH a marker resolves to itself, not the outer repo" ...
assert_eq "a worktree .git FILE bounds the walk (not just a .git dir)" "1" "${RC}"

# Delegation is asserted on the built ARGV, so it needs no infrastructure to test.
assert_not_contains "build_argv never re-derives credentials" "--vault-id" "${_PLAN_ARGV[*]}"

# The backstop.
assert_eq "a deploy-mode command is refused before the change gate passes" "1" "${RC}"
assert_contains "the refusal names the gate the script must call" "plan_gate_change" "${OUT}"

# Leg semantics.
assert_eq "a failing gather leg CONTINUES (returns 0)" "0" "${RC}"
assert_eq "a failing gather leg is recorded by name" "bad-leg" "${PLAN_FAILED_LEGS}"
```

Four principles the suite embodies, all of which generalise:

1. **Keep predicates pure so they are testable without the world.** `_plan_fingerprint_present`
   takes the agent listing as an *argument* rather than shelling out, so key idempotence is
   testable with no agent running.

2. **Assert the mechanism, not just the exit code.** "It returned 1" does not distinguish "refused
   correctly" from "crashed for an unrelated reason". Assert the message names the thing.

3. **Every control gets a negative control.** A gate that fires is not necessarily a gate that
   *discriminates*. Perturb **one** thing and require exactly the expected assertion to fail — a
   uniform failure across unrelated assertions proves nothing about any of them.

4. **State what the suite cannot cover.** A TTY cannot be faked from a container, so the suite
   covers the no-TTY paths via `setsid` and the library's header carries a short **manual**
   checklist for the rest:

```
TTY BEHAVIOUR MUST BE CHECKED BY HAND (a tty cannot be faked from a container)
  1. Key not in the agent:  ssh-add -D; ./<plan>/deploy.bash --check
     EXPECT one clean passphrase prompt BEFORE any tee'd output.
  2. Key already loaded:    ssh-add <key>; re-run
     EXPECT "already loaded" and NO second prompt.
  3. Change gate:           ./<plan>/deploy.bash
     EXPECT the prompt AFTER the banner (ordered), a wrong answer to abort
     before the first mutating leg, and -y to skip.
  4. Ctrl-C mid-run: the run log still contains every line up to the interrupt.
```

An unstated limit gets read as total coverage.

---

## 9. Configuration surface

Proposed daemon config, following existing conventions:

```yaml
plan_workflow:
  scripts:
    # Required for the library to resolve anything. No default on purpose.
    root_marker: "ansible.cfg"

    # Optional: the command runner legs delegate to, repo-relative.
    delegate: "shellscripts/ansible-run.bash"

    # Optional: the flag threaded in by --check.
    check_flag: "--check"

    # Optional: env var set to 1 when the console is a TTY, so a colour-suppressing
    # tool still colours the console while the log stays monochrome.
    force_color_var: "ANSIBLE_FORCE_COLOR"

    # Optional: the secret scrubber, repo-relative. Contract: `<scrubber> <file>`
    # rewrites in place, exits 0 on success.
    scrubber: "shellscripts/scrub-secrets.py"

    # Whether run logs are tracked in git. When true the scrubber is REQUIRED and a
    # failed scrub quarantines to `<name>.unscrubbed`.
    track_run_logs: true

  qa:
    plan_script_qa:
      edit_mode: warn          # block | warn | off
      commit_gate_mode: warn
      legacy_script_allowlist: []
```

**`edit_mode: warn` as the rollout default is deliberate.** A gate that starts red against every
existing file is one everybody learns to skip. Ship advisory, let the tree converge, then flip to
`block`.

---

## 10. What is deliberately NOT proposed

- **A plan-script *generator*.** `mkplan.bash` scaffolds the plan; scaffolding the orchestrator
  too would produce files that exist because a tool made them. The skeletons in §5 are short
  enough to copy deliberately.

- **Anything that runs plan scripts automatically.** These are operator-invoked by design. The
  authoring/running split in the originating project is a **policy**, not a capability boundary —
  the agent container is not airgapped and credentials are present in the checkout. Writing it up
  as an isolation guarantee would be false, and false in the direction that invites people to
  rely on isolation nobody is maintaining.

- **Making the gate infer the delegate.** Configure it. A gate that guesses which command is "the
  runner" will be wrong in some project and wrong quietly.

- **Reference-style markdown links, non-bash orchestrators, Windows.** Not covered; not pretended
  to be.

---

## 11. Known limits, stated because an unstated limit reads as coverage

- **Bash 4.2+.** `BASH_SUBSHELL`, `${arr[@]+"${arr[@]}"}` and `mkfifo` semantics are assumed.
  No `bash 3.2` (macOS system bash) support.

- **The scrubber is pattern-based.** A clean scrub means "none of the known shapes are present",
  never "this log is safe". Whatever it cannot reach must be listed in its own header.

- **`plan_run` cannot verify that your delegate is safe.** It only guarantees the plan script did
  not re-derive it. If the delegate leaks credentials, R6 has not helped you.

- **`is_orchestrator` is heuristic.** Basename plus a `plan_mode` declaration. A script named
  something else that declares no mode escapes the structural rules — which is the intended
  trade, but it is a trade.

- **The `BASH_SUBSHELL` guard catches misuse at runtime, not at lint time.** A
  `plan_deploy_leg` buried in a pipeline is only detected when that line executes.

- **Three variants of this library already exist in the wild** with a shared ancestor. Upstreaming
  is what stops that becoming four; it does not retroactively converge the three.

---

## 12. Suggested adoption order

1. **`_planlib.inc.bash` + `test-planlib.bash`**, with `plan_script_qa` off. Immediate value, no
   enforcement, nothing to argue with.
2. **`plan_script_qa` in `warn`**, seeded with a `legacy_script_allowlist` of what exists, so it
   ships green.
3. **Flip to `block`** once the allowlist is empty. Make the allowlist a **ratchet**: a stale
   entry *fails* rather than being a no-op, and growth fails, or it stops being a ratchet and
   becomes a list of names nobody can justify.

The ordering matters for the same reason the gate defaults to `warn`: the goal is a control
people keep, and a control that arrives red is a control that gets switched off.
