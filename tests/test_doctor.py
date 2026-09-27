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


def test_doctor_says_when_a_newer_ask_model_is_out(monkeypatch):
    import httpx

    from unlimitedpipe.doctor import newer_ask_model

    class Answer:
        def json(self):
            return {"lastModified": "2026-09-27T12:00:00.000Z"}

    monkeypatch.setattr(httpx, "get", lambda url, **kw: Answer())
    tags = [
        {"name": "hf.co/unlimitedpipe/ask-0.5b-GGUF:latest", "modified_at": "2026-09-27T01:00:00Z"}
    ]
    assert newer_ask_model(tags) == "2026-09-27"
    tags[0]["modified_at"] = "2026-09-27T13:00:00Z"
    assert newer_ask_model(tags) is None  # pulled after it came out
    assert newer_ask_model([{"name": "qwen2.5:3b", "modified_at": "2026-01-01"}]) is None
