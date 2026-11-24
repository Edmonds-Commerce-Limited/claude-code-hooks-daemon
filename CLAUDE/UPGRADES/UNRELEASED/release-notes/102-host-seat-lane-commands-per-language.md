# Callout: the host seat lane guard reads a short per-language command list, and only a declared host duty arms it

**Plan**: 00635
**Audience**: operators

`host_seat_lane_guard` takes its test, build, lint and QA commands from a short per-language list (Universal, Python, JavaScript, Shell, Go, Rust, Java, Ruby, PHP, .NET), so a language's common commands are recognised in one place. Among them: `npm t` and `pnpm t`, `pre-commit run`, `composer test`, `phpunit`, `rspec` and `bundle exec rspec`, and `dotnet test` / `dotnet build`. Commands are recognised through the common wrappers (`env`, `sudo`, `timeout`, `nice`, `uv run`, `python -m`, `sh -c`; `npx` only for the common JavaScript runners). The long tail of wrapper spellings is deliberately not chased: the guard advises, it is not a sandbox. `docker exec` and `ssh` are not classified.

What arms it: a teamchat seat with an explicit `host` duty in any team, even when another team's duty is null. A seat whose duty is null, missing or unreadable does not arm it, because duty is an optional teams field. A teamchat probe that gives no answer at all keeps the guard armed.
