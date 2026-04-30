import asyncio
import os
import sys

import click
from rich.console import Console

from magi.core import consult_all, synthesize
from magi.render import render_results


@click.command()
@click.argument("question", nargs=-1, required=True)
@click.option("--opus", is_flag=True, help="Use Claude Opus 4.7 (default: Sonnet 4.6)")
def cli(question: tuple[str, ...], opus: bool) -> None:
    """MAGI — three-agent decision system inspired by Evangelion.

    Consults Melchior (scientist), Balthasar (mother), and Casper (woman)
    on a decision and returns their verdicts.

    Example:
        magi "should I take the job offer at X for Y?"
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        click.echo("error: ANTHROPIC_API_KEY environment variable is not set", err=True)
        sys.exit(1)

    question_str = " ".join(question)
    model = "claude-opus-4-7" if opus else "claude-sonnet-4-6"

    console = Console()
    with console.status(f"[cyan]The MAGI deliberate ({model})...[/cyan]"):
        responses = asyncio.run(consult_all(question_str, model))

    synthesis = synthesize(responses)
    render_results(responses, synthesis, console)
