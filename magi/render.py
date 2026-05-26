from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from magi.core import (
    ChoiceRebuttal,
    ChoiceResponse,
    PersonaResponse,
    Rebuttal,
    RecommendRebuttal,
    RecommendResponse,
    Verdict,
)

VERDICT_COLOR = {
    Verdict.ACCEPT: "green",
    Verdict.REJECT: "red",
    Verdict.CONDITIONAL: "yellow",
}

CHOICE_COLOR = "cyan"
RECOMMEND_COLOR = "blue"


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
  [cyan]/stats[/cyan]                 decision patterns and analytics
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
     keeps going until consensus or up to 3 rounds total

[bold]outcomes[/bold]
  [green]CONSENSUS[/green]   all three agree — clean answer
  [yellow]DEADLOCK[/yellow]   they could not agree after 3 rounds — your call
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
    body.append(result.reasoning)
    if result.verdict == Verdict.CONDITIONAL and result.condition:
        body.append("\n\n")
        body.append("ONLY IF: ", style=f"bold {color}")
        body.append(result.condition)

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
    if rebuttal.final_verdict == Verdict.CONDITIONAL and rebuttal.condition:
        body.append("\n\n")
        body.append("ONLY IF: ", style=f"bold {color}")
        body.append(rebuttal.condition)

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


# ── choice-mode rendering (v0.11) ──────────────────────────────────────────


def choice_vote_status_panel(statuses: dict[str, str], results: dict) -> Panel:
    text = Text()
    for name in statuses:
        result = results.get(name)
        if result is None:
            mark, color = "·", "cyan"
        elif isinstance(result, Exception):
            mark, color = "✗", "red"
        else:
            mark, color = "✓", CHOICE_COLOR

        text.append(f"  {mark}  ", style=f"bold {color}")
        text.append(f"{name:<10}  ", style=f"bold {color}")
        text.append(f"{statuses[name]}\n", style="dim")

    return Panel(text, title="[bold cyan]ROUND 1 — INITIAL PICKS[/bold cyan]", border_style="cyan")


def choice_debate_status_panel(statuses: dict[str, str], rebuttals: dict, round_num: int) -> Panel:
    text = Text()
    for name in statuses:
        result = rebuttals.get(name)
        if result is None:
            mark, color = "·", "magenta"
        elif isinstance(result, Exception):
            mark, color = "✗", "red"
        else:
            mark, color = "✓", CHOICE_COLOR

        text.append(f"  {mark}  ", style=f"bold {color}")
        text.append(f"{name:<10}  ", style=f"bold {color}")
        text.append(f"{statuses[name]}\n", style="dim")

    title = f"[bold magenta]ROUND {round_num} — COUNCIL DELIBERATES[/bold magenta]"
    return Panel(text, title=title, border_style="magenta")


def _choice_panel(name: str, result: ChoiceResponse | Exception) -> Panel:
    if isinstance(result, Exception):
        body = Text(f"FAILED: {type(result).__name__}: {result}", style="red")
        return Panel(body, title=f"[bold red]{name}[/bold red]", border_style="red")

    body = Text()
    body.append("PICKS: ", style=f"bold {CHOICE_COLOR}")
    body.append(f"{result.chosen_option}\n\n", style=f"bold {CHOICE_COLOR}")
    body.append(result.reasoning)

    return Panel(body, title=f"[bold {CHOICE_COLOR}]{name}[/bold {CHOICE_COLOR}]", border_style=CHOICE_COLOR)


def _choice_debate_panel(
    name: str,
    previous_choice: str | None,
    rebuttal: ChoiceRebuttal | Exception | None,
    round_num: int,
) -> Panel:
    if isinstance(rebuttal, Exception):
        body = Text(f"DEBATE FAILED: {type(rebuttal).__name__}: {rebuttal}", style="red")
        return Panel(body, title=f"[bold red]{name}[/bold red]", border_style="red")

    if rebuttal is None:
        body = Text("(no debate this round)", style="dim")
        return Panel(body, title=f"[bold]{name}[/bold]", border_style="dim")

    body = Text()
    body.append(rebuttal.response + "\n\n")
    body.append("PICKS: ", style="bold")
    body.append(rebuttal.final_choice, style=f"bold {CHOICE_COLOR}")
    if previous_choice is not None and rebuttal.final_choice != previous_choice:
        body.append(f"   (changed from {previous_choice})", style="bold yellow")
    elif previous_choice is not None:
        body.append("   (held)", style="dim")

    return Panel(
        body,
        title=f"[bold {CHOICE_COLOR}]{name} — round {round_num}[/bold {CHOICE_COLOR}]",
        border_style=CHOICE_COLOR,
    )


