from pathlib import Path
from typing import Callable, Iterable
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from micro_coder.completer import MicroCoderCompleter
from micro_coder.repo import find_git_root

# Sleek dark-mode styling for the completion popup menu and scrollbars
PROMPT_STYLE = Style.from_dict(
    {
        "completion-menu.completion": "bg:#252526 #cccccc",
        "completion-menu.completion.current": "bg:#094771 #ffffff bold",
        "completion-menu.meta": "bg:#252526 #858585 italic",
        "completion-menu.meta.current": "bg:#094771 #cccccc",
        "scrollbar.background": "bg:#1e1e1e",
        "scrollbar.button": "bg:#424242",
    }
)


def create_key_bindings() -> KeyBindings:
    """
    Configures keyboard shortcuts for the interactive prompt:
    - Enter: Submits the line immediately.
    - Escape + Enter (or Alt + Enter): Inserts a newline for multiline prompts.
    - Ctrl + J: Inserts a newline.
    """
    kb = KeyBindings()

    @kb.add("escape", "enter")
    def _insert_newline_esc(event):
        event.current_buffer.insert_text("\n")

    @kb.add("c-j")
    def _insert_newline_ctrl(event):
        event.current_buffer.insert_text("\n")

    return kb


class TerminalSession:
    """
    Manages the interactive terminal prompt using prompt_toolkit.

    Features:
    - Persistent command history saved across restarts to ~/.micro_coder_history.
    - Dynamic tab-completion via MicroCoderCompleter.
    - Single-key submit (Enter) with Alt+Enter / Esc+Enter for multiline inputs.
    - Graceful keyboard interrupt (Ctrl+C) and EOF (Ctrl+D) handling.
    """

    def __init__(
        self,
        root: Path | None = None,
        get_active_files: Callable[[], Iterable[str]] | None = None,
        history_file: Path | None = None,
    ):
        self.root = root or find_git_root() or Path.cwd()
        self.history_file = history_file or (Path.home() / ".micro_coder_history")
        self.completer = MicroCoderCompleter(
            root=self.root,
            get_active_files=get_active_files,
        )
        self.session: PromptSession = PromptSession(
            completer=self.completer,
            complete_while_typing=True,
            history=FileHistory(str(self.history_file)),
            key_bindings=create_key_bindings(),
            style=PROMPT_STYLE,
        )

    def get_input(self) -> str | None:
        """
        Prompts the user for input.
        Returns the stripped string, or None if the user pressed Ctrl+C.
        Raises EOFError when the user signals EOF (Ctrl+D).
        """
        try:
            text = self.session.prompt(
                HTML("<b><ansibrightblue>you &gt; </ansibrightblue></b>")
            )
            return text.strip()
        except KeyboardInterrupt:
            return None


if __name__ == "__main__":
    print("=== Testing TerminalSession ===")
    print(f"Persistent History File: {Path.home() / '.micro_coder_history'}")
    print("\nInteractive features to test:")
    print("  1. Up/Down Arrow Keys: Navigates past command history.")
    print("  2. Type '/': Autocomplete menu appears automatically.")
    print("  3. Escape + Enter (or Alt + Enter): Inserts a newline for multiline prompts.")
    print("  4. Enter: Submits the message.")
    print("  5. Ctrl + C: Cancels the current line cleanly.")
    print("  6. Type '/exit' or press Ctrl + D to quit.\n")

    mock_active = ["src/micro_coder/main.py", "src/micro_coder/context.py"]
    term = TerminalSession(
        root=find_git_root() or Path.cwd(),
        get_active_files=lambda: mock_active,
    )

    while True:
        try:
            user_msg = term.get_input()
            if user_msg is None:
                print("^C (Interrupted - type /exit to quit)")
                continue
            if not user_msg:
                continue
            if user_msg.lower() in ("/exit", "/quit"):
                print("Goodbye!")
                break
            print(f"Received ({len(user_msg)} chars):\n{user_msg}\n")
        except EOFError:
            print("\nGoodbye! (EOF)")
            break

