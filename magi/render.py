from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

from magi.core import PersonaResponse, Verdict


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
    [dim]system online — awaiting query[/dim]
"""


HELP_TEXT = """[bold]commands[/bold]
  [cyan]/help[/cyan]      show this help
  [cyan]/opus[/cyan]      switch to Claude Opus 4.7
  [cyan]/sonnet[/cyan]    switch to Claude Sonnet 4.6
  [cyan]/model[/cyan]     show current model
  [cyan]/clear[/cyan]     clear the screen
  [cyan]/exit[/cyan]      exit the MAGI

[bold]anything else[/bold] is taken as a question for the panel.
"""


def print_banner(console: Console, model: str) -> None:
    console.print(BANNER)
    console.print(f"    [dim]model: [bold]{model}[/bold]  ·  /help for commands[/dim]\n")


def status_panel(statuses: dict[str, str], results: dict) -> Panel:
    text = Text()
    for name in statuses:
        result = results.get(name)
        if result is None:
            mark = "·"
            color = "yellow"
        elif isinstance(result, Exception):
            mark = "✗"
            color = "red"
        else:
            mark = "✓"
            color = VERDICT_COLOR[result.verdict]

        text.append(f"  {mark}  ", style=f"bold {color}")
        text.append(f"{name:<10}  ", style=f"bold {color}")
        text.append(f"{statuses[name]}\n", style="dim")

    return Panel(text, title="[bold cyan]MAGI DELIBERATING[/bold cyan]", border_style="cyan")


def _persona_panel(name: str, result: PersonaResponse | Exception) -> Panel:
    if isinstance(result, Exception):
        body = Text(f"FAILED: {type(result).__name__}: {result}", style="red")
        return Panel(body, title=f"[bold red]{name}[/bold red]", border_style="red")

    color = VERDICT_COLOR[result.verdict]
    body = Text()
    body.append(f"VERDICT: {result.verdict.value}\n\n", style=f"bold {color}")
    body.append(result.reasoning + "\n\n")
    body.append("KEY CONCERN: ", style="bold")
    body.append(result.key_concern)

    return Panel(body, title=f"[bold {color}]{name}[/bold {color}]", border_style=color)


def render_results(responses: dict, synthesis: str, console: Console | None = None) -> None:
    console = console or Console()
    for name, result in responses.items():
        console.print(_persona_panel(name, result))
    console.print()
    console.print(Panel(synthesis, title="[bold cyan]RESULT[/bold cyan]", border_style="cyan"))


def print_help(console: Console) -> None:
    console.print(Panel(HELP_TEXT, border_style="dim"))
