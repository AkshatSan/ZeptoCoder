import os
import tempfile
from pathlib import Path
from micro_coder.parser import EditBlock


def apply_patch(original_content: str, search_text: str, replace_text: str) -> str:
    """
    Applies a SEARCH/REPLACE diff to original_content.

    Two-tier strategy:
    1. Exact string match: Fast and preserves exact formatting.
    2. Whitespace-normalized line matching: Tolerates trailing whitespace
       and line-ending discrepancies introduced by the LLM.

    Raises ValueError if search_text cannot be matched.
    """
    if not search_text:
        raise ValueError("SEARCH block cannot be empty.")

    # Tier 1: Exact Match
    if search_text in original_content:
        return original_content.replace(search_text, replace_text, 1)

    # Tier 2: Whitespace-Normalized Line Window Matching
    orig_lines_keepends = original_content.splitlines(keepends=True)
    orig_lines = [line.rstrip("\r\n") for line in orig_lines_keepends]
    search_lines = [line.rstrip("\r\n") for line in search_text.splitlines()]

    norm_orig = [line.rstrip() for line in orig_lines]
    norm_search = [line.rstrip() for line in search_lines]

    n_search = len(norm_search)
    n_orig = len(norm_orig)

    if n_search > n_orig:
        raise ValueError(
            f"SEARCH block ({n_search} lines) is larger than file ({n_orig} lines)."
        )

    newline = "\r\n" if "\r\n" in original_content else "\n"

    for i in range(n_orig - n_search + 1):
        if norm_orig[i : i + n_search] == norm_search:
            before = orig_lines_keepends[:i]
            after = orig_lines_keepends[i + n_search :]

            replace_block = replace_text
            if replace_block and not replace_block.endswith(("\n", "\r\n")) and after:
                replace_block += newline

            return "".join(before) + replace_block + "".join(after)

    raise ValueError(
        "Could not find matching code in target file for SEARCH block:\n"
        f"```\n{search_text}\n```"
    )


def resolve_target_file(root: Path, filepath_str: str) -> Path:
    """
    Resolves a file path string from the LLM to a file in the project.
    Falls back to searching the project tree if parent folders were omitted.
    """
    path = Path(filepath_str)
    if path.is_absolute():
        return path

    direct = (root / path).resolve()
    if direct.exists():
        return direct

    # Fallback: search for unique matching filename if LLM omitted parent directories
    matches = list(root.glob(f"**/{path.name}"))
    if len(matches) == 1:
        return matches[0]

    return direct


def atomic_write(target_path: Path, content: str) -> None:
    """
    Writes content to target_path atomically using a temp file and os.replace.
    Guarantees no half-written or corrupted files on crash.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # Create temp file in the same directory so os.replace is an atomic rename
    with tempfile.NamedTemporaryFile(
        "w",
        dir=target_path.parent,
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def apply_blocks_to_disk(
    blocks: list[EditBlock], root: Path
) -> list[tuple[str, bool, str]]:
    """
    Applies a list of EditBlock objects to files on disk.

    Returns a list of status tuples: (filepath, success: bool, message: str).
    Edits for each file are staged in memory first; the file is only modified
    if all blocks for that file apply cleanly.
    """
    results: list[tuple[str, bool, str]] = []

    # Group blocks by file to process multi-block edits sequentially
    files_map: dict[str, list[EditBlock]] = {}
    for block in blocks:
        files_map.setdefault(block.filepath, []).append(block)

    for raw_path, file_blocks in files_map.items():
        resolved = resolve_target_file(root, raw_path)

        if not resolved.exists():
            results.append((raw_path, False, f"File not found: {raw_path}"))
            continue

        try:
            content = resolved.read_text(encoding="utf-8")
        except Exception as e:
            results.append((raw_path, False, f"Error reading file: {e}"))
            continue

        # Stage edits in memory
        current_content = content
        failed = False

        for idx, block in enumerate(file_blocks, 1):
            try:
                current_content = apply_patch(
                    current_content, block.search_text, block.replace_text
                )
            except ValueError as e:
                failed = True
                results.append((raw_path, False, f"Block {idx} failed: {e}"))
                break

        # Only write to disk if every block for this file passed in memory
        if not failed:
            try:
                atomic_write(resolved, current_content)
                results.append(
                    (raw_path, True, f"Successfully applied {len(file_blocks)} edit(s)")
                )
            except Exception as e:
                results.append((raw_path, False, f"Disk write failed: {e}"))

    return results


if __name__ == "__main__":
    import shutil

    # Self-test: Verify atomic disk patching with temporary scratch files
    scratch_dir = Path("./.scratch_test")
    scratch_dir.mkdir(exist_ok=True)
    test_file = scratch_dir / "sample.py"

    try:
        # 1. Setup sample file
        test_file.write_text(
            "def calculate(a, b):\n    return a * b\n", encoding="utf-8"
        )

        # 2. Test successful multi-block patch to disk
        test_blocks = [
            EditBlock(
                filepath="sample.py",
                search_text="return a * b",
                replace_text="result = a * b\n    return result",
            )
        ]

        results = apply_blocks_to_disk(test_blocks, root=scratch_dir)
        print("Disk Patch Test 1 (Success):", "PASSED" if results[0][1] else "FAILED")
        print(f"  -> File content on disk:\n{test_file.read_text()}")

        # 3. Test failed patch safety (disk remains untouched)
        bad_blocks = [
            EditBlock(
                filepath="sample.py",
                search_text="non_existent_code()",
                replace_text="do_something()",
            )
        ]
        results_bad = apply_blocks_to_disk(bad_blocks, root=scratch_dir)
        print("Disk Patch Test 2 (Safety Check):", "PASSED" if not results_bad[0][1] else "FAILED")

    finally:
        # Cleanup scratch folder
        shutil.rmtree(scratch_dir, ignore_errors=True)