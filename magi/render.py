from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from magi.core import PersonaResponse, Rebuttal, Verdict


VERDICT_COLOR = {
    Verdict.ACCEPT: "green",
    Verdict.REJECT: "red",
    Verdict.CONDITIONAL: "yellow",
}


BANNER = """[bold red]
    ███╗   ███╗ █████╗  ██████╗ ██╗
    ████╗ ████║██╔══██╗██╔════╝ ██║
    ██╔████╔██║███████║██║  ███╗██║
    ██║╚██╔╝██║██╔══██║██║   ██║██║
    ██║ ╚═╝ ██║██║  ██║╚██████╔╝██║
    ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝[/bold red]

    [dim]MELCHIOR  ·  BALTHASAR  ·  CASPER[/dim]
    [dim]the council convenes — bring your question[/dim]
"""


HELP_TEXT = """[bold]commands[/bold]
  [cyan]/help[/cyan]                  show this help
  [cyan]/new[/cyan]                   start a fresh deliberation
  [cyan]/models[/cyan]                show current model assignments
  [cyan]/specialists[/cyan]           list specialists you can invite
  [cyan]/invite[/cyan] <name>         invite a specialist (banker, therapist, lawyer, coach, doctor)
  [cyan]/dismiss[/cyan] <name>        remove a specialist from the council
  [cyan]/melchior[/cyan] <model>      assign a different model to a member
  [cyan]/reset[/cyan]                 reset to defaults; dismiss all specialists
  [cyan]/journal[/cyan]               show your past deliberations
  [cyan]/outcome[/cyan] <id> <text>   record what you actually did/didn't do
  [cyan]/clear[/cyan]                 clear the screen
  [cyan]/exit[/cyan]                  exit the MAGI

[bold]how this works[/bold]
  [red]❯[/red]   bring a question — the council deliberates
  [red]❯❯[/red]  argue back — they reconsider with new info
  [cyan]/new[/cyan]  drop the thread, start fresh

[bold]deliberation rounds[/bold]
  1. each member votes independently from their own lens
  2+ they read each other's positions and argue; verdicts can shift
     keeps going until consensus or up to 4 rounds total

[bold]outcomes[/bold]
  [green]CONSENSUS[/green]   all three agree — clean answer
  [yellow]DEADLOCK[/yellow]   they could not agree after 4 rounds — your call
"""


def print_banner(console: Console, models: dict[str, str]) -> None:
    console.print(BANNER)
    console.print(
        f"    [dim]MELCHIOR=[bold]{models['MELCHIOR']}[/bold]  "
        f"BALTHASAR=[bold]{models['BALTHASAR']}[/bold]  "
        f"CASPER=[bold]{models['CASPER']}[/bold][/dim]"
    )
    console.print("    [dim]/help for commands[/dim]\n")


def print_models(console: Console, models: dict[str, str]) -> None:
    text = Text()
    for name in ("MELCHIOR", "BALTHASAR", "CASPER"):
        text.append(f"  {name:<10}", style="bold")
        text.append(f"  {models[name]}\n")
    console.print(Panel(text, title="[bold]model assignments[/bold]", border_style="dim"))


def vote_status_panel(statuses: dict[str, str], results: dict) -> Panel:
    text = Text()
    for name in statuses:
        result = results.get(name)
        if result is None:
            mark, color = "·", "yellow"
        elif isinstance(result, Exception):
            mark, color = "✗", "red"
        else:
            mark, color = "✓", VERDICT_COLOR[result.verdict]

        text.append(f"  {mark}  ", style=f"bold {color}")
        text.append(f"{name:<10}  ", style=f"bold {color}")
        text.append(f"{statuses[name]}\n", style="dim")

    return Panel(text, title="[bold cyan]ROUND 1 — INITIAL VOTES[/bold cyan]", border_style="cyan")


def debate_status_panel(statuses: dict[str, str], rebuttals: dict, round_num: int) -> Panel:
    text = Text()
    for name in statuses:
        result = rebuttals.get(name)
        if result is None:
            mark, color = "·", "magenta"
        elif isinstance(result, Exception):
            mark, color = "✗", "red"
        else:
            mark, color = "✓", VERDICT_COLOR[result.final_verdict]

        text.append(f"  {mark}  ", style=f"bold {color}")
        text.append(f"{name:<10}  ", style=f"bold {color}")
        text.append(f"{statuses[name]}\n", style="dim")

    title = f"[bold magenta]ROUND {round_num} — COUNCIL DELIBERATES[/bold magenta]"
    return Panel(text, title=title, border_style="magenta")


