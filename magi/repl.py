import asyncio

from rich.console import Console
from rich.live import Live

from magi.core import (
    DEFAULT_MODELS,
    Deliberation,
    PersonaResponse,
    Rebuttal,
    _debate_round,
    _vote_round,
    synthesize,
)
from magi.personas import PERSONAS
from magi.render import (
    debate_status_panel,
    print_banner,
    print_help,
    print_models,
    render_debate,
    render_initial_votes,
    render_synthesis,
    vote_status_panel,
)


def _handle_command(
    cmd: str,
    models: dict[str, str],
    deliberation: Deliberation | None,
    console: Console,
) -> tuple[dict, Deliberation | None, bool]:
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
            await run_full_deliberation(deliberation, models, console)
        except KeyboardInterrupt:
            console.print("\n[yellow]deliberation interrupted[/yellow]")


async def run_full_deliberation(
    deliberation: Deliberation, models: dict[str, str], console: Console
) -> None:
    """Drive the two-round deliberation with live status displays for each round."""
    initial_votes: dict = {}
    rebuttals: dict = {}

    # ROUND 1: independent votes, live status panel updates as each lands.
    vote_statuses = {name: f"voting  [{models[name]}]" for name in PERSONAS}
    with Live(vote_status_panel(vote_statuses, initial_votes), console=console, refresh_per_second=8) as live:
        async for name, result in _vote_round(deliberation, models):
            initial_votes[name] = result
            if isinstance(result, Exception):
                vote_statuses[name] = f"failed: {type(result).__name__}"
            else:
                vote_statuses[name] = f"{result.verdict.value}  [{models[name]}]"
            live.update(vote_status_panel(vote_statuses, initial_votes))

    console.print()
    render_initial_votes(initial_votes, console)
    console.print()

    valid_voters = {n: v for n, v in initial_votes.items() if isinstance(v, PersonaResponse)}
    if len(valid_voters) < 2:
        # Not enough for debate — commit what we have and synthesize.
        for name, response in valid_voters.items():
            deliberation.commit_response(name, response)
        render_synthesis(synthesize(initial_votes), console)
        return

    # ROUND 2
    debate_statuses = {name: f"debating  [{models[name]}]" for name in valid_voters}
    with Live(debate_status_panel(debate_statuses, rebuttals), console=console, refresh_per_second=8) as live:
        async for name, payload in _debate_round(deliberation, models, valid_voters):
            rebuttals[name] = payload
            if isinstance(payload, Exception):
                debate_statuses[name] = f"failed: {type(payload).__name__}"
            elif isinstance(payload, Rebuttal):
                arrow = "→" if payload.final_verdict == valid_voters[name].verdict else "⇒"
                debate_statuses[name] = f"{arrow} {payload.final_verdict.value}  [{models[name]}]"
            live.update(debate_status_panel(debate_statuses, rebuttals))

    console.print()
    render_debate(initial_votes, rebuttals, console)

    # Commit FINAL responses (post-debate) to history.
    final_responses: dict[str, PersonaResponse] = {}
    for name in valid_voters:
        rebuttal = rebuttals.get(name)
        initial = valid_voters[name]
        if isinstance(rebuttal, Rebuttal):
            final = PersonaResponse(
                verdict=rebuttal.final_verdict,
                reasoning=initial.reasoning,
                asks_in_return=initial.asks_in_return,
            )
            final_responses[name] = final
            deliberation.commit_response(name, final)
        else:
            final_responses[name] = initial
            deliberation.commit_response(name, initial)

    render_synthesis(synthesize(final_responses), console)


async def run_oneshot(question: str, models: dict[str, str]) -> None:
    console = Console()
    deliberation = Deliberation()
    deliberation.add_user_message(question)
    await run_full_deliberation(deliberation, models, console)
