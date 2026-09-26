import json
import subprocess
import sys

from unlimitedpipe.doctor import run_checks


def test_doctor_reports_every_area_without_showing_key_values(monkeypatch, tmp_path):
    monkeypatch.setenv("UNLIMITEDPIPE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("X_BEARER_TOKEN", "super-secret-value")
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")  # nothing listens there
    checks = run_checks("http://127.0.0.1:9/")
    by_name = {c.name: c for c in checks}
    assert {c.area for c in checks} == {"core", "network", "extras", "ai", "keys"}
    assert by_name["state folder"].ok
    assert not by_name["feed catalog"].ok and by_name["feed catalog"].fix
    assert by_name["X_BEARER_TOKEN"].ok and not by_name["YOUTUBE_API_KEY"].ok
    assert "super-secret-value" not in repr(checks)
    assert not by_name["Ollama (ask, local)"].ok and by_name["Ollama (ask, local)"].optional


def test_doctor_json_for_agents(tmp_path):
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "unlimitedpipe",
            "doctor",
            "--json",
            "--catalog",
            "http://127.0.0.1:9/",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "OLLAMA_HOST": "http://127.0.0.1:9"},
    )
    checks = json.loads(run.stdout)
    assert {"area", "name", "ok", "detail", "fix", "optional"} <= set(checks[0])
