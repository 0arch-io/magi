import asyncio

import click

from magi.core import DEFAULT_MODELS
from magi.personas import SPECIALIST_DEFAULT_MODELS, SPECIALISTS
from magi.repl import run_oneshot, run_repl


@click.command()
@click.argument("question", nargs=-1, required=False)
@click.option("--melchior", default=None, help=f"Override Melchior's model (default: {DEFAULT_MODELS['MELCHIOR']})")
@click.option("--balthasar", default=None, help=f"Override Balthasar's model (default: {DEFAULT_MODELS['BALTHASAR']})")
@click.option("--casper", default=None, help=f"Override Casper's model (default: {DEFAULT_MODELS['CASPER']})")
@click.option("--invite", multiple=True, help=f"Invite a specialist (one of: {', '.join(s.lower() for s in SPECIALISTS)}). Repeatable.")
def cli(
    question: tuple[str, ...],
    melchior: str | None,
    balthasar: str | None,
    casper: str | None,
    invite: tuple[str, ...],
) -> None:
    """MAGI — three-agent decision council inspired by Evangelion.

    Three open-source models served via Ollama deliberate on a question.
    They argue across multiple rounds until consensus or deadlock.

    Examples:
        magi
        magi "should I take the job offer?"
        magi --invite banker --invite therapist "should I move cities?"
    """
    models = dict(DEFAULT_MODELS)
    if melchior:
        models["MELCHIOR"] = melchior
    if balthasar:
        models["BALTHASAR"] = balthasar
    if casper:
        models["CASPER"] = casper

    for spec in invite:
        canonical = spec.upper()
        if canonical not in SPECIALISTS:
            click.echo(f"warning: unknown specialist {spec!r}; available: {', '.join(s.lower() for s in SPECIALISTS)}", err=True)
            continue
        models[canonical] = SPECIALIST_DEFAULT_MODELS[canonical]

    if question:
        asyncio.run(run_oneshot(" ".join(question), models))
    else:
        asyncio.run(run_repl(models))
