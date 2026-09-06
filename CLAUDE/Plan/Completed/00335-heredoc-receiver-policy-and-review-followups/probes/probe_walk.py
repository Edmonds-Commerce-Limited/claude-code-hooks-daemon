from claude_code_hooks_daemon.docs_qa.checks.source_tree_markdown import _walk_into
from claude_code_hooks_daemon.utils.vendor_paths import VendorScope

plain = (VendorScope(root="", vendor_dirs=frozenset({"node_modules"})),)
wildcard = (
    VendorScope(
        root="",
        vendor_dirs=frozenset({"node_modules"}),
        vendor_exceptions=("**/ours/**",),
    ),
)

for label, scopes in (("no exceptions", plain), ("leading-wildcard exception", wildcard)):
    print(label)
    for parts in ((".git",), ("untracked",), ("node_modules",), ("src",)):
        print(f"   descend {parts[0]!r}: {_walk_into(parts, vendor_scopes=scopes)}")
