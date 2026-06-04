from apps import public_relay_entrypoint


def test_public_relay_entrypoint_reads_port(monkeypatch):
    calls = []

    def fake_run(app, host, port):
        calls.append({"app": app, "host": host, "port": port})

    monkeypatch.setenv("PORT", "8799")
    monkeypatch.setattr(public_relay_entrypoint.uvicorn, "run", fake_run)

    public_relay_entrypoint.main()

    assert calls == [
        {
            "app": "apps.public_relay_app:app",
            "host": "0.0.0.0",
            "port": 8799,
        }
    ]
