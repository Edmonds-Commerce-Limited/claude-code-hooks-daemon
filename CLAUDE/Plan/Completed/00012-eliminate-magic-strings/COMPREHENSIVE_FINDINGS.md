# Comprehensive Magic Strings/Numbers Analysis

**Generated**: 2026-01-29
**Source**: Deep codebase analysis by Explore subagent

This document contains the complete findings of what Plan 00012 originally MISSED.

## Executive Summary

**Original Plan Completeness**: 60%
- ✅ Handler naming (HandlerID) - GOOD
- ✅ Event naming (EventID) - GOOD
- ✅ Priority constants - GOOD
- ✅ Timeout constants - GOOD
- ✅ Path constants - GOOD
- ❌ Tags system (40+ tags, 67 files) - **COMPLETELY MISSED**
- ❌ Tool names (6+ tools, 31 files) - **COMPLETELY MISSED**
- ❌ Config keys (enabled, priority, options, etc.) - **COMPLETELY MISSED**
- ❌ Protocol field names (JSON contract) - **COMPLETELY MISSED**
- ❌ Validation limits - **PARTIALLY MISSED**
- ❌ Decision enum enforcement - **MISSED**

## 1. TAGS SYSTEM - CRITICAL OMISSION

### Impact
- **67 handler files** with hardcoded tag strings
- Config filtering with `enable_tags`/`disable_tags`
- Zero constants, zero type safety

### Found Tag Values (ALL Magic Strings)

**Language tags**: `"python"`, `"typescript"`, `"javascript"`, `"php"`, `"go"`, `"bash"`

**Category tags**:
- Safety: `"safety"`, `"blocking"`, `"terminal"`, `"non-terminal"`
- Workflow: `"workflow"`, `"advisory"`, `"validation"`, `"automation"`
- QA: `"qa-enforcement"`, `"qa-suppression-prevention"`, `"tdd"`
- Domain: `"git"`, `"file-ops"`, `"content-quality"`, `"npm"`, `"nodejs"`, `"github"`, `"markdown"`
- System: `"status"`, `"display"`, `"health"`, `"logging"`, `"cleanup"`
- Project: `"ec-specific"`, `"ec-preference"`, `"project-specific"`
- Other: `"planning"`, `"environment"`, `"yolo-mode"`, `"state-management"`, `"context-injection"`

### Where Tags Are Used
1. Handler definitions: `tags=["python", "qa-enforcement"]`
2. Config filtering: `enable_tags: [python, typescript]`
3. Registry filtering: `handlers/registry.py` lines 279-293

### Required Constants Module

```python
# constants/tags.py
from typing import Literal

class HandlerTag:
    """Canonical handler tag values - single source of truth."""

    # Language tags
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    PHP = "php"
    GO = "go"
    BASH = "bash"

    # Category tags
    SAFETY = "safety"
    BLOCKING = "blocking"
    TERMINAL = "terminal"
    NON_TERMINAL = "non-terminal"

    WORKFLOW = "workflow"
    ADVISORY = "advisory"
    VALIDATION = "validation"
    AUTOMATION = "automation"

    QA_ENFORCEMENT = "qa-enforcement"
    QA_SUPPRESSION_PREVENTION = "qa-suppression-prevention"
    TDD = "tdd"

    GIT = "git"
    FILE_OPS = "file-ops"
    CONTENT_QUALITY = "content-quality"

    STATUS = "status"
    DISPLAY = "display"
    HEALTH = "health"
    LOGGING = "logging"
    CLEANUP = "cleanup"

    EC_SPECIFIC = "ec-specific"
    EC_PREFERENCE = "ec-preference"
    PROJECT_SPECIFIC = "project-specific"

    PLANNING = "planning"
    MARKDOWN = "markdown"
    NPM = "npm"
    NODEJS = "nodejs"
    GITHUB = "github"

    ENVIRONMENT = "environment"
    YOLO_MODE = "yolo-mode"
    STATE_MANAGEMENT = "state-management"
    CONTEXT_INJECTION = "context-injection"

TagLiteral = Literal[
    "python", "typescript", "javascript", "php", "go", "bash",
    "safety", "blocking", "terminal", "non-terminal",
    "workflow", "advisory", "validation", "automation",
    "qa-enforcement", "qa-suppression-prevention", "tdd",
    "git", "file-ops", "content-quality",
    "status", "display", "health", "logging", "cleanup",
    "ec-specific", "ec-preference", "project-specific",
    "planning", "markdown", "npm", "nodejs", "github",
    "environment", "yolo-mode", "state-management", "context-injection",
]
```

