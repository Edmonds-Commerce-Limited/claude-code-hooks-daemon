# Claude Code Hooks Daemon - FRESH INSTALLATION Guide

**This document is for FRESH installations only.** Follow the steps below to install the daemon into a project that does not have it yet.

## Prerequisites

Before running the installer, verify:

1. **GIT CLEAN STATE**: `git status` must show clean working directory. Commit/push all changes first.
2. **PYTHON 3.11+**: `python3 --version` must show 3.11 or higher.
3. **CONTEXT WINDOW**: You need at least **100,000 tokens** remaining. If low, ask user to start a fresh session.
4. **WEBFETCH**: If you fetched this via WebFetch, ensure you disabled summarisation. Missing steps cause failure.
5. **SESSION RESTART**: After install completes, user MUST restart their Claude session for hooks to activate.

---

## Quick Install (Recommended)

**Step 0 — Check install state:**

```bash
if [ -d ".claude/hooks-daemon/src" ]; then
  echo "DAEMON ALREADY INSTALLED — use LLM-UPDATE.md to upgrade"
  exit 1
else
  echo "Daemon not installed — proceeding with fresh install"
fi
```

**Only use the UPDATE guide if `.claude/hooks-daemon/src/` exists** (the daemon repo is present). If you see config files like `.claude/hooks-daemon.yaml` or `.claude/settings.json` but no `.claude/hooks-daemon/` directory, that means the project uses the daemon but you're on a fresh clone — **this IS an install scenario**, not an update. The config files are checked into git; the daemon repo is gitignored and needs to be installed.

**Step 1 — Run the installer:**

```bash
# From your project root (must have .git/)

# Download the installer script
curl -sSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/install.sh -o /tmp/hooks-daemon-install.sh

# Inspect it (good security practice)
cat /tmp/hooks-daemon-install.sh

# Run it
bash /tmp/hooks-daemon-install.sh
```

> **Note**: We intentionally avoid `curl | bash` because the daemon itself blocks that
> pattern as a security risk. Practice what we preach.

This will:

1. Validate prerequisites (git required)
2. Clone the daemon repository to `.claude/hooks-daemon/`
3. Delegate to the version-specific Layer 2 installer which:
   - Checks for self-install mode (aborts if detected)
   - Verifies Python 3.11+ and installs uv if needed
   - Creates isolated venv at `.claude/hooks-daemon/untracked/venv/`
   - Deploys hook forwarder scripts to `.claude/hooks/`
   - Generates `.claude/settings.json` for hook registration
   - Creates `.claude/hooks-daemon.env` environment file
   - Generates default `.claude/hooks-daemon.yaml` config
   - Sets up all `.gitignore` files
   - Deploys slash commands to `.claude/commands/`
   - Starts the daemon and verifies it is running

### Environment Variables

| Variable        | Default | Description                              |
| --------------- | ------- | ---------------------------------------- |
| `DAEMON_BRANCH` | `main`  | Git branch or tag to install             |
| `FORCE`         | `false` | Set to `true` to reinstall over existing |

```bash
# Install specific version
curl -sSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/install.sh -o /tmp/hooks-daemon-install.sh
DAEMON_BRANCH=v2.5.0 bash /tmp/hooks-daemon-install.sh

# Force reinstall
FORCE=true bash /tmp/hooks-daemon-install.sh
```

---

## Manual Install (6 Steps)

If you prefer manual control over each step:

> **Never hand-build the venv.** From v3.7.0 the venv is **fingerprint-keyed** —
> `.claude/hooks-daemon/untracked/venv-{slug}-py{MM}-{fingerprint}/`, where
> `{fingerprint} = md5(sys.version | sys.base_prefix | platform.machine())[:8]`.
> A hand-made `untracked/venv/` is the retired pre-v3.7.0 layout and
> `resolve_venv.sh` refuses it, so every wrapper call then exits 5. Let the
> installer create it, and find it afterwards with
> `.claude/hooks-daemon/bin/hooks-daemon list-venvs`.

### 1. Verify Prerequisites

```bash
# Must show clean - if not, commit everything first
git status --short

# Must be 3.11+
python3 --version

# Optional: Commit existing .claude/ config as safety checkpoint
git add .claude/ && git commit -m "Save hooks before daemon install" && git push || true
```

