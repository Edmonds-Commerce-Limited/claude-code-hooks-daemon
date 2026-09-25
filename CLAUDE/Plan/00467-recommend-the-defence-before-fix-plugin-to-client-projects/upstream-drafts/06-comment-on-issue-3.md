# Draft: comment on Defence-Before-Fix/claude-plugin#3 (new evidence, not a new issue)

**Status**: draft, not posted. #3 is ours and still open, with no comments.

## Comment

We reproduced this with an agent that has the same tool grant (Read, Grep, Glob, Bash, no Write).
We gave it `agents/independent-searcher.md`'s body verbatim and named a report file. It did not
write the file, and it did not fall back to a Bash heredoc either. It returned the whole report
inline, with this note:

> My operating instructions for this role are explicit read-only ... "Do NOT Write
> report/summary/findings/analysis .md files ... Return findings directly as your final
> assistant message." I did not write `<the named path>`.

A caveat on the reproduction. We used a built-in read-only agent type, because the plugin's own
agent was not loaded in that session. That type's prompt forbids creating files, and a plugin
agent's prompt would not. But the quoted "Do NOT Write report/summary/findings/analysis .md
files" line is not specific to that type. We also see it in the notes Claude Code appends to
general-purpose sub-agents.

So there is a second conflict beside the missing tool. Claude Code's standard sub-agent notes
tell a sub-agent to return findings inline and not to write report files. Our agent obeyed them
over the plugin's "write the full list to the file the coordinator names".
The report survived only because the host project's hooks save every sub-agent reply to a file
on stop. Without that, the coordinator would have got the inline text and no file.

This favours option 2 of the original proposal: have both agents return the full report
inline, and let the skill, which runs in the main session with Write, save it where the project
keeps such records. That matches what the harness already tells sub-agents, so there is nothing
left for the agent to decide between.
