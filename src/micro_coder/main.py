import sys
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm

from micro_coder.llm import stream_chat
from micro_coder.context import ContextManager
from micro_coder.prompt import SYSTEM_PROMPT, format_self_healing_prompt
from micro_coder.parser import parse_edit_blocks
from micro_coder.patcher import apply_blocks_to_disk
from micro_coder.terminal import TerminalSession
from micro_coder.repo import auto_commit, undo_last_commit, display_diff, revert_files
from micro_coder.linter import lint_files
from micro_coder.tester import run_tests, find_test_files_for

console = Console()


def display_tokens(ctx: ContextManager, messages: list[dict]):
    """Renders a clean token consumption table using Rich."""
    breakdown = ctx.get_tokens_breakdown(messages)
    table = Table(
        title="Token Usage Breakdown", show_header=True, header_style="bold cyan"
    )
    table.add_column("Context Item", style="dim")
    table.add_column("Tokens", justify="right")

    for path, count in breakdown["files"].items():
        table.add_row(f"File: {path}", str(count))

    table.add_section()
    table.add_row("Total Files in Context", f"[bold]{breakdown['files_total']}[/bold]")
    table.add_row("Chat History", f"[bold]{breakdown['chat_history']}[/bold]")
    table.add_row("Grand Total", f"[bold green]{breakdown['total']}[/bold green]")

    console.print(table)


def verify_and_heal(
    successful_files: list[str],
    ctx: ContextManager,
    chat_history: list[dict],
    max_attempts: int = 3,
) -> bool:
    """
    Agentic Feedback Loop:
    1. Validates modified files with fast AST syntax check, Ruff, and Pytest.
    2. If issues exist, formats a self-healing prompt and prompts the LLM to auto-fix.
    3. Re-applies fixes and re-tests up to max_attempts.
    4. Returns True if all checks pass, False if errors remain.
    """
    lint_paths = [ctx.root / f for f in successful_files]
    lint_errors = lint_files(lint_paths)

    test_targets = find_test_files_for(successful_files, root=ctx.root)
    test_result = run_tests(targets=test_targets, root=ctx.root)

    # Fast path: Edits are clean on the very first try
    if not lint_errors and test_result.passed:
        console.print(
            "[bold green]✓ Verification passed: 0 lint errors, tests passing.[/bold green]"
        )
        return True

    # Feedback loop: Iteratively ask the model to self-heal
    for attempt in range(1, max_attempts + 1):
        console.print(
            f"\n[bold yellow]⚠️ Verification issues detected (Self-Healing Attempt {attempt}/{max_attempts}):[/bold yellow]"
        )
        if lint_errors:
            console.print(f"  [red]• {len(lint_errors)} linter/syntax error(s):[/red]")
            for err in lint_errors[:3]:
                console.print(f"    [dim]- {err.format()}[/dim]")
            if len(lint_errors) > 3:
                console.print(f"    [dim]... and {len(lint_errors) - 3} more[/dim]")

        if not test_result.passed:
            console.print(f"  [red]• Test suite failed ({test_result.command})[/red]")

        # Format targeted error-recovery prompt
        healing_prompt = format_self_healing_prompt(
            lint_errors=lint_errors,
            test_result=test_result,
            attempt=attempt,
            max_attempts=max_attempts,
        )

        # Assemble prompt payload
        healing_payload = [{"role": "system", "content": SYSTEM_PROMPT}]
        file_context = ctx.format_prompt_context()
        if file_context:
            healing_payload.append({"role": "system", "content": file_context})
        healing_payload.extend(chat_history)
        healing_payload.append({"role": "user", "content": healing_prompt})

        console.print(
            f"[bold magenta]micro-coder (healing #{attempt}) > [/bold magenta]", end=""
        )
        full_response = []
        for token in stream_chat(messages=healing_payload):
            print(token, end="", flush=True)
            full_response.append(token)
        print("\n")

        healing_text = "".join(full_response)
        chat_history.append({"role": "user", "content": healing_prompt})
        chat_history.append({"role": "assistant", "content": healing_text})

        # Apply corrective edit blocks to disk
        new_blocks = parse_edit_blocks(healing_text)
        if not new_blocks:
            console.print(
                "[yellow]No SEARCH/REPLACE blocks found in healing response.[/yellow]"
            )
            break

        results = apply_blocks_to_disk(new_blocks, root=ctx.root)
        for path, success, msg in results:
            if success:
                console.print(f"  [bold green]✓[/bold green] {path}: {msg}")
                if path not in successful_files:
                    successful_files.append(path)
            else:
                console.print(f"  [bold red]✗[/bold red] {path}: {msg}")

        # Re-run validation
        lint_paths = [ctx.root / f for f in successful_files]
        lint_errors = lint_files(lint_paths)
        test_targets = find_test_files_for(successful_files, root=ctx.root)
        test_result = run_tests(targets=test_targets, root=ctx.root)

        if not lint_errors and test_result.passed:
            console.print(
                f"[bold green]✓ Self-healing succeeded on attempt {attempt}![/bold green]"
            )
            return True

    console.print(
        f"[bold red]✗ Self-healing exhausted ({max_attempts} attempts).[/bold red]"
    )
    return False