### 2. Clone the Daemon

```bash
mkdir -p .claude && cd .claude

# Clone and checkout latest stable release tag
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git hooks-daemon
cd hooks-daemon
git fetch --tags
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "main")
git checkout "$LATEST_TAG"
echo "Using version: $LATEST_TAG"

cd ../..
```

### 3. Run Installer

The Layer-2 installer does everything: builds the fingerprint-keyed venv,
installs the package editable, writes `.claude/hooks/`, `settings.json` and
`hooks-daemon.yaml`, and starts the daemon.

```bash
# Both arguments are absolute paths: PROJECT_ROOT then DAEMON_DIR
bash .claude/hooks-daemon/scripts/install_version.sh \
  "$PWD" "$PWD/.claude/hooks-daemon"
```

Verify it came up:

```bash
.claude/hooks-daemon/bin/hooks-daemon status
# Expected: Status: RUNNING
```

**Files created:**

- `.claude/init.sh` - Daemon lifecycle functions
- `.claude/hooks/*` - Forwarder scripts
- `.claude/settings.json` - Hook registration
- `.claude/hooks-daemon.yaml` - Handler config (with container auto-detection)

**Container Auto-Detection**:

- During config generation, the installer detects container environments (Docker, Podman, YOLO mode)
- If container detected, automatically enables `enforce_single_daemon_process: true`
- In containers: Ensures only ONE daemon process runs system-wide (kills duplicates)
- Outside containers: Only cleans stale PID files (safe for multi-project setups)
- No manual configuration needed - works automatically based on environment

**Note**: The installer automatically creates `.claude/.gitignore` with the correct entries. If auto-creation fails, it will display manual instructions.

### 4. Commit & Restart

```bash
# Verify .gitignore was auto-created
ls -la .claude/.gitignore

# If missing, copy from template:
# cp .claude/hooks-daemon/.claude/.gitignore .claude/.gitignore

# Commit (with .gitignore in place to exclude generated files)
git add .claude/
git commit -m "Install Claude Code Hooks Daemon" && git push
```

**CRITICAL**:

1. Verify `.claude/.gitignore` exists before `git add` or you'll commit hooks-daemon/
2. Tell user to **restart Claude session** (exit and re-enter). Hooks won't activate until Claude reloads `.claude/settings.json`.
3. Do NOT proceed to step 5 until session restarts.

### 5. Verify Hooks Active (After Restart)

```bash
# Check daemon auto-started (lazy startup on first hook call)
.claude/hooks-daemon/bin/hooks-daemon status

# Test destructive git is blocked
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}' \
  | .claude/hooks/pre-tool-use
# Expected: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}

# Test sed is blocked
echo '{"tool_name": "Bash", "tool_input": {"command": "sed -i s/foo/bar/ file.txt"}}' \
  | .claude/hooks/pre-tool-use
# Expected: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}

# Test normal commands pass through
echo '{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}' \
  | .claude/hooks/pre-tool-use
# Expected: {} (empty = allow)
```

**If all tests pass**: Hooks active.

**If tests fail**: Check troubleshooting section below.

### Installation Success Criteria

A successful installation meets ALL of these conditions:

1. **Daemon running**: `.claude/hooks-daemon/bin/hooks-daemon status` shows `RUNNING`
2. **Hooks deployed**: `.claude/hooks/pre-tool-use` and other hook scripts exist and are executable
3. **Blocking works**: `echo '{"tool_name":"Bash","tool_input":{"command":"git reset --hard"}}' | .claude/hooks/pre-tool-use` returns a `deny` decision
4. **Safe commands pass**: `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | .claude/hooks/pre-tool-use` returns `{}` (allow)
5. **No DEGRADED MODE**: `.claude/hooks-daemon/bin/hooks-daemon logs` shows no "DEGRADED MODE" warnings
6. **Git clean**: `.claude/hooks-daemon/` is excluded via `.gitignore`, not tracked by git

If any of these fail, see Troubleshooting section below.

---

### 6. Enable and Configure Handlers (CRITICAL)

**The daemon ships with 60+ handlers but most start DISABLED.** An unconfigured daemon provides minimal value. You MUST review available handlers and enable everything relevant to the project.

**Step 6.1: Generate the full default config with ALL handlers visible:**

