import asyncio
import os
import sys

import click

from magi.repl import OPUS, SONNET, run_oneshot, run_repl


@click.command()
@click.argument("question", nargs=-1, required=False)
@click.option("--opus", is_flag=True, help="Use Claude Opus 4.7 (default: Sonnet 4.6)")
def cli(question: tuple[str, ...], opus: bool) -> None:
    """MAGI — three-agent decision system inspired by Evangelion.

    Run with no arguments to launch the interactive panel.
    Pass a question in quotes for a one-shot consultation.

    Examples:
        magi
        magi "should I take the job offer?"
        magi --opus "should I quit my PhD?"
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        click.echo("error: ANTHROPIC_API_KEY environment variable is not set", err=True)
        sys.exit(1)

    model = OPUS if opus else SONNET

    if question:
        asyncio.run(run_oneshot(" ".join(question), model))
    else:
        asyncio.run(run_repl(model))
