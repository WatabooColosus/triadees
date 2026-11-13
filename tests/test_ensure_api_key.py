from pathlib import Path

from scripts.ensure_api_key import ensure_api_key, rotate_api_key


def test_configures_key_without_returning_secret(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1\nTRIADE_API_KEY=\nB=2\n", encoding="utf-8")

    result = ensure_api_key(env)

    configured = next(
        line
        for line in env.read_text(encoding="utf-8").splitlines()
        if line.startswith("TRIADE_API_KEY=")
    ).partition("=")[2]
    assert result["status"] == "configured"
    assert result["secret_printed"] is False
    assert len(configured) >= 48
    assert configured not in str(result)


def test_existing_key_is_not_rotated(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TRIADE_API_KEY=already-secret\n", encoding="utf-8")

    assert ensure_api_key(env)["status"] == "already_configured"
    assert env.read_text(encoding="utf-8") == "TRIADE_API_KEY=already-secret\n"


def test_explicit_rotation_replaces_key_without_returning_it(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nTRIADE_API_KEY=old\n", encoding="utf-8")

    result = rotate_api_key(env, "new-secret")

    assert result["status"] == "rotated"
    assert result["secret_printed"] is False
    assert "new-secret" not in str(result)
    assert env.read_text(encoding="utf-8") == "OTHER=1\nTRIADE_API_KEY=new-secret\n"
