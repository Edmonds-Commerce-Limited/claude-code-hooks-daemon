"""Comprehensive tests for BritishEnglishHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.british_english import BritishEnglishHandler


class TestBritishEnglishHandler:
    """Test suite for BritishEnglishHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return BritishEnglishHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'enforce-british-english'."""
        assert handler.name == "enforce-british-english"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 60."""
        assert handler.priority == 60

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be non-terminal (allows operation but adds warning)."""
        assert handler.terminal is False

    def test_init_has_spelling_checks_dict(self, handler):
        """Handler should have SPELLING_CHECKS dictionary."""
        assert hasattr(handler, "SPELLING_CHECKS")
        assert len(handler.SPELLING_CHECKS) == 9

    def test_init_has_check_extensions_list(self, handler):
        """Handler should have CHECK_EXTENSIONS list."""
        assert hasattr(handler, "CHECK_EXTENSIONS")
        assert ".md" in handler.CHECK_EXTENSIONS
        assert ".html" in handler.CHECK_EXTENSIONS

    def test_init_has_check_directories_list(self, handler):
        """Handler should have CHECK_DIRECTORIES list."""
        assert hasattr(handler, "CHECK_DIRECTORIES")
        assert "CLAUDE" in handler.CHECK_DIRECTORIES
        assert "docs" in handler.CHECK_DIRECTORIES

    # matches() - Positive Cases: Write tool with American spellings
    def test_matches_write_md_file_with_color(self, handler):
        """Should match Write to .md file containing 'color'."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/docs/test.md",
                "content": "This is the color of the sky.",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_html_file_with_favor(self, handler):
        """Should match Write to .html file containing 'favor'."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/docs/test.html",
                "content": "Please favor this approach.",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_txt_file_with_behavior(self, handler):
        """Should match Write to .txt file containing 'behavior'."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/behavior.txt",
                "content": "The behavior is incorrect.",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_ejs_file_with_organize(self, handler):
        """Should match Write to .ejs file containing 'organize'."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/private_html/template.ejs",
                "content": "Let's organize the data.",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_all_american_spellings(self, handler):
        """Should match all American spelling patterns."""
        american_words = [
            ("color", "colour"),
            ("favor", "favour"),
            ("behavior", "behaviour"),
            ("organize", "organise"),
            ("recognize", "recognise"),
            ("analyze", "analyse"),
            ("center", "centre"),
            ("meter", "metre"),
            ("liter", "litre"),
        ]

        for american, _british in american_words:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/workspace/CLAUDE/test.md",
                    "content": f"This sentence contains {american} as a word.",
                },
            }
            assert handler.matches(hook_input) is True, f"Should match: {american}"

    def test_matches_multiple_american_spellings_in_one_file(self, handler):
        """Should match when multiple American spellings present."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/docs/test.md",
                "content": "The color and behavior need organization.",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Edit tool
    def test_matches_edit_tool_with_american_spelling_in_new_string(self, handler):
        """Should match Edit tool with American spelling in new_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "old_string": "old text",
                "new_string": "This is the color of the system.",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_tool_ignores_old_string(self, handler):
        """Should only check new_string in Edit operations, not old_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "old_string": "The color is wrong",  # American in old_string
                "new_string": "The colour is correct",  # British in new_string
            },
        }
        # Should not match because new_string has British spelling
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: File filtering
    def test_matches_wrong_tool_returns_false(self, handler):
        """Should not match non-Write/Edit tools."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "echo 'color'"}}
        assert handler.matches(hook_input) is False

    def test_matches_non_content_file_extension_returns_false(self, handler):
        """Should not match non-content file extensions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/test.py", "content": "color = 'blue'"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_wrong_directory_returns_false(self, handler):
        """Should not match files outside checked directories."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/component.md",
                "content": "This has the word color.",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_british_spelling_returns_false(self, handler):
        """Should not match when only British spellings present."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "content": "The colour and behaviour show proper organisation.",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_content_returns_false(self, handler):
        """Should not match when content is empty."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": ""},
        }
        assert handler.matches(hook_input) is False

    def test_matches_none_content_returns_false(self, handler):
        """Should not match when content is None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": None},
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_file_path_returns_false(self, handler):
        """Should not match when file_path is missing."""
        hook_input = {"tool_name": "Write", "tool_input": {"content": "This has color."}}
        assert handler.matches(hook_input) is False

    # matches() - Code block exclusion
    def test_matches_ignores_american_spelling_in_code_block(self, handler):
        """Should ignore American spellings inside markdown code blocks."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "content": """
