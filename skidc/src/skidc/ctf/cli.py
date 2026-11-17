"""Separate entry point; importing this command does not load the legacy engine."""
from pathlib import Path
import sqlite3

import click
import uvicorn

from .app import create_app


@click.group()
def main():
    """Experimental CTF blackboard and runtime protocol (no process execution)."""


@main.command()
@click.option("--db-path", type=click.Path(path_type=Path, dir_okay=False), required=True,
              help="Dedicated CTF SQLite file; never use the legacy database")
@click.option("--token-file", type=click.Path(path_type=Path, exists=True, dir_okay=False), required=True,
              help="File containing a separate random CTF control token (at least 32 characters)")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--dispatcher-token-file", type=click.Path(path_type=Path, exists=True, dir_okay=False),
              help="Optional independent dispatcher identity; requires --runtime-token-file")
@click.option("--runtime-token-file", type=click.Path(path_type=Path, exists=True, dir_okay=False),
              help="Optional execution-manager identity; requires --dispatcher-token-file")
@click.option("--port", default=8001, type=click.IntRange(1, 65535), show_default=True)
@click.option("--log-level", default="info", type=click.Choice(["debug", "info", "warning", "error"]), show_default=True)
def serve(db_path: Path, token_file: Path, host: str, port: int, log_level: str,
          dispatcher_token_file: Path | None, runtime_token_file: Path | None):
    """Start the CTF API, optionally exposing the runtime protocol."""
    try:
        token = token_file.read_text(encoding="utf-8").strip()
        dispatcher_token = dispatcher_token_file.read_text(encoding="utf-8").strip() if dispatcher_token_file else None
        runtime_token = runtime_token_file.read_text(encoding="utf-8").strip() if runtime_token_file else None
    except (OSError, UnicodeError) as exc:
        raise click.ClickException("Unable to read CTF control token file") from exc
    try:
        app = create_app(db_path, token, dispatcher_token=dispatcher_token, runtime_token=runtime_token)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    uvicorn.run(app, host=host, port=port, log_level=log_level)


@main.command("upgrade-copy")
@click.option("--source", type=click.Path(path_type=Path, exists=True, dir_okay=False), required=True)
@click.option("--destination", type=click.Path(path_type=Path, dir_okay=False), required=True)
def upgrade_copy_command(source: Path, destination: Path):
    """Offline copy from schema 1/2/3 into a NEW schema-4 file; preserve the source."""
    from .upgrade import upgrade_copy
    try:
        upgrade_copy(source, destination)
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("CTF copy-upgrade complete; source unchanged. Use the new database path.")


if __name__ == "__main__":
    main()