def _persona_panel(name: str, result: PersonaResponse | Exception) -> Panel:
    if isinstance(result, Exception):
        body = Text(f"FAILED: {type(result).__name__}: {result}", style="red")
        return Panel(body, title=f"[bold red]{name}[/bold red]", border_style="red")

    color = VERDICT_COLOR[result.verdict]
    body = Text()
    body.append(f"VERDICT: {result.verdict.value}\n\n", style=f"bold {color}")
    body.append(result.reasoning + "\n\n")
    body.append("ASKS YOU: ", style="bold")
    body.append(result.asks_in_return)

    return Panel(body, title=f"[bold {color}]{name}[/bold {color}]", border_style=color)


def _debate_panel(
    name: str,
    previous_verdict: Verdict | None,
    rebuttal: Rebuttal | Exception | None,
    round_num: int,
) -> Panel:
    if isinstance(rebuttal, Exception):
        body = Text(f"DEBATE FAILED: {type(rebuttal).__name__}: {rebuttal}", style="red")
        return Panel(body, title=f"[bold red]{name}[/bold red]", border_style="red")

    if rebuttal is None:
        body = Text("(no debate this round)", style="dim")
        return Panel(body, title=f"[bold]{name}[/bold]", border_style="dim")

    color = VERDICT_COLOR[rebuttal.final_verdict]
    body = Text()
    body.append(rebuttal.response + "\n\n")
    body.append("VERDICT: ", style="bold")
    body.append(rebuttal.final_verdict.value, style=f"bold {color}")
    if previous_verdict is not None and rebuttal.final_verdict != previous_verdict:
        body.append(f"   (changed from {previous_verdict.value})", style="bold yellow")
    elif previous_verdict is not None:
        body.append("   (held)", style="dim")

    return Panel(
        body,
        title=f"[bold {color}]{name} — round {round_num}[/bold {color}]",
        border_style=color,
    )


def render_initial_votes(votes: dict, console: Console) -> None:
    for name, result in votes.items():
        console.print(_persona_panel(name, result))


def render_debate_round(
    round_num: int,
    rebuttals: dict,
    previous_verdicts: dict[str, Verdict],
    console: Console,
) -> None:
    for name, rebuttal in rebuttals.items():
        prev = previous_verdicts.get(name)
        console.print(_debate_panel(name, prev, rebuttal, round_num))


def render_synthesis(synthesis: str, outcome: str, console: Console) -> None:
    color = "green" if outcome == "consensus" else "yellow" if outcome == "deadlock" else "red"
    console.print()
    console.print(Panel(synthesis, title=f"[bold {color}]RESULT[/bold {color}]", border_style=color))


def print_help(console: Console) -> None:
    console.print(Panel(HELP_TEXT, border_style="dim"))


def render_journal(entries: list[dict], console: Console) -> None:
    if not entries:
        console.print("[dim]journal is empty — your deliberations will be logged here[/dim]")
        return
    text = Text()
    for entry in entries:
        ts = entry.get("timestamp", "")[:16].replace("T", " ")
        outcome = entry.get("outcome", "?")
        outcome_color = "green" if outcome == "consensus" else "yellow" if outcome == "deadlock" else "dim"
        text.append(f"  {entry.get('id', '?'):<8}  ", style="bold cyan")
        text.append(f"{ts}  ", style="dim")
        text.append(f"[{outcome.upper()}]\n", style=f"bold {outcome_color}")
        text.append(f"            {entry.get('question', '')[:90]}\n", style="italic")
        text.append(f"            {entry.get('synthesis', '')}\n", style="dim")
        if entry.get("user_outcome"):
            text.append(f"            ↳ outcome: {entry['user_outcome']}\n", style="bold green")
        text.append("\n")
    console.print(Panel(text, title="[bold]decision journal[/bold]", border_style="dim"))
