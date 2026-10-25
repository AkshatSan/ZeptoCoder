from pathlib import Path
from typing import Callable, Iterable
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from micro_coder.repo import find_git_root

# Dictionary of supported slash commands and their user-facing descriptions
COMMANDS: dict[str, str] = {
    "/add": "Add a file to active context",
    "/drop": "Remove a file from active context",
    "/tokens": "View token budget breakdown",
    "/diff": "View git diff of modified files",
    "/undo": "Revert the last AI-generated commit",
    "/clear": "Reset conversation memory",
    "/help": "Show available commands",
    "/exit": "Exit the assistant",
}


def get_repo_files(root: Path) -> list[str]:
    """
    Returns a sorted list of relative file paths in the repository.
    Uses Git (if available) to respect .gitignore, or falls back to filesystem traversal.
    """
    try:
        import git

        repo = git.Repo(root)
        files: set[str] = set()

        # Tracked files in the repository
        if repo.head.is_valid():
            files.update(repo.git.ls_files().splitlines())
        else:
            # Handle brand new repos with staged files but no commits yet
            files.update(entry[0] for entry in repo.index.entries.keys())

        # Untracked files that are not ignored by .gitignore
        files.update(repo.untracked_files)

        # Filter for actual regular files that exist on disk
        return sorted([f for f in files if (root / f).is_file()])
    except Exception:
        # Fallback traversal ignoring common build/dependency artifacts
        ignored = {
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            "node_modules",
            ".ruff_cache",
            "dist",
            "build",
        }
        results: list[str] = []
        for p in root.rglob("*"):
            if p.is_file() and not any(part in ignored or part.startswith(".") for part in p.parts):
                try:
                    results.append(str(p.relative_to(root)))
                except ValueError:
                    pass
        return sorted(results)


class MicroCoderCompleter(Completer):
    """
    Context-sensitive autocompleter for micro-coder REPL.

    Behavior:
    1. Typing '/' -> suggests slash commands with descriptive metadata.
    2. Typing '/add ' -> suggests project files (Git-tracked & untracked, respecting .gitignore).
    3. Typing '/drop ' -> suggests only files currently in the active chat context.
    """

    def __init__(
        self,
        root: Path | None = None,
        get_active_files: Callable[[], Iterable[str]] | None = None,
    ):
        self.root = root or find_git_root() or Path.cwd()
        self.get_active_files = get_active_files

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor
        stripped = text.lstrip()

        # Only provide completions when the user starts with a slash command
        if not stripped.startswith("/"):
            return

        # Case 1: Typing the slash command name itself (e.g., "/", "/ad", "/to")
        if " " not in stripped:
            for cmd, desc in COMMANDS.items():
                if cmd.startswith(stripped.lower()):
                    # Automatically append a trailing space for commands requiring arguments
                    insert_text = f"{cmd} " if cmd in ("/add", "/drop") else cmd
                    yield Completion(
                        text=insert_text,
                        start_position=-len(stripped),
                        display=cmd,
                        display_meta=desc,
                    )
            return

        # Case 2: Typing command arguments after a space
        parts = stripped.split(maxsplit=1)
        cmd = parts[0].lower()

        # If user typed "/add " with spaces, arg is what comes after the first space
        arg = parts[1] if len(parts) > 1 else ""
        if stripped.endswith(" ") and len(parts) == 1:
            arg = ""

        lower_arg = arg.lower()

        if cmd == "/add":
            repo_files = get_repo_files(self.root)
            for filepath in repo_files:
                # Matches either from start of path or substring match on filename
                if filepath.lower().startswith(lower_arg) or lower_arg in filepath.lower():
                    yield Completion(
                        text=filepath,
                        start_position=-len(arg),
                        display=filepath,
                        display_meta="file",
                    )

        elif cmd == "/drop":
            active_files = list(self.get_active_files()) if self.get_active_files else []
            for filepath in active_files:
                filepath_str = str(filepath)
                if filepath_str.lower().startswith(lower_arg) or lower_arg in filepath_str.lower():
                    yield Completion(
                        text=filepath_str,
                        start_position=-len(arg),
                        display=filepath_str,
                        display_meta="in context",
                    )


if __name__ == "__main__":
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML

    print("=== Testing MicroCoderCompleter ===")
    print("Simulated active files in context: ['src/micro_coder/main.py', 'src/micro_coder/context.py']")
    print("\nTry testing:")
    print("  1. Type '/' and press Tab to view slash commands.")
    print("  2. Type '/add ' and press Tab (or start typing a filename) to autocomplete files.")
    print("  3. Type '/drop ' and press Tab to see only active files.")
    print("Press Ctrl+C or type /exit to finish the test.\n")

    mock_active = ["src/micro_coder/main.py", "src/micro_coder/context.py"]
    completer = MicroCoderCompleter(
        root=find_git_root() or Path.cwd(),
        get_active_files=lambda: mock_active,
    )
    session = PromptSession(completer=completer)

    while True:
        try:
            line = session.prompt(HTML("<ansibrightgreen>test &gt; </ansibrightgreen>"))
            if line.strip() in ("/exit", "/quit"):
                print("Exiting test.")
                break
            print(f"Accepted input: {line}")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting test.")
            break

