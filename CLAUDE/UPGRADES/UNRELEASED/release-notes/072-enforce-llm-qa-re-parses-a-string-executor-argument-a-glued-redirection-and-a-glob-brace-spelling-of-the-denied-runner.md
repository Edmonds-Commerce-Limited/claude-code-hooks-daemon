# Callout: `enforce_llm_qa` re-parses a string-executor argument, a glued redirection and a glob/brace spelling of the denied runner

**Plan**: 00466
**Audience**: handler authors

The project-local `enforce_llm_qa` handler still allowed the denied runner
through 19 shapes: a `bash -c`/`sh -lc`/`eval`/`ssh <host>`/`watch`/`su -c`/
`timeout … <shell> -c`/`python -c` argument where the script was not the
LAST thing in the string (`bash -c './run_all.sh --fast'`), a redirection
glued to the path with no whitespace (`./run_all.sh>out.txt`), and a glob or
brace word that could expand to the script (`run_all.sh*`,
`{run_all.sh,}`). A string-executor's argument is now re-parsed recursively
as its own shell text, `<`/`>` split off a glued redirection into their own
tokens, and a word is now also checked against the script after resolving
any brace alternation or trailing-glob shape it carries.
