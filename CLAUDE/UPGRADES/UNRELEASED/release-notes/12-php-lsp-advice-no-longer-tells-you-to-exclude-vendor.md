# Callout: PHP LSP advice no longer tells you to exclude `vendor/`

**Plan**: 00462
**Audience**: client projects

`lsp_noise_checker`'s PHP advice (`R-LSP-CONFIG-EXCLUDE`) previously told a
project-scope intelephense override to exclude `**/vendor` alongside the
daemon's other vendored/build directories. intelephense's `files.exclude`
removes files from its INDEX, not just its diagnostics, so following that
advice exactly left `PHPUnit\Framework\TestCase`, Doctrine and Symfony types
undefined project-wide. The advice now asks for intelephense's own default
nested excludes instead (`**/vendor/**/{Tests,tests}/**` and
`**/vendor/**/vendor/**`), which keep `vendor/` indexed. An existing override
that still excludes the whole of `vendor/` is now flagged as harmful, naming
the exact entry to remove.

If your project followed the old advice, see the paired post-upgrade task
for the exact fix.
