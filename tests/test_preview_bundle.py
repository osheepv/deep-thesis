import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import zipfile

import pytest
import httpx


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_preview", ROOT / "scripts" / "build_preview.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    for name in builder.INCLUDE:
        path = root / name
        if name in ("backend", "ui"):
            path.mkdir()
            path = path / "sample.txt"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("committed sample", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=Preview Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "fixture"], cwd=root, check=True)
    return root


def test_bundle_uses_commit_not_dirty_or_untracked_data(repository, tmp_path):
    (repository / "backend" / ".env").write_text("SECRET=not-real")
    (repository / "backend" / "thesis.db").write_bytes(b"private-data")
    (repository / "ui" / "sample.txt").write_text("uncommitted change")
    output = tmp_path / "preview.zip"
    manifest = builder.build(repository, output)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert "deep-thesis/backend/.env" not in archive.namelist()
        assert "deep-thesis/backend/thesis.db" not in archive.namelist()
        assert archive.read("deep-thesis/ui/sample.txt") == b"committed sample"
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(archive.read("deep-thesis/" + name)).hexdigest() == digest
        assert json.loads(archive.read("deep-thesis/preview-manifest.json"))["source_commit"] == manifest["source_commit"]
    with pytest.raises(ValueError, match="nonexistent"):
        builder.build(repository, output)


def test_tracked_runtime_database_blocks_bundle(repository, tmp_path):
    (repository / "backend" / "thesis.db").write_bytes(b"private-data")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "-c", "user.name=Preview Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "bad fixture"], cwd=repository, check=True)
    output = tmp_path / "refused.zip"
    with pytest.raises(ValueError, match="Runtime data"):
        builder.build(repository, output)
    assert not output.exists()


@pytest.mark.parametrize("desktop_stop", [False, True])
def test_launcher_serves_ui_and_api_then_stops_both(tmp_path, desktop_stop):
    listeners = [socket.socket(), socket.socket()]
    try:
        for listener in listeners:
            listener.bind(("127.0.0.1", 0))
        api_port, ui_port = [listener.getsockname()[1] for listener in listeners]
    finally:
        for listener in listeners:
            listener.close()
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("THESIS_", "DOCX_"))}
    environment.update({"THESIS_DEEPSEEK_ENABLED": "false", "PYTHONIOENCODING": "utf-8"})
    # Exercise an in-process Ctrl+C, including on Windows CI.
    driver = """
import _thread, runpy, sys, threading
timer = threading.Timer(20, _thread.interrupt_main)
timer.daemon = True
timer.start()
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    data = tmp_path / "persistent"
    ready = tmp_path / "ready.json"
    stop = tmp_path / "stop"
    with (tmp_path / "preview.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-c", driver, str(ROOT / "scripts" / "run_preview.py"),
                                    "--data-dir", str(data), "--api-port", str(api_port), "--ui-port", str(ui_port),
                                    "--ready-file", str(ready), "--stop-file", str(stop)],
                                   cwd=tmp_path, env=environment, stdin=subprocess.PIPE, stdout=log, stderr=log, text=True)
        with httpx.Client(timeout=1, trust_env=False) as client:
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, (tmp_path / "preview.log").read_text(encoding="utf-8")
                    try:
                        response = client.get(f"http://127.0.0.1:{ui_port}/")
                        if response.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    pytest.fail("Preview did not become ready: " + (tmp_path / "preview.log").read_text(encoding="utf-8"))
                assert response.headers["cache-control"] == "no-store"
                script_url = f"http://127.0.0.1:{ui_port}/js/app.js"
                script = client.get(script_url)
                assert script.status_code == 200
                assert script.headers["cache-control"] == "no-store"
                reloaded = client.get(script_url, headers={
                    "If-Modified-Since": script.headers["last-modified"],
                })
                assert reloaded.status_code == 200
                assert reloaded.content == script.content
                assert client.get(f"http://127.0.0.1:{api_port}/healthz").json()["data"]["status"] == "UP"
                result = client.post(f"http://127.0.0.1:{api_port}/api/v1/console/tasks", json={
                    "title": "Preview persistence", "degree": "MASTER", "subject_field": "CS", "session_id": "preview",
                }).json()
                assert result["code"] == 0
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert json.loads(ready.read_text(encoding="utf-8"))["url"] == (
                    f"http://127.0.0.1:{ui_port}/?apiBase=http://127.0.0.1:{api_port}"
                )
            finally:
                if desktop_stop:
                    stop.write_text("stop", encoding="utf-8")
                process.wait(timeout=30)
            assert process.returncode == 0
            assert (data / "task_store.db").is_file()
            for port in (api_port, ui_port):
                with pytest.raises(httpx.TransportError):
                    client.get(f"http://127.0.0.1:{port}/")
