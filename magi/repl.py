import asyncio

from rich.console import Console
from rich.live import Live

from magi.core import (
    DEFAULT_MODELS,
    Deliberation,
    PersonaResponse,
    Rebuttal,
    Verdict,
    iterative_deliberate,
    synthesize,
)
from magi.personas import PERSONAS
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
    """Drive iterative deliberation, rendering each round's status + panels live."""
    initial_votes: dict = {}
    current_round = 1
    round_rebuttals: dict[int, dict] = {}
    previous_verdicts: dict[str, Verdict] = {}
    final_outcome = "incomplete"
    final_positions: dict = {}

    # Per-round Live contexts. We can't keep one Live across the whole
    # deliberation because we want to render full panels between rounds.
    vote_statuses = {name: f"voting  [{models[name]}]" for name in PERSONAS}
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
                    # Live already started for round 1; nothing more to do.
                    continue

                # Round N≥2: previous round's Live is closed, render that round's panels, open a new Live for this round.
                if live is not None:
                    live.__exit__(None, None, None)
                    live = None

                if in_round_one:
                    console.print()
                    render_initial_votes(initial_votes, console)
                    console.print()
                    # Populate previous_verdicts with round-1 initial votes so that
                    # round 2 panels can show "(changed from X)" or "(held)".
                    for name, response in initial_votes.items():
                        if isinstance(response, PersonaResponse):
                            previous_verdicts[name] = response.verdict
                    in_round_one = False
                else:
                    console.print()
                    render_debate_round(debate_round_num, round_rebuttals[debate_round_num], previous_verdicts, console)
                    console.print()
                    # Update previous_verdicts to the round we just rendered, so
                    # the NEXT round's render can compare against it.
                    for name, rebuttal in round_rebuttals[debate_round_num].items():
                        if isinstance(rebuttal, Rebuttal):
                            previous_verdicts[name] = rebuttal.final_verdict

                debate_round_num = round_num
                round_rebuttals[round_num] = {}
                debate_statuses = {name: f"debating  [{models[name]}]" for name in initial_votes if isinstance(initial_votes[name], PersonaResponse)}
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
                        # First debate round — compare against initial vote
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

    # After the loop ends, render whatever round we were on.
    if in_round_one:
        console.print()
        render_initial_votes(initial_votes, console)
    else:
        console.print()
        # previous_verdicts may not yet reflect the very last round; rebuild from round_rebuttals chain.
        # Safer: pass an empty previous_verdicts so all show as "held" or comparison happens up the stack.
        # Compute the comparison verdicts as the "before" state of THIS round, which is the verdicts AFTER the previous round.
        # We've been updating previous_verdicts at each round_start transition, so it should already reflect the
        # round before debate_round_num — exactly right.
        render_debate_round(debate_round_num, round_rebuttals[debate_round_num], previous_verdicts, console)

    render_synthesis(synthesize(final_positions, outcome=final_outcome), final_outcome, console)


async def run_oneshot(question: str, models: dict[str, str]) -> None:
    console = Console()
    deliberation = Deliberation()
    deliberation.add_user_message(question)
    await run_full_deliberation(deliberation, models, console)
