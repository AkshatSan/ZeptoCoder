import sys
from rich.console import Console
from rich.table import Table

from micro_coder.llm import stream_chat
from micro_coder.context import ContextManager
from micro_coder.prompts import SYSTEM_PROMPT
from micro_coder.parser import parse_edit_blocks
from micro_coder.patcher import apply_blocks_to_disk
from micro_coder.terminal import TerminalSession
from micro_coder.repo import auto_commit, undo_last_commit, display_diff

console = Console()


def display_tokens(ctx: ContextManager, messages: list[dict]):
    """Renders a clean token consumption table using Rich."""
    breakdown = ctx.get_tokens_breakdown(messages)
    table = Table(title="Token Usage Breakdown", show_header=True, header_style="bold cyan")
    table.add_column("Context Item", style="dim")
    table.add_column("Tokens", justify="right")

    for path, count in breakdown["files"].items():
        table.add_row(f"File: {path}", str(count))

    table.add_section()
    table.add_row("Total Files in Context", f"[bold]{breakdown['files_total']}[/bold]")
    table.add_row("Chat History", f"[bold]{breakdown['chat_history']}[/bold]")
    table.add_row("Grand Total", f"[bold green]{breakdown['total']}[/bold green]")

    console.print(table)


def main():
    ctx = ContextManager()
    console.print("[bold green]micro-coder[/bold green] [dim](v0.1.0)[/dim] - Ready.")
    console.print(f"[dim]Project Root: {ctx.root}[/dim]")
    console.print("[dim]Commands: /add, /drop, /tokens, /diff, /undo, /clear, /exit, /help[/dim]\n")

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

            # None indicates user pressed Ctrl+C to cancel current line
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
                console.print("[yellow]Chat history cleared (active files kept in context).[/yellow]")
                continue

            elif user_input.lower() == "/help":
                console.print("[bold cyan]Available Commands:[/bold cyan]")
                console.print("  [bold]/add <path>[/bold]   - Add a file to active context (with tab-completion)")
                console.print("  [bold]/drop <path>[/bold]  - Remove a file from context (shows active files)")
                console.print("  [bold]/tokens[/bold]       - View token budget breakdown")
                console.print("  [bold]/diff[/bold]         - View colorized git diff (or /diff commit)")
                console.print("  [bold]/undo[/bold]         - Roll back the last AI commit and restore files")
                console.print("  [bold]/clear[/bold]        - Reset conversation memory")
                console.print("  [bold]/exit[/bold]         - Exit the assistant")
                continue

            # 2. Record User Message
            chat_history.append({"role": "user", "content": user_input})

            # 3. Dynamic Context Assembly
            payload = [{"role": "system", "content": SYSTEM_PROMPT}]

            # Inject active file contents into context
            file_context = ctx.format_prompt_context()
            if file_context:
                payload.append({"role": "system", "content": file_context})

            # Append conversational history
            payload.extend(chat_history)

            # 4. Stream Assistant Response
            console.print("[bold magenta]assistant > [/bold magenta]", end="")
            full_response = []

            for token in stream_chat(messages=payload):
                print(token, end="", flush=True)
                full_response.append(token)

            print("\n")  # Newline after stream finishes
            response_text = "".join(full_response)

            # Save assistant response to conversation history
            chat_history.append({"role": "assistant", "content": response_text})

            # 5. Intercept and Apply Edits to Disk
            blocks = parse_edit_blocks(response_text)
            if blocks:
                console.print(f"[bold cyan]Detected {len(blocks)} edit block(s). Applying to disk...[/bold cyan]")
                results = apply_blocks_to_disk(blocks, root=ctx.root)
                successful_files = []

                for path, success, msg in results:
                    if success:
                        console.print(f"  [bold green]✓[/bold green] {path}: {msg}")
                        successful_files.append(path)
                    else:
                        console.print(f"  [bold red]✗[/bold red] {path}: {msg}")

                # 6. Auto-Commit Clean Modifications to Git
                if successful_files:
                    console.print("[dim]Generating commit message and auto-committing...[/dim]")
                    committed, commit_sha, commit_msg = auto_commit(
                        root=ctx.root,
                        files=successful_files,
                    )
                    if committed:
                        console.print(
                            f"  [bold green]Commit {commit_sha}:[/bold green] [dim]{commit_msg}[/dim]"
                        )
                    else:
                        console.print(f"  [dim yellow]Commit skipped: {commit_msg}[/dim yellow]")

        except EOFError:
            console.print("\n[yellow]Goodbye![/yellow]")
            break
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}\n")


if __name__ == "__main__":
    main()

    main()