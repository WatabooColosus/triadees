"""Reserve the HTTP port before importing or starting Tríade's runtime.

Uvicorn's single-process CLI runs ASGI startup before binding the listener.
A competing launch would therefore start and stop shared workers even when
it can never serve HTTP. Keep the reserved socket through server shutdown.
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys

import uvicorn


def serve(host: str = "0.0.0.0", port: int = 8010) -> None:
    config = uvicorn.Config("apps.single_port_app:app", host=host, port=port)
    # bind_socket exits on collision, before Config.load imports the app.
    if sys.platform == "win32":
        listener = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((host, port))
        except OSError as exc:
            listener.close()
            logging.getLogger("uvicorn.error").error("Port reservation failed: %s", exc)
            raise SystemExit(1) from exc
    else:
        listener = config.bind_socket()
    try:
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    serve(host=args.host, port=args.port)