```bash
.claude/hooks-daemon/bin/hooks-daemon init-config --stdout > /tmp/full-config.yaml
cat /tmp/full-config.yaml
```

`--stdout` prints the template for review and writes nothing, so it is safe to
run on an existing install — your current `.claude/hooks-daemon.yaml` is not
touched and no `--force` is needed.

**Step 6.2: Review every handler and enable all that are relevant.**

Use these guidelines — when in doubt, **enable it**. Handlers can always be disabled later, but missing protection cannot be retroactively applied to code already written.

| Category                          | Handlers                                                                                                                                                                                                                | Recommendation                                                              |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| **Safety** (priority 10-22)       | `destructive_git`, `sed_blocker`, `absolute_path`, `error_hiding_blocker`, `security_antipattern`, `curl_pipe_shell`, `pipe_blocker`, `dangerous_permissions`, `lock_file_edit_blocker`, `pip_break_system`, `sudo_pip` | **Enable ALL** — these prevent data loss and security issues                |
| **Code Quality** (priority 25-35) | `qa_suppression`, `tdd_enforcement`, `lint_on_edit`                                                                                                                                                                     | **Enable ALL** — prevents suppressed linting, enforces TDD, validates edits |
| **Workflow** (priority 36-55)     | `npm_command`, `global_npm_advisor`, `gh_issue_comments`, `daemon_restart_verifier`                                                                                                                                     | **Enable ALL** — enforces best practices                                    |
| **Advisory** (priority 55-60)     | `british_english`, `web_search_year`                                                                                                                                                                                    | Enable based on project preferences                                         |
| **Session/Lifecycle**             | `git_context_injector`, `bash_error_detector`, `version_check`, `optimal_config_checker`                                                                                                                                | **Enable ALL** — provides valuable context at zero cost                     |
| **Planning**                      | `plan_workflow`, `validate_plan_number`, `plan_time_estimates`, `plan_completion_advisor`, `markdown_organization`                                                                                                      | Enable if using the planning workflow (see Planning section below)          |

**Step 6.3: Edit `.claude/hooks-daemon.yaml` and enable handlers:**

```yaml
daemon:
  idle_timeout_seconds: 600
  log_level: INFO

handlers:
  pre_tool_use:
    # Safety — enable ALL of these
    destructive_git: {enabled: true, priority: 10}
    sed_blocker: {enabled: true, priority: 11}
    absolute_path: {enabled: true, priority: 12}
    error_hiding_blocker: {enabled: true, priority: 13}
    security_antipattern: {enabled: true, priority: 14}
    curl_pipe_shell: {enabled: true, priority: 16}
    pipe_blocker: {enabled: true, priority: 17}
    dangerous_permissions: {enabled: true, priority: 18}
    lock_file_edit_blocker: {enabled: true, priority: 20}
    pip_break_system: {enabled: true, priority: 21}
    sudo_pip: {enabled: true, priority: 22}
    daemon_restart_verifier: {enabled: true, priority: 23}

    # Code quality — enable for better code
    qa_suppression: {enabled: true, priority: 30}
    tdd_enforcement: {enabled: true, priority: 35}

    # Workflow — enable for best practices
    gh_issue_comments: {enabled: true, priority: 40}
    global_npm_advisor: {enabled: true, priority: 42}
    npm_command: {enabled: true, priority: 49}

    # Advisory
    web_search_year: {enabled: true, priority: 55}
    british_english: {enabled: false, priority: 60}  # Enable for UK English projects

  post_tool_use:
    bash_error_detector: {enabled: true, priority: 10}
    lint_on_edit: {enabled: true, priority: 25}

  session_start:
    git_context_injector: {enabled: true, priority: 10}
    optimal_config_checker: {enabled: true, priority: 52}
    version_check: {enabled: true, priority: 56}

  user_prompt_submit:
    git_context_injector: {enabled: true, priority: 10}
```

**Step 6.4: Restart daemon to load new config:**

```bash
.claude/hooks-daemon/bin/hooks-daemon restart
```

**Step 6.5: Verify handlers loaded:**

```bash
.claude/hooks-daemon/bin/hooks-daemon status
```

**Note**: Settings.json changes require Claude session restart, config.yaml changes only need daemon restart.

**For full handler options reference** (blocking modes, language filters, etc.): see `docs/guides/HANDLER_REFERENCE.md` in the daemon directory.

