import re
from pathlib import Path
from typing import TYPE_CHECKING
import git

if TYPE_CHECKING:
    from rich.console import Console


def find_git_root(start_path: str | Path = ".") -> Path | None:
    """
    Finds the root directory of the Git repository by searching upwards
    from start_path. Returns None if not inside a Git repo.
    """
    try:
        repo = git.Repo(start_path, search_parent_directories=True)
        return Path(repo.working_tree_dir).resolve()
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return None


def get_repo_status(repo_path: str | Path | None = None) -> dict[str, list[str]]:
    """
    Returns a dictionary of modified, untracked, and staged files relative to repo root.
    Safely handles fresh repositories without any commits.
    """
    root = find_git_root(repo_path or ".")
    if not root:
        return {"untracked": [], "modified": [], "staged": []}
    repo = git.Repo(root)
    untracked = list(repo.untracked_files)
    # Unstaged modifications in the working tree
    modified = [item.a_path for item in repo.index.diff(None)]
    # Staged changes (checked safely against unborn HEAD)
    if repo.head.is_valid():
        staged = [item.a_path for item in repo.index.diff("HEAD")]
    else:
        staged = [entry[0] for entry in repo.index.entries.keys()]
    return {
        "untracked": sorted(untracked),
        "modified": sorted(modified),
        "staged": sorted(staged),
    }


def clean_commit_message(raw_msg: str) -> str:
    """
    Cleans and standardizes raw LLM output into a single-line conventional commit message.
    Strips markdown code fences, quotation marks, and conversational introductory phrases.
    """
    # Remove markdown code fences if present
    cleaned = re.sub(r"```[a-zA-Z]*", "", raw_msg).replace("```", "").strip()

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""

    # Look for a conventional commit signature: type(scope): description
    pattern = re.compile(
        r"^(feat|fix|refactor|docs|test|style|chore)(\([^\)]+\))?:\s*.+",
        re.IGNORECASE,
    )
    for line in lines:
        match = pattern.search(line)
        if match:
            candidate = line[match.start() :].strip(" '\"`")
            return candidate

    # Fallback to the first non-empty line
    return lines[0].strip(" '\"`")


def generate_commit_message(diff_text: str, model: str | None = None) -> str:
    """
    Invokes the LLM to analyze the staged git diff and generate a semantic,
    single-line Conventional Commit message (e.g. feat: ..., fix: ...).
    """
    if not diff_text.strip():
        return "chore: minor repository updates"

    # Limit diff size to ~8,000 characters to stay well within token budget and latency limits
    truncated_diff = diff_text[:8000] if len(diff_text) > 8000 else diff_text

    prompt = f"""You are an expert Git commit generator.
Analyze the following git diff and generate a concise, single-line Conventional Commit message.

Format: <type>(<scope>): <summary>
Types: feat, fix, refactor, docs, test, style, chore.

Rules:
1. Exactly ONE single line under 72 characters.
2. Lowercase summary, imperative mood, no period at the end.
3. Output ONLY the commit message itself. Do NOT include markdown ticks, quotes, or conversational explanations.

Git diff:
{truncated_diff}
"""
    messages = [
        {"role": "system", "content": "You are an automated Git commit message generator."},
        {"role": "user", "content": prompt},
    ]

    try:
        from micro_coder.llm import stream_chat

        raw_response = "".join(stream_chat(messages=messages, model=model)).strip()
        cleaned = clean_commit_message(raw_response)
        return cleaned or "chore: apply code changes"
    except Exception:
        # Safe fallback if API call fails or times out
        return "chore: apply AI code edits"


def auto_commit(
    root: Path | None = None,
    files: list[str] | None = None,
    model: str | None = None,
) -> tuple[bool, str, str]:
    """
    Automatically stages modified files, generates a conventional commit
    message using the LLM, and creates a commit.

    Appends '[micro-coder auto-commit]' to the commit body so /undo can
    safely identify and roll back tool-generated commits.

    Returns:
        (success: bool, short_sha: str, commit_message: str)
    """
    repo_root = root or find_git_root()
    if not repo_root:
        return False, "", "Not inside a git repository."

    repo = git.Repo(repo_root)

    # 1. Stage the files
    if files:
        # Filter for files that exist on disk
        target_files = [f for f in files if (repo_root / f).exists()]
        if not target_files:
            return False, "", "No target files found to commit."
        repo.git.add(target_files)
    else:
        status = get_repo_status(repo_root)
        changed = status["modified"] + status["untracked"]
        if not changed:
            return False, "", "No modified or untracked changes to commit."
        repo.git.add(changed)

    # 2. Extract staged diff for the LLM
    staged_diff = repo.git.diff("--cached")
    if not staged_diff.strip():
        return False, "", "Staged git diff is empty."

    # 3. Generate the commit message
    commit_msg = generate_commit_message(staged_diff, model=model)

    # Tag commit body with signature for safe rollback
    full_commit_body = f"{commit_msg}\n\n[micro-coder auto-commit]"

    # 4. Commit to Git
    try:
        new_commit = repo.index.commit(full_commit_body)
        short_sha = new_commit.hexsha[:7]
        return True, short_sha, commit_msg
    except Exception as e:
        # Unstage changes to avoid dirty staged index on failure
        repo.git.reset()
        return False, "", f"Commit failed: {e}"


