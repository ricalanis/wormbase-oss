"""``wormbase-voice-agent`` CLI.

Single command for the Thursday demo: ``serve``. Boots the FastAPI app
under uvicorn on a configurable port (default 8090).

Run from inside docker-compose::

    wormbase-voice-agent serve --port 8090

Or in dev::

    OLLAMA_API_KEY=... \\
    WORMBASE_LEDGER_DSN=postgresql+asyncpg://... \\
    wormbase-voice-agent serve --port 8090
"""

from __future__ import annotations

import logging
import os

import click


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=False)
def main(verbose: bool) -> None:
    """WormBase voice agent — ElevenLabs ↔ Kimi bridge."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )


@main.command("serve")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8090, type=int, show_default=True)
@click.option(
    "--reload",
    is_flag=True,
    default=False,
    help="Enable auto-reload (dev only).",
)
@click.option(
    "--log-level",
    default=lambda: os.environ.get("WORMBASE_VOICE_LOG_LEVEL", "info"),
    show_default="info",
)
def serve_cmd(host: str, port: int, reload: bool, log_level: str) -> None:
    """Start the FastAPI service for ElevenLabs webhooks."""
    import uvicorn  # local import keeps `--help` snappy

    uvicorn.run(
        "wormbase_voice_agent.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
