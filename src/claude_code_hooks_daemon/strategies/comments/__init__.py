"""Comment syntax strategies for multi-language support.

Strategy Pattern implementation: each language supplies comment SYNTAX data
(line prefixes, block/doc delimiters) via a CommentStrategy. Extraction and
matching logic live once, shared, in ``extractor.py`` and the
``comment_size``/``comment_changelog`` handlers.
"""
