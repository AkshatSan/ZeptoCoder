import os
from pathlib import Path
import tiktoken
from micro_coder.repo import find_git_root


class ContextManager:
    """
    Manages active files in the chat context, reads their contents safely,
    formats them for the LLM prompt, and calculates token consumption.
    """

    def __init__(self, root: Path | None = None, model: str | None = None):
        self.root = root or find_git_root() or Path.cwd()
        self.active_files: set[Path] = set()
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-6-luna")
        self.tokenizer = self._get_tokenizer(self.model)

    def _get_tokenizer(self, model: str):
        """
        Attempts to load model-specific BPE encoding. Falls back to o200k_base
        for newer or custom models (like gpt-6-luna).
        """
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            # Fallback encoding used by modern OpenAI architectures
            return tiktoken.get_encoding("o200k_base")

    def count_tokens(self, text: str) -> int:
        """
        Returns the exact number of BPE tokens in a string.
        disallowed_special=() ensures code snippets containing special tokens don't throw errors.
        """
        if not text:
            return 0
        return len(self.tokenizer.encode(text, disallowed_special=()))

    def add_file(self, filepath: str | Path) -> tuple[bool, str]:
        """
        Adds a file to the active context.
        Returns (success: bool, message: str).
        """
        raw_path = Path(filepath)
        resolved = (raw_path if raw_path.is_absolute() else (self.root / raw_path)).resolve()
        print(resolved)

        if not resolved.exists():
            return False, f"File not found: {filepath}"
        if not resolved.is_file():
            return False, f"Path is not a regular file: {filepath}"

        try:
            rel_path = resolved.relative_to(self.root)
        except ValueError:
            rel_path = resolved

        if rel_path in self.active_files:
            return False, f"{rel_path} is already in the chat context."

        self.active_files.add(rel_path)
        token_count = self.count_tokens(self.get_file_content(rel_path) or "")
        return True, f"Added {rel_path} ({token_count} tokens) to chat context."

    def drop_file(self, filepath: str | Path) -> tuple[bool, str]:
        """
        Removes a file from the active context.
        Returns (success: bool, message: str).
        """
        raw_path = Path(filepath)
        resolved = (raw_path if raw_path.is_absolute() else (self.root / raw_path)).resolve()

        try:
            rel_path = resolved.relative_to(self.root)
        except ValueError:
            rel_path = resolved

        if rel_path not in self.active_files:
            return False, f"{rel_path} is not in the chat context."

        self.active_files.remove(rel_path)
        return True, f"Removed {rel_path} from chat context."

    def get_file_content(self, rel_path: Path) -> str | None:
        """
        Safely reads file text as UTF-8. Returns None if unreadable or binary.
        """
        full_path = self.root / rel_path
        try:
            return full_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            return None

    def format_prompt_context(self) -> str:
        """
        Formats all active files into a markdown string to inject into the LLM prompt.
        """
        if not self.active_files:
            return ""

        sections = ["# In-Context Source Files:\n"]
        for rel_path in sorted(self.active_files):
            content = self.get_file_content(rel_path)
            if content is None:
                continue

            ext = rel_path.suffix.lstrip(".") or "text"
            sections.append(f"## {rel_path}\n```{ext}\n{content}\n```\n")

        return "\n".join(sections)

    def get_tokens_breakdown(self, messages: list[dict] | None = None) -> dict:
        """
        Calculates token usage for each active file, total active files,
        chat history, and grand total.
        """
        file_breakdown = {}
        files_total = 0

        for rel_path in sorted(self.active_files):
            content = self.get_file_content(rel_path)
            count = self.count_tokens(content or "")
            file_breakdown[str(rel_path)] = count
            files_total += count

        history_total = 0
        if messages:
            for msg in messages:
                # Approximate 4 tokens of formatting overhead per message turn
                history_total += self.count_tokens(msg.get("content", "")) + 4

        return {
            "files": file_breakdown,
            "files_total": files_total,
            "chat_history": history_total,
            "total": files_total + history_total,
        }


if __name__ == "__main__":
    ctx = ContextManager()
    print("Testing ContextManager with Token Counting...")

    # 1. Add repo.py
    success, msg = ctx.add_file("src/micro_coder/repo.py")
    print(f"Add status: {msg}")

    # 2. Get breakdown
    dummy_history = [{"role": "user", "content": "How does repo.py work?"}]
    breakdown = ctx.get_tokens_breakdown(messages=dummy_history)

    print("\nToken Usage Breakdown:")
    for path, count in breakdown["files"].items():
        print(f"  - {path}: {count} tokens")
    print(f"  - Files Total : {breakdown['files_total']} tokens")
    print(f"  - Chat History: {breakdown['chat_history']} tokens")
    print(f"  - Grand Total : {breakdown['total']} tokens")