import asyncio

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from magi.core import (
    DEFAULT_MODELS,
    Deliberation,
    PersonaResponse,
    Rebuttal,
    Verdict,
    iterative_deliberate,
    synthesize,
)
from magi.personas import (
    PERSONAS,
    SPECIALIST_DEFAULT_MODELS,
    SPECIALIST_DESCRIPTIONS,
    SPECIALISTS,
    is_core_member,
)
from magi.render import (
    debate_status_panel,
    print_banner,
    print_help,
    print_models,
    render_debate_round,
    render_initial_votes,
    render_synthesis,
    vote_status_panel,
)


def _print_council_roster(console: Console, models: dict[str, str]) -> None:
    text = Text()
    text.append("CORE\n", style="bold cyan")
    for name in ("MELCHIOR", "BALTHASAR", "CASPER"):
        if name in models:
            text.append(f"  {name:<11} ", style="bold")
            text.append(f"{models[name]}\n", style="dim")

    invited = [n for n in models if not is_core_member(n)]
    if invited:
        text.append("\nINVITED SPECIALISTS\n", style="bold magenta")
        for name in invited:
            desc = SPECIALIST_DESCRIPTIONS.get(name, "")
            text.append(f"  {name:<11} ", style="bold")
            text.append(f"{models[name]}", style="dim")
            if desc:
                text.append(f"  — {desc}", style="dim italic")
            text.append("\n")

    available = [s for s in SPECIALISTS if s not in models]
    if available:
        text.append("\nAVAILABLE TO INVITE\n", style="bold")
        for name in available:
            desc = SPECIALIST_DESCRIPTIONS.get(name, "")
            text.append(f"  /invite {name.lower():<11}", style="cyan")
            text.append(f"  {desc}\n", style="dim italic")

    console.print(Panel(text, title="[bold]council[/bold]", border_style="dim"))


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
    elif head in ("specialists", "council", "roster"):
        _print_council_roster(console, models)
    elif head == "clear":
        console.clear()
        print_banner(console, models)
    elif head in ("new", "n"):
        if deliberation is not None and deliberation.turn > 0:
            console.print(f"[dim]new deliberation (closed prior thread, {deliberation.turn} turn(s))[/dim]")
        else:
            console.print("[dim]new deliberation[/dim]")
        deliberation = None
    elif head == "invite":
        if not arg:
            console.print("[red]usage: /invite <specialist>[/red]  [dim](e.g. /invite banker)[/dim]")
            console.print(f"  [dim]available: {', '.join(s.lower() for s in SPECIALISTS)}[/dim]")
        else:
            specialist = arg.upper()
            if specialist not in SPECIALISTS:
                console.print(f"[red]unknown specialist: {arg}[/red]")
                console.print(f"  [dim]available: {', '.join(s.lower() for s in SPECIALISTS)}[/dim]")
            elif specialist in models:
                console.print(f"[dim]{specialist} is already in the council[/dim]")
            else:
                models[specialist] = SPECIALIST_DEFAULT_MODELS[specialist]
                if deliberation is not None:
                    deliberation.add_member(specialist)
                desc = SPECIALIST_DESCRIPTIONS.get(specialist, "")
                console.print(f"[bold magenta]{specialist}[/bold magenta] joins the council  [dim]({desc})[/dim]")
    elif head == "dismiss":
        if not arg:
            console.print("[red]usage: /dismiss <specialist>[/red]")
        else:
            specialist = arg.upper()
            if is_core_member(specialist):
                console.print(f"[red]cannot dismiss core MAGI member {specialist}[/red]")
            elif specialist not in models:
                console.print(f"[dim]{specialist} is not in the council[/dim]")
            else:
                models.pop(specialist)
                if deliberation is not None:
                    deliberation.remove_member(specialist)
                console.print(f"[dim]{specialist} leaves the council[/dim]")
    elif head in PERSONAS_LOWER:
        canonical = head.upper()
        if not arg:
            console.print(f"[red]usage: /{head} <model>[/red]  [dim](e.g. /{head} qwen3:8b)[/dim]")
        else:
            models[canonical] = arg
            console.print(f"[dim]{canonical} → [bold]{arg}[/bold][/dim]")
    elif head in SPECIALISTS_LOWER and head in [s.lower() for s in models if not is_core_member(s)]:
        # /banker <model> works only if banker is invited
        canonical = head.upper()
        if not arg:
            console.print(f"[red]usage: /{head} <model>[/red]")
        else:
            models[canonical] = arg
            console.print(f"[dim]{canonical} → [bold]{arg}[/bold][/dim]")
    elif head == "reset":
        models.clear()
        models.update(DEFAULT_MODELS)
        if deliberation is not None:
            for name in list(deliberation.histories):
                if not is_core_member(name):
                    deliberation.remove_member(name)
        console.print("[dim]models reset; specialists dismissed[/dim]")
        print_models(console, models)
    else:
        console.print(f"[red]unknown command: /{head}[/red]  [dim](try /help)[/dim]")

    return models, deliberation, True