def get_last_commit_info(root: Path | None = None) -> dict[str, str | bool] | None:
    """
    Retrieves metadata about the most recent commit on HEAD.
    Returns None if repository has no commits yet.
    """
    repo_root = root or find_git_root()
    if not repo_root:
        return None
    repo = git.Repo(repo_root)
    if not repo.head.is_valid():
        return None

    head = repo.head.commit
    is_ai = "[micro-coder auto-commit]" in (head.message or "")
    title = (head.message or "").splitlines()[0] if head.message else ""

    return {
        "sha": head.hexsha[:7],
        "message": title,
        "is_ai": is_ai,
        "full_message": head.message or "",
    }


def undo_last_commit(root: Path | None = None) -> tuple[bool, str]:
    """
    Safely rolls back the most recent Git commit if it was generated by micro-coder.

    Safety checks:
    1. Inspects commit metadata: only rolls back if '[micro-coder auto-commit]' is present.
    2. Performs 'git reset --hard HEAD~1' to revert both Git history and disk files.

    Returns:
        (success: bool, message: str)
    """
    repo_root = root or find_git_root()
    if not repo_root:
        return False, "Not inside a Git repository."

    last_commit = get_last_commit_info(repo_root)
    if not last_commit:
        return False, "No commits found to undo."

    # Guard: only undo commits made by micro-coder
    if not last_commit["is_ai"]:
        return (
            False,
            f"Safety block: The latest commit '{last_commit['sha']}' "
            f"('{last_commit['message']}') was not created by micro-coder. "
            "Manual developer commits cannot be undone automatically.",
        )

    repo = git.Repo(repo_root)
    try:
        repo.git.reset("--hard", "HEAD~1")
        return (
            True,
            f"Undid commit {last_commit['sha']}: '{last_commit['message']}'. "
            "Repository restored to prior state.",
        )
    except Exception as e:
        return False, f"Failed to reset commit: {e}"


def get_diff(root: Path | None = None, target: str | None = None) -> tuple[str, str]:
    """
    Retrieves a git diff based on target:
    - target == "commit" or "last": Always returns the diff of the latest commit on HEAD.
    - target is None:
        1. Returns uncommitted working tree changes (if any).
        2. Returns staged changes (if any).
        3. Falls back to the latest commit (if working tree is clean).

    Returns:
        (diff_text: str, title: str)
    """
    repo_root = root or find_git_root()
    if not repo_root:
        return "", "Not inside a Git repository."

    repo = git.Repo(repo_root)

    # Force inspection of the last commit if requested
    if target in ("commit", "last", "head"):
        if repo.head.is_valid():
            try:
                if len(repo.head.commit.parents) > 0:
                    commit_diff = repo.git.diff("HEAD~1", "HEAD")
                    title = f"Commit {repo.head.commit.hexsha[:7]}: {repo.head.commit.message.splitlines()[0]}"
                    return commit_diff, title
                else:
                    return repo.git.show("HEAD", "--format=", "--stat", "-p"), f"Initial Commit ({repo.head.commit.hexsha[:7]})"
            except Exception as e:
                return "", f"Could not inspect last commit: {e}"
        return "", "No commits found on HEAD."

    # Default: 1. Uncommitted working tree changes
    unstaged_diff = repo.git.diff()
    if unstaged_diff.strip():
        return unstaged_diff, "Uncommitted Working Tree Changes (use '/diff commit' to view last commit)"

    # 2. Check for staged changes
    staged_diff = repo.git.diff("--cached")
    if staged_diff.strip():
        return staged_diff, "Staged Changes (Ready to Commit)"

    # 3. If working tree is clean, show diff of the last commit
    if repo.head.is_valid():
        try:
            if len(repo.head.commit.parents) > 0:
                last_commit_diff = repo.git.diff("HEAD~1", "HEAD")
                title = f"Last Commit ({repo.head.commit.hexsha[:7]}): {repo.head.commit.message.splitlines()[0]}"
                return last_commit_diff, title
            else:
                initial_diff = repo.git.show("HEAD", "--format=", "--stat", "-p")
                return initial_diff, f"Initial Commit ({repo.head.commit.hexsha[:7]})"
        except Exception as e:
            return "", f"Could not inspect last commit: {e}"

    return "", "Working tree is clean. No diff available."


def display_diff(root: Path | None = None, target: str | None = None, console: "Console | None" = None) -> None:
    """
    Displays the current Git diff in the terminal with Rich syntax coloring.
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax

    out_console = console or Console()
    diff_text, title = get_diff(root, target=target)

    if not diff_text.strip():
        out_console.print(f"[dim]{title}[/dim]")
        return

    syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=True, word_wrap=True)
    out_console.print(Panel(syntax, title=f"[bold cyan]{title}[/bold cyan]", border_style="dim"))


if __name__ == "__main__":
    print("=== Testing /undo and /diff in repo.py ===")
    root = find_git_root()
    print(f"Git Root detected: {root}")

    if root:
        # 1. Test /diff display
        print("\nTesting display_diff():")
        display_diff(root)

        # 2. Test /undo safety verification
        print("\nTesting undo_last_commit() safety block on existing HEAD:")
        success, msg = undo_last_commit(root)
        print(f"  -> Result : {'Success' if success else 'Blocked safely'}")
        print(f"  -> Message: {msg}")
        