---

## Post-Installation: Handler Status Report (MANDATORY)

**You MUST run this after installation to verify your handler configuration.** Review the output and check that the handlers you need are actually enabled.

```bash
.claude/hooks-daemon/bin/hooks-daemon handlers
```

This displays:

- **All available handlers** organized by event type
- **Enabled/Disabled status** — review this carefully
- **Priority and terminal settings**
- **Summary statistics** — if the enabled count is low, go back to Step 6 and enable more handlers

**Check your enabled count.** A well-configured installation typically has **30+ handlers enabled**. If you see fewer than 15 enabled, you are likely missing valuable protection and workflow enforcement. Return to Step 6 and review the handler categories.

**Save for reference:**

```bash
.claude/hooks-daemon/bin/hooks-daemon handlers > /tmp/handler-status.txt
cat /tmp/handler-status.txt
```

---

## Post-Installation: Update Project CLAUDE.md

Add a `### Hooks Daemon` section to the **project's root `CLAUDE.md`** so future agents working in this project know how to manage the daemon.

### Check if Section Exists

```bash
grep -n "### Hooks Daemon" CLAUDE.md 2>/dev/null || echo "MISSING - add section"
```

### Add or Update the Section

If missing (or outdated), append the following to the **bottom** of the project's root `CLAUDE.md`:

```markdown
### Hooks Daemon

This project uses [claude-code-hooks-daemon](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon) for automated safety and workflow enforcement.

After editing `.claude/hooks-daemon.yaml` — restart the daemon using the `hooks-daemon` skill:

- **Restart**: use the `hooks-daemon` skill with args `restart`
- **Health check**: use the `hooks-daemon` skill with args `health`

> **Important**: `/hooks-daemon` is a **skill** (slash command), not a bash command.
> Invoke it using the Skill tool, e.g. `Skill(skill="hooks-daemon", args="restart")`.
> Do NOT attempt to run `/hooks-daemon` as a bash command — it will fail.

**Key files**:
- `.claude/hooks-daemon.yaml` — handler configuration (enable/disable handlers)
- `.claude/project-handlers/` — project-specific custom handlers (if any)

**Documentation**: `.claude/hooks-daemon/CLAUDE/LLM-INSTALL.md`
```

### Also: Check Config Header

Verify `.claude/hooks-daemon.yaml` has the restart-reminder header (new installs add it automatically; older installs may be missing it):

```bash
grep -q "AFTER EDITING THIS FILE" .claude/hooks-daemon.yaml && echo "OK" || echo "Header missing"
```

If missing, prepend this comment block to the top of `.claude/hooks-daemon.yaml`:

```yaml
# Claude Code Hooks Daemon - Handler Configuration
#
# AFTER EDITING THIS FILE: restart the daemon for changes to take effect.
#   User: type /hooks-daemon restart
#   Claude: use Skill tool with skill="hooks-daemon" args="restart"
#
# Verify it is running:
#   User: type /hooks-daemon health
#   Claude: use Skill tool with skill="hooks-daemon" args="health"
#
# Full handler reference: .claude/hooks-daemon/CLAUDE/HANDLER_DEVELOPMENT.md

```

### Rules

- Keep the section terse — 10 lines maximum
- Do not duplicate if a `### Hooks Daemon` section already exists; update it in place instead
- This section is for **project agents**, not end users — focus on operational commands

---

## Post-Installation: Planning Workflow Setup

The daemon includes a structured planning workflow with numbered plan directories and enforcement handlers. **If your project uses any form of planning or task tracking, you should adopt this system** — it integrates directly with the daemon's enforcement handlers to keep plans consistent and actionable.

### Quick Assessment

Ask yourself (or the user): Does this project benefit from structured planning for non-trivial work?

- **Yes** → Follow the setup steps below. The enforcement handlers prevent common planning mistakes (bad numbering, time estimates, incomplete closures).
- **No / Not sure** → Skip for now. The handlers remain disabled and can be enabled later.

### Setup Steps

**1. Create planning directories and copy workflow documentation:**

```bash
mkdir -p CLAUDE/Plan
cp .claude/hooks-daemon/CLAUDE/PlanWorkflow.md CLAUDE/PlanWorkflow.md

if [ ! -f "CLAUDE/Plan/README.md" ]; then
  echo "# Plans Index

## Active Plans
- None

## Completed Plans
- None
" > CLAUDE/Plan/README.md
fi
```

