import ast
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LintError:
    file: str
    line: int
    column: int
    message: str
    code: str | None = None
    source: str = "ast"  # "ast" or "ruff"

    def format(self) -> str:
        """Formats the error into a compiler-style line recognizable by LLMs."""
        code_tag = f" [{self.code}]" if self.code else ""
        return f"{self.file}:{self.line}:{self.column}:{code_tag} {self.message}"


def check_syntax_ast(code: str, filepath: str | Path) -> list[LintError]:
    """
    Tier 1 Check: In-process AST parsing.
    Catches raw SyntaxError and IndentationError in < 1ms without subprocess overhead.
    """
    try:
        ast.parse(code, filename=str(filepath))
        return []
    except SyntaxError as e:
        return [
            LintError(
                file=str(filepath),
                line=e.lineno or 1,
                column=e.offset or 1,
                message=e.msg or "Syntax error",
                code="SyntaxError",
                source="ast",
            )
        ]


def run_ruff(filepath: str | Path) -> list[LintError]:
    """
    Tier 2 Check: Invokes `ruff check` using JSON output for deterministic parsing.
    Catches undefined variables, unused imports, and style bugs.
    """
    path = Path(filepath)
    if not path.exists():
        return [
            LintError(
                file=str(filepath),
                line=1,
                column=1,
                message=f"File not found: {filepath}",
                code="FileNotFound",
                source="ruff",
            )
        ]

    cmd = ["ruff", "check", "--output-format=json", str(path)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,  # Ruff returns exit code 1 when lint errors exist
        )
    except FileNotFoundError:
        # If ruff is not in PATH or virtualenv, fail gracefully
        return [
            LintError(
                file=str(filepath),
                line=1,
                column=1,
                message="ruff executable not found in environment",
                code="MissingTool",
                source="ruff",
            )
        ]

    # Empty stdout means no errors were discovered
    if not result.stdout.strip():
        return []

    try:
        diagnostics = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    errors: list[LintError] = []
    for diag in diagnostics:
        location = diag.get("location", {})
        errors.append(
            LintError(
                file=str(filepath),
                line=location.get("row", 1),
                column=location.get("column", 1),
                message=diag.get("message", "Lint issue"),
                code=diag.get("code"),
                source="ruff",
            )
        )

    return errors


def lint_file(filepath: str | Path) -> list[LintError]:
    """
    Runs the multi-tier linter on a single file:
    1. Tier 1 (AST Parse): Fast syntax check.
    2. Tier 2 (Ruff): Runs only if syntax check passes.
    """
    path = Path(filepath)
    if not path.is_file():
        return []

    # Only run Python AST and Ruff on Python files
    if path.suffix.lower() != ".py":
        return []

    try:
        code = path.read_text(encoding="utf-8")
    except Exception as e:
        return [
            LintError(
                file=str(path),
                line=1,
                column=1,
                message=f"Failed to read file: {e}",
                code="IOError",
                source="ast",
            )
        ]

    # Tier 1: AST Parse
    syntax_errors = check_syntax_ast(code, path)
    if syntax_errors:
        # If the file has invalid syntax, stop immediately.
        # Running Ruff on broken syntax produces redundant or misleading messages.
        return syntax_errors

    # Tier 2: Ruff Linter
    return run_ruff(path)


def lint_files(filepaths: list[str | Path]) -> list[LintError]:
    """Lints multiple files and returns all accumulated errors."""
    all_errors: list[LintError] = []
    for p in filepaths:
        all_errors.extend(lint_file(p))
    return all_errors
