"""Entrypoint for cloud platforms that inject PORT at runtime."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("apps.public_relay_app:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
