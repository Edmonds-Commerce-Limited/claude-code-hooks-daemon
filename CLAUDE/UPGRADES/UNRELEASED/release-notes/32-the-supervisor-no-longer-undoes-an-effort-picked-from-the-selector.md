# Callout: the ccy supervisor no longer undoes an effort level picked from the selector

**Plan**: 00422
**Audience**: operators

A bare `/effort` opens Claude Code's selector, which types no level, so the
supervisor used to miss the choice and its per-model effort floor put the old
level back. The supervisor now trusts any effort drop it did not type itself
as your choice. It latches the drop exactly like a typed `/effort <level>`, and
the floor stays off for the rest of that model spell. Its own `/effort`
injections are recognised when they land, even after a late status render, so
they are never mistaken for yours. This deliberately mirrors the model-downgrade
rule, where an unattributed model change gets no restore. The decision log
records each latched drop.
