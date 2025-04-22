import click

from jtec.commands.gatus import gatus


@click.group()
@click.pass_context
def cli(ctx, **kwargs):
    pass


cli.add_command(gatus.main)


def main() -> None:
    cli()
