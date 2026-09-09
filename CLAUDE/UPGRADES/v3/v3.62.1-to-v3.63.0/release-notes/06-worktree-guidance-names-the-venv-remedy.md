# Callout: worktree guidance now says how to get a working venv

**Plan**: 00358
**Audience**: everyone

The `worktree_create` guidance injected into CLAUDE.md now tells an agent that
a fresh worktree has no Python venv and to build one with the project's setup
script rather than symlinking the main checkout's. A shared venv imports the
package from the main checkout's source, so the worktree's tests silently
exercise the wrong code.
