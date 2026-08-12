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

# Guard against double-sourcing. `return` at file scope is valid because this block
# only ever runs while being sourced.
if [[ -n "${PLANLIB_SOURCED:-}" ]]; then
    return 0
fi

PLANLIB_VERSION="1.0.0"
PLANLIB_SOURCED=1
export PLANLIB_VERSION

# ── CONFIGURATION SEAM ───────────────────────────────────────────────────────
# Every project-specific fact lives here and nowhere else.

# What file marks the repository root? The upward walk stops at this.
# There is deliberately NO DEFAULT — see plan_init.
PLANLIB_ROOT_MARKER="${PLANLIB_ROOT_MARKER:-}"

# Where plans live, repo-relative. Used for messages and `auto` log placement only;
# the library never enumerates it.
PLANLIB_PLAN_DIR="${PLANLIB_PLAN_DIR:-CLAUDE/Plan}"

# The command runner a leg delegates to, repo-relative. Optional. When set it MUST
# already handle credentials, targeting and cleanup — see plan_run.
PLANLIB_DELEGATE="${PLANLIB_DELEGATE:-}"

# The dry-run flag threaded in by --check.
PLANLIB_CHECK_FLAG="${PLANLIB_CHECK_FLAG:---check}"

# An env var set to 1 when the console is a TTY, so a colour-suppressing tool still
# colours the console while the log stays monochrome. Empty disables the behaviour.
PLANLIB_FORCE_COLOR_VAR="${PLANLIB_FORCE_COLOR_VAR:-}"

# The secret scrubber, repo-relative. Optional but required in practice when run logs
# are tracked. Contract: `<scrubber> <file>` rewrites in place, exits 0 on success.
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
# Reason the /dev/tty open probe failed, so a fatal message can quote it instead of
# leaving the operator guessing.
PLAN_TTY_PROBE_ERR=""
# tee-drain plumbing: the PID of the background log writer, plus a once-guard so the
# finalize handler cannot run twice (EXIT after a signal).
PLAN_TEE_PID=""
PLAN_TRAP_DONE=0
# Space-separated names of gather legs that failed; drives the final exit code.
PLAN_FAILED_LEGS=""
PLAN_CHECK_ARGS=()
PLAN_REMAINING_ARGS=()
# The fully-built command line, as an ARRAY so nothing is word-split and no SC2086
# suppression is needed.
_PLAN_ARGV=()

export PLAN_MODE PLAN_CHECK PLAN_GATE_PASSED

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

# _plan_strip_cr <string> — drop a single TRAILING carriage return. A terminal in raw/mixed
# mode can leave a CR on a reply, which silently breaks an exact token match.
_plan_strip_cr() {
    local s="$1"
    printf '%s' "${s%$'\r'}"
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

# plan_init "${BASH_SOURCE[0]}" — resolve the repo layout from the CALLING SCRIPT's own
# location, never from the cwd. Idempotent. Fails loudly rather than guessing.
plan_init() {
    # NOTE: no apostrophes in a ${var:?word} message. The word is quote-processed, so an
    # apostrophe opens a quoted section and breaks the parse of everything after it.
    local callerSource="${1:?plan_init requires the calling script BASH_SOURCE[0]}"
    local callerDir=""

    if [[ -z "${PLANLIB_ROOT_MARKER}" ]]; then
        _plan_err "PLANLIB_ROOT_MARKER is unset. Set it to the file marking this repository root BEFORE sourcing planlib. There is deliberately no default: a wrong default resolves to some other directory and the script then operates on the wrong repository." || return 1
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

# _plan_agent_listing — echo `ssh-add -l` output, distinguishing "agent up but empty"
# (exit 1) from "cannot reach an agent" (exit 2) from "ssh-add is not installed" (127).
# Every failure is REPORTED, never discarded; the listing is simply empty when unknown, so
# the caller falls through to a load attempt rather than wrongly skipping a key.
_plan_agent_listing() {
    local out="" rc=0
    out="$(ssh-add -l 2>&1)" || rc=$?
    case "${rc}" in
        0)
            printf '%s' "${out}"
            ;;
        1)
            : # agent is running and holds no identities — a normal, non-error state
            ;;
        2)
            printf '[WARN] no ssh-agent reachable (ssh-add exit 2): %s\n' "${out}" >&2
            printf '[WARN] remedy: start an agent for this shell (eval the output of ssh-agent -s), then re-run.\n' >&2
            ;;
        *)
            printf '[WARN] could not query the ssh-agent (ssh-add exit %s): %s\n' "${rc}" "${out}" >&2
            ;;
    esac
    return 0
}

