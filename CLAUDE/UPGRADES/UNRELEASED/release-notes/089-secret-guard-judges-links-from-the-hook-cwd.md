# Callout: the secret guard judges a link from the command's own directory

**Plan**: 00614
**Audience**: client projects

A symlink with an innocuous name that points at a protected file was denied when spelled as an absolute path, but three spellings reached the file's content past `secret_file_guard`:

- A relative Bash word naming the link (`cat link`, `cat < link`, an interpreter one-liner's `open('link')`). The daemon runs from `/`, so the link was looked up there instead of in the command's working directory. It is now resolved from the hook's `cwd` (and every literal `cd` target), and a link anywhere on the path counts, not only the last component. A relative `Read` or `Grep` path is judged the same way.
- A recursive search (the Grep tool, `grep -r`, `rg`) rooted at a directory link that leads out of the project, typically into another checkout from a worktree. The protected-file index lists only the project, so such a search is no longer vouched for and is denied.
- A glob under a directory link (`cat dlink/*`) that leads out of the project. Plan 00612 already matches such a glob with its literal directory resolved; a target outside the project is now denied too.
- A `cd` the command makes anywhere bash runs it: in a subshell `( )`, a brace group, after `if`/`while`/`then`, in a `$( )` or backtick substitution, in a quoted `bash -c` body, and `env -C`/`--chdir` and `git -C`. All of these now move where a relative link is read, for both the text scan and a recursive search.
- A glob whose wildcard sits in the component that names the directory link (`cat dl*/*`, `cat pl*/sub/*`, `grep -r x dl*`). The matching links in the literal parent are listed and judged. A glob whose first component is wildcards only (`*/*`) still names no place and is allowed.
- A command an exemption clears (an allowlisted consumer such as `ansible-playbook` with the protected path in flag position, a grep whose protected mention is only its pattern, or one naming an encrypted-at-rest file) no longer clears a relative link to a protected file beside it.

Behaviour change: a recursive search or a glob through a link from inside the project to a directory outside it is denied even when that directory holds no protected file. The deny message now says that a link to a directory outside the project is the cause, names the link, and says to run the command from the checkout that holds the target. It also names the first configured protected glob, because no particular file matched.

- A `cd` spelled `builtin cd`, `command cd`, or with a redirection before it or before its operand (`>/dev/null cd x`, `cd 2>/dev/null x`), and the chdir options `sudo -D`/`--chdir` and `tar -C`/`--directory`. All of these now move where a relative word is read.
- A glob with no slash (`*`, `i*`, `*/*`) read after a `cd` into a directory link that leads out of the project. It is now denied like `./*`.

Behaviour change: a `cd` whose target bash computes (`cd "$D"`, `cd $(pwd)/x`, `cd -`, a bare `cd`) now makes relative words and search roots be read from the project root, and from every project directory that holds a link, as well as from the hook's `cwd` and every literal target. Before, they were dropped. So `cd "$D" && grep -r foo .` is now judged over the project root. A variable the same command assigns literally (`D=x; cd "$D"`) is put in, and a globbed target (`cd inn?r`) is expanded on disk. The directories that hold a link are found by a scan of at most 512 directories. A link deeper than that in a larger tree is not judged from a computed `cd`.

Behaviour change: if working out where a command's paths lead raises an error, the call is now denied rather than allowed with an advisory. This covers placing a directory it moves to, a link or a glob. Before the fix, a `cd` to a single name over 255 bytes made every protected read in the same command go unjudged. A failed `cd` (to a name that is not a directory) keeps the directory a recursive search was already in, as bash does for a command after `;` or `||`.

Behaviour change: when a command moves into more than 16 existing directories, a relative word that could pass through a link in one of them is denied rather than resolved from each, and the deny message says to split the command. The same rule applies to the quarantine-artefact guard, which shares the index. A path that is outside the project as spelled is judged as before, and an ordinary relative word that is not a link behaves as before.

Upgrade: nothing to do.
