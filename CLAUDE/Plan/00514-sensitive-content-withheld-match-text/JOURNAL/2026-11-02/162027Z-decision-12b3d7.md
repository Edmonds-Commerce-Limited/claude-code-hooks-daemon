## 16:20 · decision · —

Owner ruling, 2 November 2026: public-pattern matches are never disclosed. The deny reason names the pattern and where it matched (path, line, git field, gh body), never the matched text. Implemented across Write, Edit, git metadata and gh bodies; the commit-time scan already named only the path. Release note 017 records it.
