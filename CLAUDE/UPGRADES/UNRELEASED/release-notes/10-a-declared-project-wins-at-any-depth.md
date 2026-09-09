# Callout: a declared project wins at any depth, and editing an existing `.md` is never a location violation

**Plan**: 00365
**Audience**: everyone

`markdown_organization` (R-MARKDOWN-WRONG-LOCATION) denied an `Edit` of an
existing `.md` inside a first-party clone that Composer had installed from
source two `vendor/` levels deep, and neither escape hatch rescued it. Three
things changed.

A `projects:` entry now wins outright, wherever its `root` sits. It is
consulted BEFORE the built-in `vendor/` and `node_modules/` inference, so a
sub-project under `vendor/`, inside another declared project, or at any other
depth is declared exactly as it is on disk. That is the supported answer to
"my sub-project lives somewhere unusual": declare it in the top-level config
with its real directory, and it works. Nothing is inferred from directory
shape without a declaration, as before.

The dependency inference itself now repeats through nested dependency trees,
so `vendor/a/b/vendor/c/d/docs/x.md` is judged as `docs/x.md` rather than as
the repository path `vendor/c/d/docs/x.md`. And an `extra_allowed_markdown_paths`
pattern spelled from the repository root (`^vendor/org/pkg/`) now matches; the
package-relative spelling still matches too.

A `.md` file that already exists at the target path is no longer a location
violation for `Edit` or `Write`. The rule is about where NEW markdown lands; a
file that is already there has had its location accepted, and editing it moves
nothing. A genuinely new misplaced file is still denied, and the deny message
now names a `projects:` declaration as one of the fixes.