## 2. TOOL NAMES - CRITICAL OMISSION

### Impact
- **31 handler files** with hardcoded tool names
- `tool_name == "Bash"`, `tool_name == "Write"`, etc.

### Found Occurrences
- `tool_name == "Bash"` (8 occurrences)
- `tool_name == "Write"` (9 occurrences)
- `tool_name == "Edit"` (12 occurrences)
- `tool_name in ["Write", "Edit"]` (10 occurrences)

### Required Constants Module

```python
# constants/tools.py
from typing import Literal

class ToolName:
    """Claude Code tool names - single source of truth."""

    BASH = "Bash"
    WRITE = "Write"
    EDIT = "Edit"
    READ = "Read"
    GLOB = "Glob"
    GREP = "Grep"
    WEB_SEARCH = "WebSearch"
    WEB_FETCH = "WebFetch"
    SKILL = "Skill"
    TASK = "Task"
    TASK_CREATE = "TaskCreate"
    TASK_UPDATE = "TaskUpdate"

ToolNameLiteral = Literal[
    "Bash", "Write", "Edit", "Read", "Glob", "Grep",
    "WebSearch", "WebFetch", "Skill", "Task",
    "TaskCreate", "TaskUpdate",
]
```

## 3. CONFIG KEYS - CRITICAL OMISSION

### Impact
- Config key strings hardcoded throughout config system
- No single source of truth for config field names

### Found Hardcoded Keys

**Handler config**: `"enabled"`, `"priority"`, `"options"`, `"enable_tags"`, `"disable_tags"`
**Daemon config**: `"idle_timeout_seconds"`, `"log_level"`, `"socket_path"`, `"pid_file_path"`, etc.

### Required Constants Module

```python
# constants/config.py
class ConfigKey:
    """Config file key names - single source of truth."""

    # Top-level keys
    VERSION = "version"
    DAEMON = "daemon"
    HANDLERS = "handlers"
    PLUGINS = "plugins"

    # Handler config keys
    ENABLED = "enabled"
    PRIORITY = "priority"
    OPTIONS = "options"
    ENABLE_TAGS = "enable_tags"
    DISABLE_TAGS = "disable_tags"

    # Daemon config keys
    IDLE_TIMEOUT_SECONDS = "idle_timeout_seconds"
    LOG_LEVEL = "log_level"
    SOCKET_PATH = "socket_path"
    PID_FILE_PATH = "pid_file_path"
    LOG_BUFFER_SIZE = "log_buffer_size"
    REQUEST_TIMEOUT_SECONDS = "request_timeout_seconds"
    SELF_INSTALL_MODE = "self_install_mode"
    ENABLE_HELLO_WORLD_HANDLERS = "enable_hello_world_handlers"
    INPUT_VALIDATION = "input_validation"
```

## 4. PROTOCOL FIELD NAMES - CRITICAL OMISSION

### Impact
- JSON input/output field names hardcoded
- Part of contract with Claude Code CLI

### Found Field Names

**Input fields**: `"toolName"`, `"toolInput"`, `"sessionId"`, `"transcriptPath"`, `"message"`, `"prompt"`
**Output fields**: `"hookSpecificOutput"`, `"hookEventName"`, `"permissionDecision"`, `"permissionDecisionReason"`, `"additionalContext"`, `"guidance"`, `"decision"`, `"reason"`

### Required Constants Module

```python
# constants/protocol.py
class HookInputField:
    """Claude Code hook input field names (camelCase)."""

    TOOL_NAME = "toolName"
    TOOL_INPUT = "toolInput"
    SESSION_ID = "sessionId"
    TRANSCRIPT_PATH = "transcriptPath"
    MESSAGE = "message"
    PROMPT = "prompt"

class HookOutputField:
    """Claude Code hook output field names (camelCase)."""

    HOOK_SPECIFIC_OUTPUT = "hookSpecificOutput"
    HOOK_EVENT_NAME = "hookEventName"
    PERMISSION_DECISION = "permissionDecision"
    PERMISSION_DECISION_REASON = "permissionDecisionReason"
    ADDITIONAL_CONTEXT = "additionalContext"
    GUIDANCE = "guidance"
    DECISION = "decision"
    REASON = "reason"
```

