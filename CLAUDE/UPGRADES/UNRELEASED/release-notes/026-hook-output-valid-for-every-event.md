# Fix: fail-open hook output is valid for every event under Claude Code 2.1.289

**Plan**: none (urgent field report)
**Audience**: everyone

Claude Code 2.1.289 validates hook JSON output strictly. In a project where the daemon was not installed, not running, or its venv was missing, `init.sh` answered every non-Stop event with `hookSpecificOutput`, which most events do not define (SessionEnd, PreCompact, PostCompact, Notification, Setup and others). Claude Code rejected the whole document, so the SessionEnd hook failed with "Hook JSON output validation failed" and the explanation was lost with it.

Every fail-open answer now follows the per-event contract (`contracts/claude-code-hooks/`): `hookSpecificOutput.additionalContext` only for events that define it, the universal top-level `systemMessage` for the rest. Stop and SubagentStop still block. The same fix covers the CI-enforced answer, the provisioning answer, the CI passthrough advisory and the transport's no-daemon answer, and a CI-enforced PreToolUse deny is now a `permissionDecision: deny` rather than an undefined top-level `decision`.

On the daemon side, a refusal returned by a handler on an event that cannot carry one used to be emitted as an undefined top-level `decision` for the events that have no event-specific schema; it is now replaced by an explanatory `systemMessage`.
