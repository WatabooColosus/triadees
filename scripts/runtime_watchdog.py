#!/usr/bin/env python3
"""Watchdog foreground. systemd conserva el proceso; este módulo evalúa progreso."""

import json
import os
import time

from triade.runtime.watchdog import RuntimeWatchdog

if __name__ == "__main__":
    interval = max(10, int(os.getenv("TRIADE_WATCHDOG_INTERVAL", "60")))
    watchdog = RuntimeWatchdog(
        max_recoveries=int(os.getenv("TRIADE_WATCHDOG_MAX_RECOVERIES", "3"))
    )
    while True:
        result = watchdog.tick(process_running=True)
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        time.sleep(interval)
