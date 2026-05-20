"""Simple configuration loader for Triade."""

from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "models": {
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "timeout": 60,
        "fallback_enabled": True,
        "roles": {
            "hypothalamus": "qwen2.5:3b-instruct",
            "central": "qwen2.5:3b-instruct",
        },
    }
}


def load_config(path: str | Path = "triade.yml") -> dict[str, Any]:
    """Loads a tiny YAML subset used by triade.yml.

    This avoids adding PyYAML during the MVP. It supports the current nested
    key/value shape only. If parsing fails, defaults are returned.
    """
    config = DEFAULT_CONFIG.copy()
    file_path = Path(path)
    if not file_path.exists():
        return DEFAULT_CONFIG

    try:
        parsed = _parse_simple_yaml(file_path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_CONFIG

    return _deep_merge(DEFAULT_CONFIG, parsed)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if value == "":
            new_map: dict[str, Any] = {}
            current[key] = new_map
            stack.append((indent, new_map))
        else:
            current[key] = _coerce_value(value)

    return root


def _coerce_value(value: str) -> Any:
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {**base}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
