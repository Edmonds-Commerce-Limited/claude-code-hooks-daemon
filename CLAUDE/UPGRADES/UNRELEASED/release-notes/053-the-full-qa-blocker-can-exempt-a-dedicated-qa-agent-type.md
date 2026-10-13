# Callout: subagent_full_qa_blocker can exempt a dedicated QA agent type, one run at a time

**Plan**: 00518
**Audience**: client projects

A project that runs its full QA gate through a dedicated agent no longer has to leave `subagent_full_qa_blocker` off. The new option `exempt_agent_types` lists exact agent definition-type names (the `name` in `.claude/agents/<name>.md`); a sub-agent of a listed type is allowed to run a declared full-suite command, with an advisory naming the entry that exempted it. The exemption comes with one run at a time: while another full run holds the host-wide full-QA lock the call is denied, and a holder that ended or died never blocks. A sub-agent whose `agent_type` is missing or empty is never exempt, the match is exact (no globs, no case folding), and the default is an empty list, which changes nothing.

A named agent's `agent_type` in the hook payload is its dispatch `name`, not its definition type, so the new silent handler `agent_dispatch_recorder` records `name -> subagent_type` when it sees the dispatch and the blocker reads the type back from that record. A teammate named like a listed type is therefore not exempt. Keep `agent_dispatch_recorder` enabled (it ships on) if you list a type. An unnamed agent's `agent_type` is trusted as its type; the payload offers nothing to check it against.

The `optimise` review now looks for a dedicated full-QA runner agent under `.claude/agents/` (a name carrying `full`, `runner` and one of `qa`, `pipeline`, `gate`, `suite`, such as `php-qa-ci_full-pipeline-runner`) and, when it finds one, recommends enabling `subagent_full_qa_blocker` with `exempt_agent_types: [<that agent type>]` instead of leaving it off.
