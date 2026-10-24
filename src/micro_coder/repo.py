from pathlib import Path
import git

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
if __name__ == "__main__":
    root = find_git_root()
    print(f"Git Root detected: {root}")
    if root:
        status = get_repo_status(root)
        print("Repository Status:")
        print(f"  - Untracked files : {len(status['untracked'])}")
        print(f"  - Modified files  : {len(status['modified'])}")
        print(f"  - Staged files    : {len(status['staged'])}")

        