**2. Enable ALL planning enforcement handlers** in `.claude/hooks-daemon.yaml`:

```yaml
handlers:
  pre_tool_use:
    plan_workflow: {enabled: true, priority: 46}
    validate_plan_number: {enabled: true, priority: 41}
    plan_time_estimates: {enabled: true, priority: 45}
    plan_completion_advisor: {enabled: true, priority: 48}
    plan_number_helper: {enabled: true, priority: 33}
    markdown_organization: {enabled: true, priority: 50}
```

**What each handler does:**

| Handler                   | What It Enforces                                                |
| ------------------------- | --------------------------------------------------------------- |
| `plan_workflow`           | Guides agents through proper planning steps when creating plans |
| `validate_plan_number`    | Ensures plan folders use sequential numbering (001, 002, ...)   |
| `plan_time_estimates`     | Blocks time estimates in plan documents (they are always wrong) |
| `plan_completion_advisor` | Reminds to follow the completion checklist when closing plans   |
| `plan_number_helper`      | Provides the correct next plan number when agents search for it |
| `markdown_organization`   | Enforces markdown file placement rules in CLAUDE/ directory     |

**3. Restart daemon:**

```bash
.claude/hooks-daemon/bin/hooks-daemon restart
```

**4. Verify planning handlers loaded:**

```bash
.claude/hooks-daemon/bin/hooks-daemon status
```

---

## Custom Handler Migration

If you had custom hooks before install (backed up to `.claude/hooks.bak.TIMESTAMP/`):

**1. Find backup:**

```bash
ls -d .claude/hooks.bak.* 2>/dev/null | tail -1
```

**2. Create handler file:**

```bash
mkdir -p .claude/hooks/handlers/pre_tool_use
# Create .claude/hooks/handlers/pre_tool_use/my_handler.py
```

**3. Handler template:**

```python
"""MyHandler - brief description."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks-daemon/src"))

from claude_code_hooks_daemon.core import Handler, HookResult

class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(name="my-handler", priority=50, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        command = hook_input.get("tool_input", {}).get("command", "")
        return "npm" in command

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision="deny", reason="Use project script instead")
```

**4. Register in config:**

```yaml
handlers:
  pre_tool_use:
    my_handler: {enabled: true, priority: 50}
```

**5. Restart:**

```bash
.claude/hooks-daemon/bin/hooks-daemon restart
```

---

## Troubleshooting Common Issues

**For comprehensive troubleshooting, see [BUG_REPORTING.md](../BUG_REPORTING.md)**

### Quick Diagnostics

**Generate full debug report:**

```bash
.claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
```

### Common Quick Fixes

**Daemon won't start:**

```bash
# Check Python version (must be 3.11+)
python3 --version

# Verify installation
.claude/hooks-daemon/bin/hooks-daemon health

# Check logs
.claude/hooks-daemon/bin/hooks-daemon logs
```

**Handlers not blocking:**

```bash
# Test hook manually
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}' | .claude/hooks/pre-tool-use

# Check handler config
grep -A 1 "destructive_git:" .claude/hooks-daemon.yaml
```

**Hooks not working after install:**

1. **Restart Claude session** (required for settings.json changes)
2. Run debug script to see what's wrong
3. Check [BUG_REPORTING.md](../BUG_REPORTING.md)

**Layer 2 installer not found (legacy fallback):**
If you see "Layer 2 installer not found" during install, you are installing an older version that predates the modular architecture. The legacy fallback (uv sync + install.py) will handle the installation. This is expected for tags before the two-layer architecture was introduced.

### Rollback to Previous Hooks

**Option 1 - Git restore (if you committed before install):**

```bash
.claude/hooks-daemon/bin/hooks-daemon stop 2>/dev/null || true
git restore .claude/
rm -rf .claude/hooks-daemon/
```

**Option 2 - Backup directory (if no git commit):**

```bash
BACKUP_DIR=$(ls -d .claude/hooks.bak.* 2>/dev/null | tail -1)
if [ -z "$BACKUP_DIR" ]; then
    echo "No backup - rollback impossible without git commit"
    exit 1
fi

.claude/hooks-daemon/bin/hooks-daemon stop 2>/dev/null || true
rm -rf .claude/hooks
mv "$BACKUP_DIR" .claude/hooks
```