def main():
    ctx = ContextManager()
    console.print("[bold green]micro-coder[/bold green] [dim](v0.1.0)[/dim] - Ready.")
    console.print(f"[dim]Project Root: {ctx.root}[/dim]")
    console.print(
        "[dim]Commands: /add, /drop, /tokens, /diff, /undo, /clear, /exit, /help[/dim]\n"
    )

    # Initialize professional prompt_toolkit terminal session with autocompletion & history
    terminal = TerminalSession(
        root=ctx.root,
        get_active_files=lambda: [str(p) for p in ctx.active_files],
    )

    # Chat history stores conversational turns (user & assistant)
    chat_history: list[dict] = []

    while True:
        try:
            user_input = terminal.get_input()

            if user_input is None:
                continue

            if not user_input:
                continue

            # 1. Handle Slash Commands
            if user_input.lower() in ("/exit", "/quit", "exit"):
                console.print("[yellow]Goodbye![/yellow]")
                break

            elif user_input.startswith("/add"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    console.print("[red]Usage: /add <filepath>[/red]")
                else:
                    success, msg = ctx.add_file(parts[1])
                    color = "green" if success else "red"
                    console.print(f"[{color}]{msg}[/{color}]")
                continue

            elif user_input.startswith("/drop"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    console.print("[red]Usage: /drop <filepath>[/red]")
                else:
                    success, msg = ctx.drop_file(parts[1])
                    color = "yellow" if success else "red"
                    console.print(f"[{color}]{msg}[/{color}]")
                continue

            elif user_input.lower() == "/tokens":
                display_tokens(ctx, chat_history)
                continue

            elif user_input.lower().startswith("/diff"):
                parts = user_input.split(maxsplit=1)
                target = parts[1].strip().lower() if len(parts) > 1 else None
                display_diff(root=ctx.root, target=target, console=console)
                continue

            elif user_input.lower() == "/undo":
                success, msg = undo_last_commit(root=ctx.root)
                if success:
                    console.print(f"[bold green]✓ {msg}[/bold green]")
                else:
                    console.print(f"[bold yellow]! {msg}[/bold yellow]")
                continue

            elif user_input.lower() == "/clear":
                chat_history.clear()
                console.print(
                    "[yellow]Chat history cleared (active files kept in context).[/yellow]"
                )
                continue

            elif user_input.lower() == "/help":
                console.print("[bold cyan]Available Commands:[/bold cyan]")
                console.print(
                    "  [bold]/add <path>[/bold]   - Add a file to active context (with tab-completion)"
                )
                console.print(
                    "  [bold]/drop <path>[/bold]  - Remove a file from context (shows active files)"
                )
                console.print(
                    "  [bold]/tokens[/bold]       - View token budget breakdown"
                )
                console.print(
                    "  [bold]/diff[/bold]         - View colorized git diff (or /diff commit)"
                )
                console.print(
                    "  [bold]/undo[/bold]         - Roll back the last AI commit and restore files"
                )
                console.print(
                    "  [bold]/clear[/bold]        - Reset conversation memory"
                )
                console.print("  [bold]/exit[/bold]         - Exit the assistant")
                continue

            # 2. Record User Message
            chat_history.append({"role": "user", "content": user_input})

            # 3. Dynamic Context Assembly
            payload = [{"role": "system", "content": SYSTEM_PROMPT}]

            file_context = ctx.format_prompt_context()
            if file_context:
                payload.append({"role": "system", "content": file_context})

            payload.extend(chat_history)

            # 4. Stream Assistant Response
            console.print("[bold magenta]assistant > [/bold magenta]", end="")
            full_response = []

            for token in stream_chat(messages=payload):
                print(token, end="", flush=True)
                full_response.append(token)

            print("\n")
            response_text = "".join(full_response)

            chat_history.append({"role": "assistant", "content": response_text})

            # 5. Intercept and Apply Edits to Disk
            blocks = parse_edit_blocks(response_text)
            if blocks:
                console.print(
                    f"[bold cyan]Detected {len(blocks)} edit block(s). Applying to disk...[/bold cyan]"
                )
                results = apply_blocks_to_disk(blocks, root=ctx.root)
                successful_files = []

                for path, success, msg in results:
                    if success:
                        console.print(f"  [bold green]✓[/bold green] {path}: {msg}")
                        successful_files.append(path)
                    else:
                        console.print(f"  [bold red]✗[/bold red] {path}: {msg}")

                # 6. Agentic Self-Healing Feedback Loop
                if successful_files:
                    console.print("[dim]Running linter and tests verification...[/dim]")
                    is_clean = verify_and_heal(
                        successful_files=successful_files,
                        ctx=ctx,
                        chat_history=chat_history,
                        max_attempts=3,
                    )

                    # 7. Auto-Commit only if clean
                    if is_clean:
                        console.print(
                            "[dim]Generating commit message and auto-committing...[/dim]"
                        )
                        committed, commit_sha, commit_msg = auto_commit(
                            root=ctx.root,
                            files=successful_files,
                        )
                        if committed:
                            console.print(
                                f"  [bold green]Commit {commit_sha}:[/bold green] [dim]{commit_msg}[/dim]"
                            )
                        else:
                            console.print(
                                f"  [dim yellow]Commit skipped: {commit_msg}[/dim yellow]"
                            )
                    else:
                        console.print(
                            "\n[bold red]Self-healing failed to resolve all issues after 3 attempts.[/bold red]"
                        )
                        should_revert = Confirm.ask(
                            "[bold yellow]Revert modified files to keep repository clean?[/bold yellow]",
                            default=True,
                        )
                        if should_revert:
                            ok, msg = revert_files(
                                files=successful_files, root=ctx.root
                            )
                            if ok:
                                console.print(f"[bold green]✓ {msg}[/bold green]")
                            else:
                                console.print(f"[bold red]✗ {msg}[/bold red]")
                        else:
                            console.print(
                                "[dim]Kept changes on disk for manual debugging.[/dim]"
                            )

        except EOFError:
            console.print("\n[yellow]Goodbye![/yellow]")
            break
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}\n")


if __name__ == "__main__":
    main()
