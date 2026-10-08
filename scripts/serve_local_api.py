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
import threading
from pathlib import Path
from uuid import uuid4

import uvicorn

ROOT = Path(__file__).resolve().parents[1]


def watch_shutdown(server: uvicorn.Server, flag: Path, stop: threading.Event) -> None:
    while not stop.wait(1):
        if flag.is_file():
            # Retain the operator's request as an artifact; never execute it.
            try:
                flag.rename(flag.with_name(f"api-shutdown-handled-{uuid4().hex}.json"))
            except (FileNotFoundError, PermissionError):
                continue
            server.should_exit = True
            return


def serve(host: str = "0.0.0.0", port: int = 8010, shutdown_file: Path | None = None) -> None:
    if shutdown_file is not None:
        shutdown_file = shutdown_file.resolve()
        if not shutdown_file.is_relative_to(ROOT / "artifacts/service_logs"):
            raise ValueError("shutdown_file_outside_service_scope")
    config = uvicorn.Config("apps.single_port_app:app", host=host, port=port,
                            timeout_graceful_shutdown=30)
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
        from triade.runtime.source_provenance import capture_source, bind_loaded_source
        before = capture_source(ROOT)
        config.load()
        from apps.single_port_app import app
        # Captured around app import. This snapshot does not silently update
        # when HEAD changes later while this process remains alive.
        app.state.loaded_source_revision = bind_loaded_source(before, capture_source(ROOT))
        server = uvicorn.Server(config)
        stopped = threading.Event()
        monitor = None
        if shutdown_file is not None:
            monitor = threading.Thread(target=watch_shutdown, args=(server, shutdown_file, stopped), daemon=True)
            monitor.start()
        try:
            server.run(sockets=[listener])
        finally:
            stopped.set()
            if monitor is not None:
                monitor.join(timeout=2)
    finally:
        listener.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--shutdown-file", type=Path, default=ROOT / "artifacts/service_logs/api.shutdown")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, shutdown_file=args.shutdown_file)
