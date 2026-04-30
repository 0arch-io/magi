import asyncio

import click

from magi.core import DEFAULT_MODELS
from magi.repl import run_oneshot, run_repl


@click.command()
@click.argument("question", nargs=-1, required=False)
@click.option("--melchior", default=None, help=f"Override Melchior's model (default: {DEFAULT_MODELS['MELCHIOR']})")
@click.option("--balthasar", default=None, help=f"Override Balthasar's model (default: {DEFAULT_MODELS['BALTHASAR']})")
@click.option("--casper", default=None, help=f"Override Casper's model (default: {DEFAULT_MODELS['CASPER']})")
def cli(question: tuple[str, ...], melchior: str | None, balthasar: str | None, casper: str | None) -> None:
    """MAGI — three-agent decision system inspired by Evangelion.

    Three independent open-source models served via Ollama deliberate on a
    decision and return their verdicts.

    Run with no arguments to launch the interactive panel.
    Pass a question in quotes for a one-shot consultation.

    Examples:
        magi
        magi "should I take the job offer?"
        magi --melchior=qwen3:8b "should I quit my PhD?"
    """
    models = dict(DEFAULT_MODELS)
    if melchior:
        models["MELCHIOR"] = melchior
    if balthasar:
        models["BALTHASAR"] = balthasar
    if casper:
        models["CASPER"] = casper

    if question:
        asyncio.run(run_oneshot(" ".join(question), models))
    else:
        asyncio.run(run_repl(models))
