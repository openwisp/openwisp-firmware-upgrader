"""The docstrfmt server."""

import logging
import time

import click
import docutils
from aiohttp import web
from black import DEFAULT_LINE_LENGTH

from . import Manager, rst_extras


async def handler(request: web.Request) -> web.Response:
    """Handle the incoming request."""
    width = int(request.headers.get("X-Line-Length", DEFAULT_LINE_LENGTH))
    body = await request.text()

    start_time = time.perf_counter()
    manager = Manager(logging, None)
    try:
        try:
            text = manager.format_node(
                width, manager.parse_string("<server_input>", body)
            )
            resp = web.Response(text=text)
        except docutils.utils.SystemMessage as error:  # pragma: no cover
            raise ParseError(str(error)) from None
    except ParseError as error:  # pragma: no cover
        logging.warning(f"Failed to parse input: {error}")
        resp = web.Response(status=400, reason=str(error))
    except Exception as error:  # pragma: no cover
        logging.exception("Error while handling request")
        resp = web.Response(status=500, reason=str(error))

    end_time = time.perf_counter()

    int(1000 * (end_time - start_time))
    return resp


rst_extras.register()


@click.command()
@click.option(
    "-h",
    "--bind-host",
    "bind_host",
    type=str,
    default="localhost",
    show_default=True,
)
@click.option(
    "-p",
    "--bind-port",
    "bind_port",
    type=int,
    default=5219,
    show_default=True,
)
def main(bind_host: str, bind_port: int) -> None:
    """Start the docstrfmt server."""
    app = web.Application()
    app.add_routes([web.post("/", handler)])
    web.run_app(app, host=bind_host, port=bind_port)


class ParseError(Exception):  # pragma: no cover
    """An error occurred while parsing the input."""
