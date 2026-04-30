from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from magi.core import PersonaResponse, Verdict


VERDICT_COLOR = {
    Verdict.ACCEPT: "green",
    Verdict.REJECT: "red",
    Verdict.CONDITIONAL: "yellow",
}


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
