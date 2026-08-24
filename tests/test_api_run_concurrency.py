from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from apps.routes import api
from apps.services import RunRequest


def test_api_run_limits_active_organisms_without_dropping_requests(monkeypatch) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def measured_run(request: RunRequest, api_key: str | None = None):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.03)
            return {"status": "ok", "text": request.text}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(api, "_RUN_SLOTS", threading.BoundedSemaphore(2))
    monkeypatch.setattr(api, "_run_triade", measured_run)
    request = RunRequest(text="bounded")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: api.run_triade(request, None), range(8)))

    assert peak == 2
    assert len(results) == 8
    assert all(result["status"] == "ok" for result in results)
