"""SubagentStop handlers for claude-code-hooks-daemon.

Empty since Plan 00237. ``subagent_completion_logger`` appended to a JSONL log
nothing read; ``remind_prompt_library`` unconditionally advised running
``npm run llm:prompts`` and reading ``CLAUDE/PromptLibrary/README.md``, neither
of which exists in this repository. The package stays so SubagentStop remains a
registered, dispatchable event with a home for future handlers.
"""

__all__: list[str] = []
