# Callout: Go files under a `testdata` directory are no longer linted

**Plan**: 00474
**Audience**: client projects

The Go lint at edit time and at commit time ran `go vet` on every `.go` file, including `analysistest` fixtures under a `testdata/` directory. Those fixtures import GOPATH-style packages that exist only inside their own `testdata/src` tree, so `go vet` reported an unresolved import for correct code and the commit gate printed a false failure. The Go toolchain itself ignores `testdata` directories, and the daemon's Go lint now skips them too. Go files elsewhere are linted as before.
