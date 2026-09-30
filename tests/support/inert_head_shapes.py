"""Command shapes for the inert-head exemption (Plan 00408 Task 3.3).

One set of lists, shared by the ``shell_segmentation`` unit tests and by each
guard that adopts ``is_wholly_inert_command``, so a shape added here is proved
against every consumer at once rather than against whichever one a test author
remembered.

Each template carries :data:`PLACEHOLDER` where the guarded command goes. A
placeholder is used instead of ``str.format`` because the shapes themselves
contain shell braces.
"""

from typing import Final

PLACEHOLDER: Final[str] = "@CMD@"

#: WHOLE commands that are one bare inert head and nothing else: the false
#: positives the exemption exists to clear.
INERT_SHAPES: Final[tuple[str, ...]] = (
    "echo '@CMD@'",
    'echo "@CMD@"',
    "echo @CMD@",
    "echo -e '@CMD@'",
    "echo -n '@CMD@'",
    "printf '%s\\n' '@CMD@'",
    "printf '%b' '@CMD@'",
    "printf '%s' -v '@CMD@'",
    ": '@CMD@'",
    "true '@CMD@'",
    "  echo '@CMD@'",
    "\techo '@CMD@'",
    "echo 'a' # @CMD@",
    "echo \\; '@CMD@'",
    "echo \"\\$x\" '@CMD@'",
)

#: Shapes where the guarded command CAN run: the deny-preservation matrix.
ESCAPE_SHAPES: Final[tuple[str, ...]] = (
    # A following segment is its own command.
    "echo x; @CMD@",
    "echo x && @CMD@",
    "echo x || @CMD@",
    "echo x & @CMD@",
    "echo x\n@CMD@",
    # Output handed to something else.
    "echo '@CMD@' | bash",
    "echo '@CMD@' |& bash",
    "printf '%b' '@CMD@' | sh",
    "echo -e '@CMD@' | xargs -I{} sh -c {}",
    # Substitution inside the argument runs before echo sees it.
    'echo "$(@CMD@)"',
    "echo $(@CMD@)",
    "echo `@CMD@`",
    'echo "`@CMD@`"',
    "echo <(@CMD@)",
    "echo $'@CMD@'",
    "echo \"$x\" '@CMD@'",
    # A doubled backslash escapes only ITSELF, leaving the following `$` or
    # backtick live -- the pairing a one-character-skip mutant would break.
    'echo "\\\\$(@CMD@)"',
    "echo \\\\$(@CMD@)",
    'echo "\\\\`@CMD@`"',
    # Written somewhere that is executed later.
    "echo '@CMD@' > f.sh; bash f.sh",
    "echo '@CMD@' >> f.sh && . f.sh",
    "echo '@CMD@' &> f.sh; source f.sh",
    "echo '@CMD@' 2>&1 >f.sh",
    "echo '@CMD@' > >(bash)",
    # printf -v assigns, and the variable can be run.
    "printf -v cmd '@CMD@'; $cmd",
    "printf -\"v\" cmd '@CMD@'; $cmd",
    "printf -v cmd '@CMD@'; bash -c \"$cmd\"",
    'printf -"v" cmd \'@CMD@\'; bash -c "$cmd"',
    "printf -\\v cmd '@CMD@'; bash -c \"$cmd\"",
    # Not the bare head.
    "builtin echo '@CMD@'",
    "command echo '@CMD@'",
    "env echo '@CMD@'",
    "nice echo '@CMD@'",
    "time echo '@CMD@'",
    "exec echo '@CMD@'",
    "xargs echo '@CMD@'",
    "sudo echo '@CMD@'",
    "'echo' '@CMD@'",
    "\\echo '@CMD@'",
    "/bin/echo '@CMD@'",
    "X=1 echo '@CMD@'",
    "eval echo '@CMD@'",
    # The head is rebound, or the shell's output rerouted, in this command.
    "alias echo=bash; echo '@CMD@'",
    "echo() { bash -c \"$*\"; }; echo '@CMD@'",
    "function echo { bash -c \"$*\"; }; echo '@CMD@'",
    "true() { bash -c \"$1\"; }; true '@CMD@'",
    "eval 'printf() { bash -c \"$1\"; }'; printf '@CMD@'",
    ". defs.sh; echo '@CMD@'",
    "source defs.sh; echo '@CMD@'",
    "exec > f.sh; echo '@CMD@'",
    "enable -n echo; echo '@CMD@'",
    "x=eval; $x 'echo() { bash -c \"$1\"; }'; echo '@CMD@'",
    # A group or loop whose output is piped on.
    "{ echo '@CMD@'; } | bash",
    "{ true; echo '@CMD@'; } | bash",
    "( true; echo '@CMD@' ) | bash",
    "while true; do\necho '@CMD@'\ndone | bash",
    "for i in 1; do echo '@CMD@'; done | bash",
    "if true; then\necho '@CMD@'\nfi | bash",
    # A heredoc body is whatever its receiver makes of it.
    "python3 <<EOF\necho '@CMD@'\nEOF",
    "bash <<'EOF'\necho x\n@CMD@\nEOF",
    # A quote inside a comment must not swallow the next line.
    "echo x # don't\n@CMD@ # it's",
    # Unbalanced quoting cannot be segmented soundly.
    "echo 'x\n@CMD@",
)