---

## CLI Reference

```bash
.claude/hooks-daemon/bin/hooks-daemon start
.claude/hooks-daemon/bin/hooks-daemon stop
.claude/hooks-daemon/bin/hooks-daemon status
.claude/hooks-daemon/bin/hooks-daemon restart
.claude/hooks-daemon/bin/hooks-daemon logs
```

---

## Handler Priority Ranges

- **5**: Test/debug handlers
- **10-20**: Safety (destructive git, sed blocker)
- **25-35**: Code quality (ESLint, TDD)
- **36-55**: Workflow (planning, npm)
- **56-60**: Advisory (British English, formatting)

Lower priority = runs first. Terminal handlers stop dispatch chain.

---

## Directory Structure After Install

```
project/
├── .claude/
│   ├── .gitignore              # AUTO-CREATED by installer
│   ├── init.sh                 # COMMIT - Daemon lifecycle
│   ├── hooks-daemon.yaml       # COMMIT - Handler config
│   ├── hooks-daemon.env        # COMMIT - Environment variables
│   ├── settings.json           # COMMIT - Hook registration
│   ├── hooks/                  # COMMIT - Forwarder scripts
│   │   ├── pre-tool-use
│   │   ├── post-tool-use
│   │   └── handlers/           # COMMIT - Custom handlers
│   ├── commands/               # COMMIT - Slash commands
│   └── hooks-daemon/           # EXCLUDED via .gitignore
│       ├── src/                # Daemon source code
│       ├── scripts/
│       │   ├── install/        # Shared modular library (14 modules)
│       │   ├── install_version.sh  # Layer 2 install orchestrator
│       │   └── upgrade_version.sh  # Layer 2 upgrade orchestrator
│       └── untracked/
│           └── venv/           # Isolated Python environment
```

**Git Integration:**

- Installer automatically creates `.claude/.gitignore` with daemon exclusion entries
- Root `.gitignore` also updated automatically with `.claude/hooks-daemon/` entry
- If auto-creation fails, manual instructions are displayed

### Which Files Under `.claude/` Are Yours?

**Most of `.claude/` is yours. A short, fixed list is not.** The daemon owns the
files below: it rewrites them on every install and upgrade, so a local edit is
discarded. They are the daemon's, not your project's — do not edit them, and do
not treat their contents as your code.

`.claude/hooks-daemon/` is the obvious one and needs no thought: the installer
git-ignores it, and ruff, black and most modern tooling respect `.gitignore`, so
it is already outside your quality gates without you doing anything.

**The rest of the list is not git-ignored, and that is deliberate** — these
files only work if they are committed, so your teammates receive them. The same
fact puts daemon-owned source inside your linters' default scope.

| Deployed path                              | What it is                                    | Why it cannot live in `.claude/hooks-daemon/`               |
| ------------------------------------------ | --------------------------------------------- | ----------------------------------------------------------- |
| `.claude/init.sh`                          | Daemon lifecycle / socket resolution          | Sourced by every hook forwarder; must sit beside them       |
| `.claude/hooks/*`                          | Hook forwarder scripts                        | Claude Code executes them by the path in `settings.json`    |
| `.claude/skills/hooks-daemon/scripts/*.sh` | Skill helper scripts                          | Claude Code only discovers skills under `.claude/skills/`   |
| `CLAUDE/Plan/mkplan.bash`                  | Plan scaffolder (plan workflow only)          | Runs inside your plan directory and is documented that way  |
| `.claude/ccy/claude-supervise.py`          | Standalone PTY supervisor (ccy projects only) | `exec`'d by the ccy launcher; committed so teammates get it |

The manifest above is generated from
`src/claude_code_hooks_daemon/install/client_owned_assets.py`, which the daemon's
own test suite keeps in step with the code that performs each deploy — so this
table cannot silently go stale.

#### Excluding Them From Your Quality Gates

Every file above is checked upstream against its language's **default** rule set
(`ruff check --isolated` for Python, `shellcheck -x` for shell) and ships clean.
If your project selects **stricter** rules than the defaults, they may report
findings you cannot act on: you cannot fix them (the next upgrade overwrites the
file) and you cannot suppress them inline (the daemon's own `qa_suppression`
handler denies an agent writing a suppression directive). Exclude them instead.