def render_initial_choices(choices: dict, console: Console) -> None:
    for name, result in choices.items():
        console.print(_choice_panel(name, result))


def render_choice_debate_round(
    round_num: int,
    rebuttals: dict,
    previous_choices: dict[str, str],
    console: Console,
) -> None:
    for name, rebuttal in rebuttals.items():
        prev = previous_choices.get(name)
        console.print(_choice_debate_panel(name, prev, rebuttal, round_num))


def render_intake(question_class: str, options: list[str], console: Console) -> None:
    """Tiny dim-line above the deliberation showing the classifier's read."""
    if question_class == "choice" and options:
        console.print(f"[dim italic]intake: choice question — {' vs '.join(options)}[/dim italic]")
    else:
        console.print(f"[dim italic]intake: {question_class} question[/dim italic]")


# ── recommend-mode rendering (v0.11 phase C) ───────────────────────────────


def recommend_vote_status_panel(statuses: dict[str, str], results: dict) -> Panel:
    text = Text()
    for name in statuses:
        result = results.get(name)
        if result is None:
            mark, color = "·", RECOMMEND_COLOR
        elif isinstance(result, Exception):
            mark, color = "✗", "red"
        else:
            mark, color = "✓", RECOMMEND_COLOR

        text.append(f"  {mark}  ", style=f"bold {color}")
        text.append(f"{name:<10}  ", style=f"bold {color}")
        text.append(f"{statuses[name]}\n", style="dim")

    return Panel(text, title=f"[bold {RECOMMEND_COLOR}]ROUND 1 — INITIAL RECOMMENDATIONS[/bold {RECOMMEND_COLOR}]", border_style=RECOMMEND_COLOR)


def recommend_debate_status_panel(statuses: dict[str, str], rebuttals: dict, round_num: int) -> Panel:
    text = Text()
    for name in statuses:
        result = rebuttals.get(name)
        if result is None:
            mark, color = "·", "magenta"
        elif isinstance(result, Exception):
            mark, color = "✗", "red"
        else:
            mark, color = "✓", RECOMMEND_COLOR

        text.append(f"  {mark}  ", style=f"bold {color}")
        text.append(f"{name:<10}  ", style=f"bold {color}")
        text.append(f"{statuses[name]}\n", style="dim")

    title = f"[bold magenta]ROUND {round_num} — COUNCIL REFINES[/bold magenta]"
    return Panel(text, title=title, border_style="magenta")


def _recommend_panel(name: str, result: RecommendResponse | Exception) -> Panel:
    if isinstance(result, Exception):
        body = Text(f"FAILED: {type(result).__name__}: {result}", style="red")
        return Panel(body, title=f"[bold red]{name}[/bold red]", border_style="red")

    body = Text()
    body.append("RECOMMENDS: ", style=f"bold {RECOMMEND_COLOR}")
    body.append(f"{result.recommendation}\n\n", style=f"bold {RECOMMEND_COLOR}")
    body.append(result.reasoning)

    return Panel(body, title=f"[bold {RECOMMEND_COLOR}]{name}[/bold {RECOMMEND_COLOR}]", border_style=RECOMMEND_COLOR)


def _recommend_debate_panel(
    name: str,
    previous_rec: str | None,
    rebuttal: RecommendRebuttal | Exception | None,
    round_num: int,
) -> Panel:
    if isinstance(rebuttal, Exception):
        body = Text(f"DEBATE FAILED: {type(rebuttal).__name__}: {rebuttal}", style="red")
        return Panel(body, title=f"[bold red]{name}[/bold red]", border_style="red")

    if rebuttal is None:
        body = Text("(no debate this round)", style="dim")
        return Panel(body, title=f"[bold]{name}[/bold]", border_style="dim")

    body = Text()
    body.append(rebuttal.response + "\n\n")
    body.append("RECOMMENDS: ", style="bold")
    body.append(rebuttal.final_recommendation, style=f"bold {RECOMMEND_COLOR}")
    if previous_rec is not None and rebuttal.final_recommendation.lower().strip() != previous_rec.lower().strip():
        body.append(f"\n   (refined from: {previous_rec})", style="bold yellow")
    elif previous_rec is not None:
        body.append("   (held)", style="dim")

    return Panel(
        body,
        title=f"[bold {RECOMMEND_COLOR}]{name} — round {round_num}[/bold {RECOMMEND_COLOR}]",
        border_style=RECOMMEND_COLOR,
    )