#: The shapes the round-1 review ran against the per-segment design, and its
#: coverage-gap list. Every one is a compound command or carries an expansion,
#: so each is judged exactly as it was before the exemption existed.
REVIEW_SHAPES: Final[tuple[str, ...]] = (
    # BLOCKER 1: a `#` after an escaped blank or separator is not a comment.
    "echo a\\ #b; @CMD@",
    "echo a\\;#; @CMD@",
    "echo a\\\t#b; @CMD@",
    "echo a\\&#; @CMD@",
    "echo a\\|#; @CMD@",
    # BLOCKER 2: `$_` re-runs the previous command's last argument.
    "echo '@CMD@'; bash -c \"$_\"",
    ": '@CMD@'; sh -c \"$_\"",
    'true \'@CMD@\'; read l <<< "$_"; bash -c "$l"',
    # BLOCKER 3: a trap or the alias table rebinds without a rebinding word.
    "trap 'bash -c \"${BASH_COMMAND:5}\"' DEBUG; echo @CMD@",
    "trap 'bash -c \"$_\"' EXIT; echo '@CMD@'",
    "shopt -s expand_aliases\nBASH_ALIASES[echo]=eval\necho '@CMD@'",
    "BASH_CMDS[echo]=/bin/bash; echo -c '@CMD@'",
    "set -x; PS4='$(@CMD@)'; echo x",
    # Minor: bash's blanks are space and tab only, not Python's whitespace.
    "\x1cecho '@CMD@'",
    "\x0becho '@CMD@'",
    "\x0cecho '@CMD@'",
    "\x85echo '@CMD@'",
    "\xa0echo '@CMD@'",
    "echo\x0b'@CMD@'",
    # Compound heads the matrix did not carry.
    "select x in 1; do echo '@CMD@'; break; done | bash",
    "until false; do echo '@CMD@'; break; done | bash",
    "case x in x) echo '@CMD@';; esac | bash",
    "coproc echo '@CMD@'",
    # Heredoc and here-string spellings.
    "bash <<-EOF\n\t@CMD@\nEOF",
    "bash <<< '@CMD@'",
    "echo <<EOF\n$(@CMD@)\nEOF",
    # Expansions the matrix did not carry.
    "echo $((1)) '@CMD@'",
    "echo $[1] '@CMD@'",
    "echo ${x:-$(@CMD@)}",
    "echo ${x} '@CMD@'",
    'echo $"@CMD@"',
    # Redirections the matrix did not carry.
    "echo '@CMD@' >| f.sh; bash f.sh",
    "echo '@CMD@' <> f.sh; bash f.sh",
    "echo '@CMD@' 1>&3 3>f.sh; bash f.sh",
    # A line continuation into a pipe.
    "echo '@CMD@' \\\n| bash",
)

#: Harmless shapes that are nonetheless NOT one bare inert command. The
#: exemption does not reach them, so each keeps the verdict it had before:
#: a false positive, which is the cheap error.
STILL_JUDGED_SHAPES: Final[tuple[str, ...]] = (
    "ls | echo '@CMD@'",
    "echo '@CMD@'; printf '@CMD@'",
    "echo x <<EOF\n@CMD@\nEOF",
    "echo 'x\n@CMD@'",
    "echo ~ '@CMD@'",
    "echo * '@CMD@'",
    "echo ? '@CMD@'",
    "echo [a] '@CMD@'",
    "echo {a,b} '@CMD@'",
    "echo \"hi!\" '@CMD@'",
    "echo '@CMD@' 2>&1",
    "echo '@CMD@' < /dev/null",
    "printf -- '%s' '@CMD@'",
    "printf -v cmd '@CMD@'",
    "printf -\\v cmd '@CMD@'",
    "echo 'unbalanced @CMD@",
)

#: Everything the exemption must NOT reach.
NOT_INERT_SHAPES: Final[tuple[str, ...]] = ESCAPE_SHAPES + REVIEW_SHAPES + STILL_JUDGED_SHAPES


def fill(template: str, command: str) -> str:
    """``template`` with the guarded ``command`` in place of the placeholder."""
    return template.replace(PLACEHOLDER, command)