Ruff:

```toml
# ruff.toml / pyproject.toml — daemon-owned, refreshed on upgrade; do not lint
[lint.per-file-ignores]
".claude/ccy/claude-supervise.py" = ["BLE001", "DTZ005", "DTZ006"]
```

Or, to exclude the daemon-owned files wholesale rather than rule-by-rule:

```toml
[tool.ruff]
extend-exclude = [".claude/ccy/claude-supervise.py", ".claude/init.sh", ".claude/hooks"]
```

Shell (`.shellcheckrc`), if you check `.claude/hooks/*` without `-x`:

```
# Follow the `source .claude/init.sh` the forwarders perform
source-path=SCRIPTDIR
```

**Report anything the defaults catch.** A daemon-owned file that is dirty under
default rules is an upstream bug — file it rather than excluding around it.

---

## Feedback & Issue Reporting

**IMPORTANT**: During the installation process, keep detailed notes of everything that happens. Create a feedback file that the user can optionally share with the project maintainers to improve the install experience.

### Create Feedback File

After installation completes (whether successful or not), create a detailed feedback file at the project root:

```bash
cat > install-feedback-$(date +%Y%m%d).md << 'EOF'
# Installation Feedback Report

## Environment
- **Date**: [today's date]
- **Target Version**: [version installed]
- **OS**: [operating system and version, e.g. uname -a output]
- **Python Version**: [python3 --version output]
- **Default Python Path**: [which python3 output]
- **Project Path**: [absolute path to project root]
- **Project Path Length**: [character count]

## Installation Method
- [ ] Automated (install.sh via curl)
- [ ] Manual (step-by-step)

## Results
- **Overall**: SUCCESS / PARTIAL / FAILED
- **Duration**: [approximate time taken]
- **Daemon Status**: RUNNING / FAILED / NOT STARTED

## Step-by-Step Log
[Document each step: what command was run, what output was received, any errors or warnings]

1. **Pre-flight checks**: ...
2. **Prerequisites (git, python, uv)**: ...
3. **Repository clone**: ...
4. **Venv creation**: ...
5. **Config generation**: ...
6. **Hook deployment**: ...
7. **Daemon start**: ...
8. **Verification**: ...
9. **Session restart**: ...

## Issues Encountered
[List any problems, workarounds, or unexpected behavior]

1. **Issue**: [description]
   **Severity**: Critical / Major / Minor / Cosmetic
   **Workaround**: [what you did to get past it]
   **Suggestion**: [how it could be improved]

## Documentation Gaps
[Note any missing, unclear, or incorrect documentation in LLM-INSTALL.md]

1. [description of gap or inconsistency]

## Suggestions
[Any improvements to the installation process]

1. [suggestion]

## Warnings & Anomalies
[Any warnings logged, unexpected behavior, or things that seemed wrong but didn't break anything]
EOF
```

### What to Document During Installation

Actively note throughout the process:

- **Every command** you run and its output (especially errors/warnings)
- **Every decision point** where you had to choose between options
- **Documentation inconsistencies** where docs said one thing but reality was different
- **Missing prerequisites** that weren't mentioned in docs
- **Confusing error messages** that didn't help diagnose the issue
- **Workarounds** applied that shouldn't be necessary
- **Time spent** on each step (helps identify bottlenecks)
- **Path/permission issues** especially on different OS configurations
- **Python version issues** (system python too old, alternative interpreters found)

### Sharing Feedback

The feedback file can be shared with project maintainers to improve the install process:

1. Open an issue at the project's GitHub repository
2. Attach or paste the feedback file content
3. Maintainers use this real-world data to fix installation issues

**Every piece of feedback makes the next installation smoother for everyone.**

---

## Bug Reports

Include in issue:

```bash
# Full diagnostic report (version, paths, config, daemon state)
.claude/hooks-daemon/bin/hooks-daemon bug-report

# Python
python3 --version

# OS
uname -a

# Logs
.claude/hooks-daemon/bin/hooks-daemon logs > daemon-logs.txt

# Config (sanitize sensitive data)
cat .claude/hooks-daemon.yaml
```

**Submit:** https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/new

---

**Installation Date:** `date +%Y-%m-%d`
