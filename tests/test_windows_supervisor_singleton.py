import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows supervisor")
def test_second_supervisor_cannot_acquire_repository_lock(tmp_path):
    source = (
        Path(__file__).resolve().parents[1] / "scripts/triade_service_worker.ps1"
    ).read_text(encoding="utf-8-sig")
    # Execute the production startup guard, without loading keys or starting API.
    guard = source.split("$python =", 1)[0]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    probe = scripts / "guard.ps1"
    probe.write_text(
        guard
        + '\nWrite-Output "LOCKED"\n[Console]::ReadLine() | Out-Null\n$supervisorGuard.Dispose()\n',
        encoding="utf-8",
    )
    wrapper = scripts / "invoke-guard.ps1"
    wrapper.write_text(
        "& (Join-Path $PSScriptRoot 'guard.ps1')\n"
        "$guardExit = $LASTEXITCODE\n"
        "if ($Error.Count) { [Console]::Error.WriteLine($Error[0].Exception.Message) }\n"
        "exit $guardExit\n",
        encoding="utf-8",
    )
    # Keep the original guard and exit status. Read the actual ErrorRecord:
    # PowerShell's display formatting truncates long-path error messages.
    command = ["powershell.exe", "-NoProfile", "-File", str(wrapper)]
    first = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert first.stdout.readline().strip() == "LOCKED"
        second = subprocess.run(
            command, input="\n", capture_output=True, text=True, timeout=15, check=False
        )
        assert second.returncode == 1
        assert "LOCKED" not in second.stdout
        assert "Another supervisor" in second.stderr
    finally:
        first.communicate("\n", timeout=15)
    third = subprocess.run(
        command, input="\n", capture_output=True, text=True, timeout=15, check=False
    )
    assert third.returncode == 0
    assert "LOCKED" in third.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
@pytest.mark.parametrize("configured", [True, False])
def test_backup_key_location_and_legacy_fallback(tmp_path, configured):
    source = (
        Path(__file__).resolve().parents[1] / "scripts/triade_service_worker.ps1"
    ).read_text(encoding="utf-8-sig")
    block = (
        "$keyCandidates ="
        + source.split("$keyCandidates =", 1)[1].split("Set-Location $repo", 1)[0]
    )
    # No production credential is consulted by this isolated launcher test.
    block = block.replace(
        r"C:\Users\sven6\AppData\Local\Triade\backup.key", str(tmp_path / "absent.key")
    )
    key = (
        tmp_path / "physical.key" if configured else tmp_path / "Triade" / "backup.key"
    )
    key.parent.mkdir(exist_ok=True)
    key.write_text("test-only-not-a-real-key", encoding="utf-8")
    if configured:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "backup_key_location.json").write_text(
            json.dumps({"key_file": str(key)}), encoding="utf-8"
        )
    path_literal = str(tmp_path).replace("'", "''")
    script = tmp_path / "key-probe.ps1"
    script.write_text(
        f"$ErrorActionPreference='Stop'\n$repo='{path_literal}'\n$env:LOCALAPPDATA=$repo\n"
        + block
        + '\n@{selected=$env:TRIADE_BACKUP_KEY_FILE;loaded=($env:TRIADE_BACKUP_KEY -eq "test-only-not-a-real-key");vault=($env:TRIADE_AUTH_VAULT_KEY -eq $env:TRIADE_BACKUP_KEY)} | ConvertTo-Json\n',
        encoding="utf-8",
    )
    run = subprocess.run(
        ["powershell.exe", "-NoProfile", "-File", str(script)],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    result = json.loads(run.stdout)
    assert Path(result["selected"]) == key
    assert result["loaded"] and result["vault"]
