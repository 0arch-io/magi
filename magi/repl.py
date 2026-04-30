import asyncio

from rich.console import Console
from rich.live import Live

from magi.core import consult_all_streaming, synthesize
from magi.personas import PERSONAS
from magi.render import (
    print_banner,
    print_help,
    render_results,
    status_panel,
)


SONNET = "claude-sonnet-4-6"
OPUS = "claude-opus-4-7"


async def consult_with_live_status(question: str, model: str, console: Console) -> None:
    statuses = {name: "deliberating..." for name in PERSONAS}
    results: dict = {}

    with Live(status_panel(statuses, results), console=console, refresh_per_second=8) as live:
        async for name, result in consult_all_streaming(question, model):
            results[name] = result
            if isinstance(result, Exception):
                statuses[name] = f"failed: {type(result).__name__}"
            else:
                statuses[name] = f"{result.verdict.value}"
            live.update(status_panel(statuses, results))

    console.print()
    render_results(results, synthesize(results), console)


def _handle_command(cmd: str, model: str, console: Console) -> tuple[str, bool]:
    """Returns (new_model, should_continue)."""
    cmd = cmd.lower().strip()
    if cmd in ("exit", "quit", "q"):
        console.print("[dim]MAGI offline.[/dim]")
        return model, False
    if cmd == "help":
        print_help(console)
    elif cmd == "opus":
        model = OPUS
        console.print(f"[dim]model → [bold]{model}[/bold][/dim]")
    elif cmd == "sonnet":
        model = SONNET
        console.print(f"[dim]model → [bold]{model}[/bold][/dim]")
    elif cmd == "model":
        console.print(f"[dim]model: [bold]{model}[/bold][/dim]")
    elif cmd == "clear":
        console.clear()
        print_banner(console, model)
    else:
        console.print(f"[red]unknown command: /{cmd}[/red]  [dim](try /help)[/dim]")
    return model, True


async def run_repl(initial_model: str) -> None:
    console = Console()
    console.clear()
    print_banner(console, initial_model)
    model = initial_model

    while True:
        try:
            line = console.input("[bold red]❯[/bold red] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]MAGI offline.[/dim]")
            return

        if not line:
            continue

        if line.startswith("/"):
            model, cont = _handle_command(line[1:], model, console)
            if not cont:
                return
            continue

        try:
            await consult_with_live_status(line, model, console)
        except KeyboardInterrupt:
            console.print("\n[yellow]deliberation interrupted[/yellow]")


async def run_oneshot(question: str, model: str) -> None:
    console = Console()
    await consult_with_live_status(question, model, console)
