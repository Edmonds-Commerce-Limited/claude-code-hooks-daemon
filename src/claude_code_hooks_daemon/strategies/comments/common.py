"""Shared defaults for comment-strategy implementations.

Every language strategy needs a `skip_directories` list, and the common
case (vendor code, build output, test fixtures) is identical across
languages -- defined ONCE here rather than duplicated inside each
per-language file. A strategy with genuinely language-specific extra
directories can still add its own on top of this tuple.
"""

DEFAULT_SKIP_DIRECTORIES: tuple[str, ...] = (
    "vendor/",
    "node_modules/",
    "tests/fixtures/",
    "tests/assets/",
    "migrations/",
    ".venv/",
    "venv/",
    "build/",
    "dist/",
)