PERSONAS_LOWER = {n.lower() for n in PERSONAS}
SPECIALISTS_LOWER = {n.lower() for n in SPECIALISTS}


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
            deliberation = Deliberation(list(models.keys()))

        deliberation.add_user_message(line)

        try:
            await run_full_deliberation(deliberation, models, console)
        except KeyboardInterrupt:
            console.print("\n[yellow]deliberation interrupted[/yellow]")


async def run_full_deliberation(
    deliberation: Deliberation, models: dict[str, str], console: Console
) -> None:
    """Drive iterative deliberation, rendering each round's status + panels live."""
    initial_votes: dict = {}
    round_rebuttals: dict[int, dict] = {}
    previous_verdicts: dict[str, Verdict] = {}
    final_outcome = "incomplete"
    final_positions: dict = {}

    vote_statuses = {name: f"voting  [{models[name]}]" for name in models}
    live: Live | None = Live(vote_status_panel(vote_statuses, initial_votes), console=console, refresh_per_second=8)
    live.__enter__()

    debate_statuses: dict[str, str] = {}
    debate_round_num = 0
    in_round_one = True

    try:
        async for event in iterative_deliberate(deliberation, models):
            kind = event[0]

            if kind == "round_start":
                round_num = event[1]
                if round_num == 1:
                    continue

                if live is not None:
                    live.__exit__(None, None, None)
                    live = None

                if in_round_one:
                    console.print()
                    render_initial_votes(initial_votes, console)
                    console.print()
                    for name, response in initial_votes.items():
                        if isinstance(response, PersonaResponse):
                            previous_verdicts[name] = response.verdict
                    in_round_one = False
                else:
                    console.print()
                    render_debate_round(debate_round_num, round_rebuttals[debate_round_num], previous_verdicts, console)
                    console.print()
                    for name, rebuttal in round_rebuttals[debate_round_num].items():
                        if isinstance(rebuttal, Rebuttal):
                            previous_verdicts[name] = rebuttal.final_verdict

                debate_round_num = round_num
                round_rebuttals[round_num] = {}
                debate_statuses = {
                    name: f"debating  [{models[name]}]"
                    for name in initial_votes
                    if isinstance(initial_votes[name], PersonaResponse)
                }
                live = Live(
                    debate_status_panel(debate_statuses, round_rebuttals[round_num], round_num),
                    console=console,
                    refresh_per_second=8,
                )
                live.__enter__()

            elif kind == "vote":
                _, name, payload = event
                initial_votes[name] = payload
                if isinstance(payload, Exception):
                    vote_statuses[name] = f"failed: {type(payload).__name__}"
                else:
                    vote_statuses[name] = f"{payload.verdict.value}  [{models[name]}]"
                if live is not None:
                    live.update(vote_status_panel(vote_statuses, initial_votes))

            elif kind == "rebuttal":
                _, name, payload = event
                round_rebuttals[debate_round_num][name] = payload
                if isinstance(payload, Exception):
                    debate_statuses[name] = f"failed: {type(payload).__name__}"
                elif isinstance(payload, Rebuttal):
                    prev = previous_verdicts.get(name)
                    if prev is None:
                        initial = initial_votes.get(name)
                        if isinstance(initial, PersonaResponse):
                            prev = initial.verdict
                    arrow = "→" if prev == payload.final_verdict else "⇒"
                    debate_statuses[name] = f"{arrow} {payload.final_verdict.value}  [{models[name]}]"
                if live is not None:
                    live.update(debate_status_panel(debate_statuses, round_rebuttals[debate_round_num], debate_round_num))

            elif kind == "done":
                _, outcome, positions = event
                final_outcome = outcome
                final_positions = positions
    finally:
        if live is not None:
            live.__exit__(None, None, None)
            live = None

    if in_round_one:
        console.print()
        render_initial_votes(initial_votes, console)
    else:
        console.print()
        render_debate_round(debate_round_num, round_rebuttals[debate_round_num], previous_verdicts, console)

    render_synthesis(synthesize(final_positions, outcome=final_outcome), final_outcome, console)


async def run_oneshot(question: str, models: dict[str, str]) -> None:
    console = Console()
    deliberation = Deliberation(list(models.keys()))
    deliberation.add_user_message(question)
    await run_full_deliberation(deliberation, models, console)