## 5. VALIDATION LIMITS - PARTIAL OMISSION

### Impact
- Min/max validation thresholds are magic numbers

### Found Limits

- Buffer size: `ge=100, le=100000` (default=1000)
- Request timeout: `ge=1, le=300`
- Idle timeout: `ge=1`
- Hash truncation: `[:8]`
- Name truncation: `[:20]`

### Required Constants Module

```python
# constants/validation.py
class ValidationLimit:
    """Validation limits and thresholds."""

    LOG_BUFFER_MIN = 100
    LOG_BUFFER_MAX = 100_000
    LOG_BUFFER_DEFAULT = 1_000

    REQUEST_TIMEOUT_MIN = 1
    REQUEST_TIMEOUT_MAX = 300

    IDLE_TIMEOUT_MIN = 1

# constants/formatting.py
class FormatLimit:
    """Formatting and truncation limits."""

    HASH_LENGTH = 8
    PROJECT_NAME_MAX = 20
    REASON_PREVIEW_LENGTH = 50
```

## 6. DECISION ENUM - EXISTS BUT NOT ENFORCED

### Status
- `Decision` enum EXISTS in `core/hook_result.py`
- But some handlers still use `"allow"` strings instead of `Decision.ALLOW`

### Required
- QA rule to enforce Decision enum usage
- Migrate remaining string usages

## 7. EVENT_TYPE_MAPPING - MISSED

### Problem
`handlers/registry.py` has hardcoded event type string keys:

```python
EVENT_TYPE_MAPPING: dict[str, EventType] = {
    "pre_tool_use": EventType.PRE_TOOL_USE,  # ← Magic string keys
    "post_tool_use": EventType.POST_TOOL_USE,
    # ...
}
```

### Solution
Use EventID constants for keys

## 8. ADDITIONAL MAGIC NUMBERS

### Subprocess Timeouts
- `timeout=30` in `validate_eslint_on_write.py`
- `timeout=0.5` in `git_branch.py`
- `timeout=5` in `git_context_injector.py`

### Should Be
```python
timeout=Timeout.ESLINT_CHECK  # 30 seconds
timeout=Timeout.GIT_STATUS_SHORT  # 0.5 seconds
timeout=Timeout.GIT_CONTEXT  # 5 seconds
```

## REVISED CONSTANTS STRUCTURE

```
constants/
├── __init__.py          # ✅ Already in original plan
├── handlers.py          # ✅ Already in original plan (HandlerID, HandlerKey)
├── events.py            # ✅ Already in original plan (EventID, EventKey)
├── priority.py          # ✅ Already in original plan (Priority, PriorityRange)
├── timeout.py           # ✅ Already in original plan (Timeout)
├── paths.py             # ✅ Already in original plan (DaemonPath, ProjectPath)
├── tags.py              # ❌ NEW - HandlerTag, TagLiteral
├── tools.py             # ❌ NEW - ToolName, ToolNameLiteral
├── config.py            # ❌ NEW - ConfigKey
├── protocol.py          # ❌ NEW - HookInputField, HookOutputField
├── validation.py        # ❌ NEW - ValidationLimit
└── formatting.py        # ❌ NEW - FormatLimit
```

## FILES AFFECTED BY CATEGORY

### Tags (67 files)
All handler files + config system + registry

### Tool Names (31 files)
Handlers that check tool_name in matches()

### Config Keys (15+ files)
Config loading, validation, registry

### Protocol Fields (5 files)
Event models, HookResult, input schemas

### Validation Limits (3 files)
Config models, validators

### Decision Strings (42 files)
All handlers that return HookResult

## ASSESSMENT

**Original Plan Completeness**: 60%
**Critical Omissions**: 4 (tags, tools, config keys, protocol)
**Moderate Omissions**: 2 (validation limits, EVENT_TYPE_MAPPING)
**Minor Omissions**: 2 (decision enforcement, subprocess timeouts)

The plan is SOLID for what it covers but NOT comprehensive. The tags system alone affects 67 files and was completely absent.
