# Callout: the host seat lane guard reads a short per-language command list, and only a declared host duty arms it

**Plan**: 00635
**Audience**: operators

`host_seat_lane_guard` now takes its test, build, lint and QA commands from a short per-language list (Universal, Python, JavaScript, Shell, Go, Rust, Java, Ruby, PHP, .NET), so a language's common commands are recognised in one place. Newly recognised: `npm t` and `pnpm t`, `pre-commit run`, `composer test`, `phpunit`, `rspec` and `bundle exec rspec`, and `dotnet test` / `dotnet build`. Every command it recognised before is still recognised, through the same common wrappers (`env`, `sudo`, `timeout`, `nice`, `uv run`, `python -m`, `sh -c`). The long tail of wrapper spellings is deliberately not chased: the guard advises, it is not a sandbox. `docker exec` and `ssh` remain unclassified.

Arming is narrower. A teamchat seat whose duty is null, missing or unreadable no longer arms the guard: duty is an optional teams field, so only an explicit `host` duty does. A host duty in one team is not disarmed by a null duty in another. A probe that gives no answer at all still keeps the guard armed, as before.
