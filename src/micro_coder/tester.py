import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    passed: bool
    returncode: int
    output: str
    duration: float = 0.0
    command: str = ""

    def format_for_llm(self, max_chars: int = 3000) -> str:
        """
        Formats test failures into a concise, token-efficient string
        tailored for LLM self-healing prompts.
        """
        if self.passed:
            return "All tests passed successfully."

        trimmed_output = self.output.strip()
        if len(trimmed_output) > max_chars:
            # Preserve the tail where pytest prints the summary and assertion tracebacks
            trimmed_output = (
                f"... [output truncated] ...\n{trimmed_output[-max_chars:]}"
            )

        return (
            f"Pytest Execution Failed (Exit Code {self.returncode})\n"
            f"Command: {self.command}\n"
            f"--- Failure Traceback ---\n"
            f"{trimmed_output}"
        )


def find_test_files_for(
    modified_files: list[str | Path],
    root: str | Path = ".",
) -> list[Path]:
    """
    Intelligently maps modified source files to their corresponding test files.
    Heuristics:
    1. If the file is already a test (e.g. `test_*.py` or in `tests/`), run it directly.
    2. If `calculator.py` is modified, searches for `tests/test_calculator.py`,
       `tests/calculator_test.py`, or `test_calculator.py`.
    """
    root_path = Path(root).resolve()
    discovered: set[Path] = set()

    for file in modified_files:
        f_path = Path(file)
        stem = f_path.stem

        # Case 1: The modified file is itself a test file
        if stem.startswith("test_") or stem.endswith("_test"):
            full_path = (root_path / f_path).resolve()
            if full_path.is_file():
                discovered.add(full_path)
            continue

        # Case 2: Source file — check common test naming conventions
        candidates = [
            f"test_{stem}.py",
            f"{stem}_test.py",
        ]

        search_directories = [
            root_path / "tests",
            root_path / "test",
            (root_path / f_path.parent),
            root_path,
        ]

        for s_dir in search_directories:
            for candidate in candidates:
                cand_path = (s_dir / candidate).resolve()
                if cand_path.is_file():
                    discovered.add(cand_path)

    return sorted(discovered)


def discover_all_tests(root: str | Path = ".") -> list[Path]:
    """Finds all test files in the project (e.g. under tests/ or test_*.py in root)."""
    root_path = Path(root).resolve()
    tests_dir = root_path / "tests"
    if tests_dir.is_dir():
        tests = list(tests_dir.rglob("test_*.py"))
        if tests:
            return sorted(tests)
    return sorted(root_path.glob("test_*.py"))


def run_tests(
    targets: list[str | Path] | None = None,
    root: str | Path = ".",
    timeout: int = 30,
) -> TestResult:
    """
    Executes pytest on target test files or discovered project tests.
    Returns a structured TestResult with clean stdout/stderr and timing.
    """
    root_path = Path(root).resolve()

    # Determine what to run
    resolved_targets: list[str] = []
    if targets:
        for t in targets:
            resolved_targets.append(str(Path(t).resolve()))
    else:
        # Fall back to discovering any tests in the workspace
        all_tests = discover_all_tests(root_path)
        resolved_targets = [str(p) for p in all_tests]

    # If no tests exist in this project at all, cleanly report pass
    if not resolved_targets:
        return TestResult(
            passed=True,
            returncode=0,
            output="No test files found in project.",
            duration=0.0,
            command="pytest (no tests)",
        )

    # Command configuration:
    # -q: quiet (suppresses environment headers)
    # --tb=short: short stack traces (reduces token overhead for the LLM)
    # --no-header: removes unnecessary pytest banners
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "--no-header",
    ] + resolved_targets

    cmd_str = " ".join(cmd)
    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = round(time.time() - start_time, 2)
        raw_output = (proc.stdout + "\n" + proc.stderr).strip()

        # Exit code 0: All passed
        # Exit code 5: Pytest ran but collected 0 tests (treat as passed / benign)
        passed = proc.returncode in (0, 5)

        return TestResult(
            passed=passed,
            returncode=proc.returncode,
            output=raw_output,
            duration=duration,
            command=cmd_str,
        )

    except subprocess.TimeoutExpired:
        duration = round(time.time() - start_time, 2)
        return TestResult(
            passed=False,
            returncode=-1,
            output=f"Test run timed out after {timeout} seconds. Possible infinite loop in test or modified code.",
            duration=duration,
            command=cmd_str,
        )
    except Exception as e:
        duration = round(time.time() - start_time, 2)
        return TestResult(
            passed=False,
            returncode=-1,
            output=f"Failed to execute pytest: {e}",
            duration=duration,
            command=cmd_str,
        )