# plan_load_ssh_keys <keyfile>... — load the operator's keys into ssh-agent.
#
# MUST run BEFORE plan_start_log: a passphrase prompt issued after the tee redirect is
# flooded and garbled, which is why the ordering is ENFORCED rather than documented.
# Per-key idempotence is by SHA256 fingerprint, so an already-loaded key never re-prompts.
# No openable terminal plus an unloaded key is fatal in deploy mode and a loud recorded
# warning in gather mode.
#
# This is NOT how infrastructure is reached — the delegate owns that. This primitive exists
# for a plan that needs the OPERATOR's own key for something else (e.g. a git push).
plan_load_ssh_keys() {
    if [[ "${PLAN_LOG_STARTED}" -eq 1 ]]; then
        _plan_err "plan_load_ssh_keys must be called BEFORE plan_start_log — a passphrase prompt issued after the tee redirect is flooded and garbled" || return 1
    fi

    local listing="" key="" fprRaw="" fpr=""
    listing="$(_plan_agent_listing)"

    for key in "$@"; do
        if [[ ! -e "${key}" ]]; then
            if [[ "${PLAN_MODE}" == "gather" ]]; then
                printf '[WARN] ssh key not found: %s (continuing — gather mode)\n' "${key}" >&2
                continue
            fi
            _plan_err "ssh key not found: ${key}" || return 1
        fi
        fpr=""
        if fprRaw="$(ssh-keygen -lf "${key}" 2>&1)"; then
            fpr="$(printf '%s' "${fprRaw}" | awk '{print $2}')"
        else
            printf '[WARN] could not fingerprint %s (%s) — attempting a load rather than skipping it\n' \
                "${key}" "${fprRaw}" >&2
        fi
        if [[ -n "${fpr}" ]] && _plan_fingerprint_present "${fpr}" "${listing}"; then
            printf '==> ssh key already in the agent, skipping: %s\n' "${key}"
            continue
        fi
        if ! _plan_tty_openable; then
            if [[ "${PLAN_MODE}" == "gather" ]]; then
                printf '[WARN] %s may need a passphrase but there is no controlling terminal (%s) — continuing, gather mode. Remedy: run ssh-add %s first.\n' \
                    "${key}" "${PLAN_TTY_PROBE_ERR}" "${key}" >&2
                continue
            fi
            _plan_err "${key} may need a passphrase but there is no controlling terminal (${PLAN_TTY_PROBE_ERR}). Remedy: run 'ssh-add ${key}' in your terminal, then re-run this script." || return 1
        fi
        printf '==> loading ssh key into the agent: %s\n' "${key}"
        if ! ssh-add "${key}" </dev/tty; then
            if [[ "${PLAN_MODE}" == "gather" ]]; then
                printf '[WARN] could not load ssh key: %s (continuing — gather mode)\n' "${key}" >&2
                continue
            fi
            _plan_err "could not load ssh key into the agent: ${key}" || return 1
        fi
        # Refresh so a second path pointing at the same key is recognised as loaded.
        listing="$(_plan_agent_listing)"
    done
    return 0
}

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
    if [[ -t 9 ]] && [[ -n "${PLANLIB_FORCE_COLOR_VAR}" ]]; then
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
#
# The scrubber is separate DELIBERATELY: the thing that WRITES the log must not also be the
# thing that certifies it clean.
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

# plan_list_reports — name the report files the run produced, so the operator knows what to
# read without hunting.
plan_list_reports() {
    if [[ -z "${PLAN_RUN_DIR}" ]] || [[ ! -d "${PLAN_RUN_DIR}" ]]; then
        return 0
    fi
    local f found=0
    for f in "${PLAN_RUN_DIR}"/*report*; do
        if [[ -e "${f}" ]]; then
            if [[ "${found}" -eq 0 ]]; then
                printf '==> reports produced:\n'
                found=1
            fi
            printf '    %s\n' "${f}"
        fi
    done
    return 0
}

# plan_finish — the closing statement of every plan script: list reports, summarise failed
# legs, and terminate with a status that AGREES with the text. It ends the run deliberately,
# so anything written after a plan_finish call is dead code.
plan_finish() {
    plan_list_reports
    if [[ -n "${PLAN_FAILED_LEGS}" ]]; then
        printf '==> FAILED legs: %s\n' "${PLAN_FAILED_LEGS}" >&2
        if [[ -n "${PLAN_RUN_LOG}" ]]; then
            printf '==> run log: %s\n' "${PLAN_RUN_LOG}"
        fi
        exit 1
    fi
    printf '==> all legs OK\n'
    if [[ -n "${PLAN_RUN_LOG}" ]]; then
        printf '==> run log: %s\n' "${PLAN_RUN_LOG}"
    fi
    exit 0
}

# plan_parse_common_flags "$@" — consume the flags every plan script shares and leave the
# rest in PLAN_REMAINING_ARGS. Set PLAN_USAGE first to get a useful --help.
#
#   --check     thread the dry-run flag into every delegated command
#   -y|--yes    consent non-interactively (skips plan_confirm / plan_gate_change prompts)
#   -h|--help   print PLAN_USAGE and stop
plan_parse_common_flags() {
    PLAN_REMAINING_ARGS=()
    local arg
    for arg in "$@"; do
        case "${arg}" in
            --check)
                PLAN_CHECK=1
                PLAN_CHECK_ARGS=("${PLANLIB_CHECK_FLAG}")
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