Some text here.

```python
# This code uses color
color = 'blue'
```

Regular text with colour.
""",
            },
        }
        # Should not match because 'color' is in code block
        # But would still match if there were American spellings outside blocks
        assert handler.matches(hook_input) is False

    def test_matches_detects_american_spelling_outside_code_blocks(self, handler):
        """Should detect American spellings outside code blocks."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "content": """
The color is important.

```python
# This is fine
colour = 'blue'
```

More text here.
""",
            },
        }
        # Should match because 'color' is outside code block
        assert handler.matches(hook_input) is True

    def test_matches_handles_nested_code_blocks(self, handler):
        """Should handle multiple code blocks correctly."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "content": """
Text with colour.

```python
# color here is ignored
```

More text with colour.

```javascript
// color here is also ignored
```

Final text with colour.
""",
            },
        }
        # Should not match - all American spellings in code blocks
        assert handler.matches(hook_input) is False

    # handle() Tests - Non-blocking behavior
    def test_handle_returns_allow_decision(self, handler):
        """handle() should return allow decision (non-blocking)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": "This has color."},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_context_contains_file_path(self, handler):
        """handle() context should include file path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": "This has color."},
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context)
        assert "/workspace/CLAUDE/doc.md" in context_text

    def test_handle_context_contains_american_word(self, handler):
        """handle() context should include the American spelling found."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "content": "This has color in it.",
            },
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context)
        assert "color" in context_text

    def test_handle_context_contains_british_suggestion(self, handler):
        """handle() context should include British spelling suggestion."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "content": "This has color in it.",
            },
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context)
        assert "colour" in context_text

    def test_handle_context_contains_line_number(self, handler):
        """handle() context should include line number of issue."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "content": "Line 1\nThis has color.\nLine 3",
            },
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context)
        assert "Line 2" in context_text

    def test_handle_context_limits_to_5_issues(self, handler):
        """handle() should only show first 5 issues."""
        content_lines = ["This has color."] * 10  # 10 lines with 'color'
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "content": "\n".join(content_lines),
            },
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context)
        # Should mention "5 more issue(s)" since 10 total - 5 shown = 5 remaining
        assert "5 more issue" in context_text

    def test_handle_context_shows_all_issues_when_5_or_fewer(self, handler):
        """handle() should show all issues when 5 or fewer."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/doc.md",
                "content": "Line 1: color\nLine 2: favor\nLine 3: behavior",
            },
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context)
        # Should not mention "more issues"
        assert "more issue" not in context_text

    def test_handle_provides_correct_spelling_guidance(self, handler):
        """handle() should provide guidance about British English."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": "This has color."},
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context)
        assert "CORRECT SPELLING" in context_text
        assert "British English" in context_text

    def test_handle_mentions_intentional_quotes_exception(self, handler):
        """handle() should mention quotes as potential exception."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": "This has color."},
        }
        result = handler.handle(hook_input)
        context_text = "\n".join(result.context)
        assert "quote" in context_text.lower()

    def test_handle_reason_is_none_for_allow(self, handler):
        """handle() reason should be None for advisory ALLOW decisions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": "This has color."},
        }
        result = handler.handle(hook_input)
        assert result.reason is None

    def test_handle_context_is_populated_for_advisory(self, handler):
        """handle() context should be populated with warning for advisory ALLOW decisions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": "This has color."},
        }
        result = handler.handle(hook_input)
        assert len(result.context) > 0
        assert isinstance(result.context, list)

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": "This has color."},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_empty_content_returns_allow(self, handler):
        """handle() should return ALLOW for empty content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/doc.md", "content": ""},
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.reason is None

    # _check_british_english() Tests
    def test_check_british_english_detects_color(self, handler):
        """_check_british_english() should detect 'color'."""
        content = "The color is blue."
        issues = handler._check_british_english(content)
        assert len(issues) == 1
        assert issues[0]["american"] == "color"
        assert issues[0]["british"] == "colour"

    def test_check_british_english_detects_multiple_words(self, handler):
        """_check_british_english() should detect multiple American spellings."""
        content = "The color and behavior need to organize data."
        issues = handler._check_british_english(content)
        assert len(issues) == 3

    def test_check_british_english_provides_line_numbers(self, handler):
        """_check_british_english() should provide accurate line numbers."""
        content = "Line 1\nLine 2 has color\nLine 3"
        issues = handler._check_british_english(content)
        assert issues[0]["line"] == 2

    def test_check_british_english_truncates_long_lines(self, handler):
        """_check_british_english() should truncate lines over 80 chars."""
        long_line = "a" * 100 + " color " + "b" * 100
        content = long_line
        issues = handler._check_british_english(content)
        assert len(issues[0]["text"]) <= 80

    def test_check_british_english_skips_code_blocks(self, handler):
        """_check_british_english() should skip content in code blocks."""
        content = """
Text before.

```python
color = 'blue'  # This should be ignored
```

Text after.
"""
        issues = handler._check_british_english(content)
        assert len(issues) == 0

    def test_check_british_english_toggles_code_block_state(self, handler):
        """_check_british_english() should correctly toggle in/out of code blocks."""
        content = """
color here is detected

```
color here is ignored
```

color here is detected again
"""
        issues = handler._check_british_english(content)
        assert len(issues) == 2  # Only the two outside code block

    def test_check_british_english_handles_empty_content(self, handler):
        """_check_british_english() should handle empty content."""
        content = ""
        issues = handler._check_british_english(content)
        assert len(issues) == 0

    def test_check_british_english_case_insensitive(self, handler):
        """_check_british_english() should be case insensitive."""
        content = "The Color is blue."
        issues = handler._check_british_english(content)
        assert len(issues) == 1
        assert issues[0]["american"] == "Color"

    def test_check_british_english_word_boundaries(self, handler):
        """_check_british_english() should respect word boundaries."""
        content = "The colors and coloration are fine."
        issues = handler._check_british_english(content)
        # Should only match 'color' at word boundary, not in 'colors' or 'coloration'
        # Actually, \bcolor\b won't match 'colors', but the regex is \bcolor\b
        # so 'colors' won't match, 'coloration' won't match
        assert len(issues) == 0

    def test_check_british_english_all_patterns(self, handler):
        """_check_british_english() should detect all 9 American spelling patterns."""
        content = "color favor behavior organize recognize analyze center meter liter"
        issues = handler._check_british_english(content)
        assert len(issues) == 9

    # Integration Tests
    def test_full_workflow_write_with_american_spelling(self, handler):
        """Complete workflow: Write file with American spelling."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/test.md",
                "content": "The color of the system is important.",
            },
        }

        # Should match
        assert handler.matches(hook_input) is True

        # Should allow with warning in context (not reason)
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.reason is None
        context_text = "\n".join(result.context)
        assert "color" in context_text
        assert "colour" in context_text

    def test_full_workflow_edit_with_american_spelling(self, handler):
        """Complete workflow: Edit file introducing American spelling."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/docs/guide.md",
                "old_string": "old text",
                "new_string": "The behavior is unexpected.",
            },
        }

        # Should match
        assert handler.matches(hook_input) is True

        # Should allow with warning in context (not reason)
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.reason is None
        context_text = "\n".join(result.context)
        assert "behavior" in context_text
        assert "behaviour" in context_text

    def test_full_workflow_british_spelling_allowed(self, handler):
        """Complete workflow: British spelling should not trigger warning."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/test.md",
                "content": "The colour and behaviour demonstrate proper organisation.",
            },
        }

        # Should not match
        assert handler.matches(hook_input) is False

    def test_full_workflow_code_file_ignored(self, handler):
        """Complete workflow: Code files should be ignored."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/CLAUDE/script.py",
                "content": "color = 'blue'  # American spelling in code",
            },
        }

        # Should not match (wrong file extension)
        assert handler.matches(hook_input) is False

    def test_all_checked_directories(self, handler):
        """Should check files in all specified directories."""
        directories = ["private_html", "docs", "CLAUDE"]

        for directory in directories:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": f"/workspace/{directory}/test.md",
                    "content": "This has color.",
                },
            }
            assert handler.matches(hook_input) is True, f"Should check: {directory}"

    def test_all_checked_extensions(self, handler):
        """Should check all specified file extensions."""
        extensions = [".md", ".ejs", ".html", ".txt"]

        for ext in extensions:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": f"/workspace/CLAUDE/test{ext}",
                    "content": "This has color.",
                },
            }
            assert handler.matches(hook_input) is True, f"Should check: {ext}"
