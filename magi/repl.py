import asyncio

from rich.console import Console
from rich.live import Live

from magi.core import (
    DEFAULT_MODELS,
    Deliberation,
    consult_all_streaming,
    synthesize,
)
from magi.personas import PERSONAS
from magi.render import (
    print_banner,
    print_help,
    print_models,
    render_results,
    status_panel,
)


async def consult_with_live_status(
    deliberation: Deliberation, models: dict[str, str], console: Console
) -> None:
    statuses = {name: f"deliberating  [{models[name]}]" for name in PERSONAS}
    results: dict = {}

    with Live(status_panel(statuses, results), console=console, refresh_per_second=8) as live:
        async for name, result in consult_all_streaming(deliberation, models):
            results[name] = result
            if isinstance(result, Exception):
                statuses[name] = f"failed: {type(result).__name__}: {result}"
            else:
                statuses[name] = f"{result.verdict.value}  [{models[name]}]"
            live.update(status_panel(statuses, results))

    console.print()
    render_results(results, synthesize(results), console)


def _handle_command(
    cmd: str,
    models: dict[str, str],
    deliberation: Deliberation | None,
    console: Console,
) -> tuple[dict, Deliberation | None, bool]:
    """Returns (new_models, new_deliberation, should_continue)."""
    parts = cmd.lower().strip().split(maxsplit=1)
    head = parts[0] if parts else ""
    arg = parts[1] if len(parts) > 1 else ""

    if head in ("exit", "quit", "q"):
        console.print("[dim]MAGI offline.[/dim]")
        return models, deliberation, False

    if head == "help":
        print_help(console)
    elif head == "models":
        print_models(console, models)
    elif head == "clear":
        console.clear()
        print_banner(console, models)
    elif head in ("new", "n"):
        if deliberation is not None and deliberation.turn > 0:
            console.print(f"[dim]new deliberation (closed prior thread, {deliberation.turn} turn(s))[/dim]")
        else:
            console.print("[dim]new deliberation[/dim]")
        deliberation = None
    elif head in ("melchior", "balthasar", "casper"):
        if not arg:
            console.print(f"[red]usage: /{head} <model>[/red]  [dim](e.g. /{head} qwen3:8b)[/dim]")
        else:
            models[head.upper()] = arg
            console.print(f"[dim]{head.upper()} → [bold]{arg}[/bold][/dim]")
    elif head == "reset":
        models = dict(DEFAULT_MODELS)
        console.print("[dim]models reset to defaults[/dim]")
        print_models(console, models)
    else:
        console.print(f"[red]unknown command: /{head}[/red]  [dim](try /help)[/dim]")

    return models, deliberation, True


async def run_repl(initial_models: dict[str, str]) -> None:
    console = Console()
    console.clear()
    print_banner(console, initial_models)
    models = dict(initial_models)
    deliberation: Deliberation | None = None

    while True:
        # Visual cue: ❯ for new question, ❯❯ for follow-up in active deliberation.
        prompt = "[bold red]❯❯[/bold red] " if deliberation is not None else "[bold red]❯[/bold red] "
        try:
            line = console.input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]MAGI offline.[/dim]")
            return

        if not line:
            continue

        if line.startswith("/"):
            models, deliberation, cont = _handle_command(line[1:], models, deliberation, console)
            if not cont:
                return
            continue

        if deliberation is None:
            deliberation = Deliberation()

        deliberation.add_user_message(line)

        try:
            await consult_with_live_status(deliberation, models, console)
        except KeyboardInterrupt:
            console.print("\n[yellow]deliberation interrupted[/yellow]")


async def run_oneshot(question: str, models: dict[str, str]) -> None:
    console = Console()
    deliberation = Deliberation()
    deliberation.add_user_message(question)
    await consult_with_live_status(deliberation, models, console)
