"""Command shapes for the inert-head allowlist (Plan 00408 Task 3.3).

One list, shared by the ``shell_segmentation`` unit tests and by each guard that
adopts ``blank_inert_command_arguments``, so a shape added here is proved
against every consumer at once rather than against whichever one a test author
remembered.

Each template carries :data:`PLACEHOLDER` where the guarded command goes. A
placeholder is used instead of ``str.format`` because the shapes themselves
contain shell braces.
"""

from typing import Final

PLACEHOLDER: Final[str] = "@CMD@"

#: Shapes where the guarded text is an inert head's ARGUMENT and nothing can
#: run it: the false positives the allowlist exists to clear.
INERT_SHAPES: Final[tuple[str, ...]] = (
    "echo '@CMD@'",
    'echo "@CMD@"',
    "echo -e '@CMD@'",
    "echo -n '@CMD@'",
    "printf '%s\\n' '@CMD@'",
    "printf '%b' '@CMD@'",
    ": '@CMD@'",
    "true '@CMD@'",
    "  echo '@CMD@'",
    "echo 'a' # @CMD@",
    "ls | echo '@CMD@'",
    "echo '@CMD@'; printf '@CMD@'",
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
    # Written somewhere that is executed later.
    "echo '@CMD@' > f.sh; bash f.sh",
    "echo '@CMD@' >> f.sh && . f.sh",
    "echo '@CMD@' &> f.sh; source f.sh",
    "echo '@CMD@' 2>&1 >f.sh",
    "echo '@CMD@' > >(bash)",
    # printf -v assigns, and the variable can be run.
    "printf -v cmd '@CMD@'; $cmd",
    "printf -\"v\" cmd '@CMD@'; $cmd",
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


def fill(template: str, command: str) -> str:
    """``template`` with the guarded ``command`` in place of the placeholder."""
    return template.replace(PLACEHOLDER, command)
