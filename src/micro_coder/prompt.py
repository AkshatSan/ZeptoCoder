from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from micro_coder.linter import LintError
    from micro_coder.tester import TestResult

# Dynamically generate markers to prevent VS Code and Git from misinterpreting
# them as active merge conflicts in the editor.
SEARCH_MARKER = "<" * 7 + " SEARCH"
DIVIDER_MARKER = "=" * 7
REPLACE_MARKER = ">" * 7 + " REPLACE"

SYSTEM_PROMPT = f"""You are micro-coder, an expert AI pair programming assistant working directly in the user's terminal and local repository.

When modifying or creating code:
1. Output your code changes as SEARCH/REPLACE blocks.
2. Before every SEARCH/REPLACE block, output the relative file path on its own line.
3. Every SEARCH block must match EXACT lines from the existing file, including indentation and whitespace.
4. Keep SEARCH blocks as small as possible, including only enough lines to uniquely identify the section to be replaced.
5. Do NOT include line numbers or markdown formatting inside the SEARCH or REPLACE blocks.

Format for code edits:
path/to/file.py
{SEARCH_MARKER}
exact lines of code to replace
{DIVIDER_MARKER}
new lines of code
{REPLACE_MARKER}

If the user asks an informational question or does not ask to modify code, reply normally without SEARCH/REPLACE blocks.
"""


def format_self_healing_prompt(
    lint_errors: list["LintError"] | None = None,
    test_result: "TestResult" | None = None,
    attempt: int = 1,
    max_attempts: int = 3,
) -> str:
    """
    Constructs an assertive, targeted self-healing prompt instructing the LLM
    to fix lint or test regressions using SEARCH/REPLACE blocks.
    """
    sections = []

    # 1. Format Lint & Syntax Diagnostics
    if lint_errors:
        error_lines = [f"- {err.format()}" for err in lint_errors]
        sections.append("### Syntax & Linter Errors:\n" + "\n".join(error_lines))

    # 2. Format Pytest Failure Output
    if test_result and not test_result.passed:
        sections.append(
            "### Test Suite Failures:\n" + test_result.format_for_llm(max_chars=2500)
        )

    error_summary = "\n\n".join(sections)

    return f"""The previous edits introduced errors or broke existing tests (Attempt {attempt} of {max_attempts}).

{error_summary}

CRITICAL INSTRUCTIONS:
1. Fix the errors above. Respond ONLY with SEARCH/REPLACE blocks for the files that need fixing.
2. The {SEARCH_MARKER} block must match the CURRENT code on disk exactly (including exact indentation and whitespace).
3. Do NOT provide conversational explanations, apologies, or markdown text outside of the SEARCH/REPLACE blocks.
4. Keep edits strictly focused on resolving the errors; do not refactor or alter unrelated working code.
"""