def render_initial_recommendations(recs: dict, console: Console) -> None:
    for name, result in recs.items():
        console.print(_recommend_panel(name, result))


def render_recommend_debate_round(
    round_num: int,
    rebuttals: dict,
    previous_recs: dict[str, str],
    console: Console,
) -> None:
    for name, rebuttal in rebuttals.items():
        prev = previous_recs.get(name)
        console.print(_recommend_debate_panel(name, prev, rebuttal, round_num))


def print_help(console: Console) -> None:
    console.print(Panel(HELP_TEXT, border_style="dim"))


def warmup_status_panel(statuses: dict[str, tuple[str, str]]) -> Panel:
    """statuses[name] = (model_id, state). state ∈ {'loading', 'ready', 'failed: ...'}."""
    text = Text()
    for name, (model, state) in statuses.items():
        if state == "ready":
            mark, color = "✓", "green"
        elif state == "loading":
            mark, color = "·", "yellow"
        else:
            mark, color = "✗", "red"
        text.append(f"  {mark}  ", style=f"bold {color}")
        text.append(f"{name:<10}  ", style=f"bold {color}")
        text.append(f"[{model}]  ", style="dim")
        text.append(f"{state}\n", style="dim")
    return Panel(text, title="[bold cyan]WARMING COUNCIL[/bold cyan]", border_style="cyan")


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


def render_stats(entries: list[dict], console: Console) -> None:
    if not entries:
        console.print("[dim]no deliberations yet — stats will appear after your first question[/dim]")
        return

    total = len(entries)
    consensus_count = sum(1 for e in entries if e.get("outcome") == "consensus")
    deadlock_count = sum(1 for e in entries if e.get("outcome") in ("deadlock", "split"))
    picks_count = sum(1 for e in entries if e.get("outcome") == "picks")
    other_count = total - consensus_count - deadlock_count - picks_count
    outcomes_recorded = sum(1 for e in entries if e.get("user_outcome"))

    avg_rounds = 0
    rounds_entries = [e for e in entries if e.get("rounds")]
    if rounds_entries:
        avg_rounds = sum(e["rounds"] for e in rounds_entries) / len(rounds_entries)

    text = Text()
    text.append(f"  total deliberations:  {total}\n", style="bold")
    text.append(f"  consensus:            {consensus_count}", style="green")
    if total > 0:
        text.append(f"  ({consensus_count * 100 // total}%)", style="dim")
    text.append("\n")
    text.append(f"  deadlock/split:       {deadlock_count}", style="yellow")
    if total > 0:
        text.append(f"  ({deadlock_count * 100 // total}%)", style="dim")
    text.append("\n")
    if picks_count:
        text.append(f"  open (distinct picks):{picks_count:>2}\n", style="blue")
    if other_count:
        text.append(f"  other:                {other_count}\n", style="dim")
    text.append(f"  avg rounds:           {avg_rounds:.1f}\n", style="dim")
    text.append(f"  outcomes recorded:    {outcomes_recorded}/{total}\n", style="dim")

    console.print(Panel(text, title="[bold]decision stats[/bold]", border_style="dim"))

    if deadlock_count >= 3:
        deadlocks = [e for e in entries if e.get("outcome") in ("deadlock", "split")]
        text2 = Text()
        for e in deadlocks[:10]:
            ts = e.get("timestamp", "")[:10]
            text2.append(f"  {ts}  ", style="dim")
            text2.append(f"{e.get('question', '')[:80]}\n", style="italic")
        console.print(Panel(text2, title="[bold yellow]recent deadlocks[/bold yellow]", border_style="yellow"))
