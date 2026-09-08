"""Real HTTP API/CLI worker recovery; model transport is loopback-only."""

from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time

import httpx
import pytest


def _wait(predicate, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for deployment state")


@pytest.mark.parametrize("fault", ["kill", "disconnect"])
def test_real_api_and_worker_recover_from_transport_fault(tmp_path, fault):
    reached = threading.Event()
    release = threading.Event()
    healthy = threading.Event()

    class ModelHandler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            reached.set()
            if not healthy.is_set():
                if fault == "kill":
                    release.wait(40)
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            content = {"degree": "MASTER", "subject_field": "CS",
                       "candidates": [{"title": "Recovered research topic", "innovation": "test",
                                       "feasibility": "test", "degree_fit": "MASTER"}],
                       "recommendation": "Transport recovery fixture"}
            body = json.dumps({"id": "local-fixture", "object": "chat.completion", "created": 0,
                               "model": "deepseek-v4-flash",
                               "choices": [{"index": 0, "finish_reason": "stop",
                                            "message": {"role": "assistant", "content": json.dumps(content)}}],
                               "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with closing(socket.socket()) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("THESIS_", "DOCX_"))}
    environment.update({
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend"),
        "PYTHONIOENCODING": "utf-8", "THESIS_DATA_DIR": str(tmp_path / "data"),
        "THESIS_TASK_STORE_MEMORY": "false", "THESIS_JOB_WORKER_ENABLED": "false",
        "THESIS_DEEPSEEK_ENABLED": "true", "THESIS_DEEPSEEK_FALLBACK_TO_MOCK": "false",
        "THESIS_DEEPSEEK_API_KEY": "local-test-not-a-secret",
        "THESIS_DEEPSEEK_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
        "THESIS_DEEPSEEK_TIMEOUT": "20", "THESIS_DEEPSEEK_RETRY_MAX": "0",
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
    })
    processes = []
    logs = []

    def start(arguments):
        log = (tmp_path / f"process-{len(processes)}.log").open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen([sys.executable, *arguments], cwd=tmp_path, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    api_args = ["-m", "uvicorn", "application.main:app", "--host", "127.0.0.1", "--port", str(port)]
    worker_args = ["-m", "application.worker", "--once", "--worker-id", "recovery-worker", "--lease-seconds", "10"]
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2, trust_env=False)

    def ready():
        try:
            return client.get("/healthz").status_code == 200
        except httpx.TransportError:
            return False

    try:
        api = start(api_args)
        _wait(ready)
        created = client.post("/api/v1/console/tasks", json={
            "title": "Fault recovery", "degree": "MASTER", "subject_field": "CS", "session_id": "fault",
        }).json()
        assert created["code"] == 0, created
        task_id = created["data"]["task_id"]
        url = f"/api/v1/console/tasks/{task_id}/jobs?session_id=fault"
        queued = client.post(url, json={"operation": "ring.execute", "payload": {"ring_no": 1},
                                        "idempotency_key": "recover-ring1", "max_attempts": 2 if fault == "kill" else 1}).json()["data"]
        worker = start(worker_args)
        assert reached.wait(30), "Worker never contacted model transport"
        assert client.get(url).json()["data"][0]["status"] == "RUNNING"
        if fault == "kill":
            worker.kill()
            worker.wait(10)
            release.set()
            # No timestamp edits: wait for the persisted lease to expire naturally.
            healthy.set()
            replacement = start([arg for arg in worker_args if arg != "--once"])
        else:
            assert worker.wait(35) == 1
            failed = client.get(url).json()["data"][0]
            assert failed["status"] == "FAILED"
            healthy.set()
            retried = client.post(f"/api/v1/console/tasks/{task_id}/jobs/{queued['job_id']}/retry?session_id=fault").json()
            assert retried["code"] == 0, retried
            replacement = start(worker_args)
        done = _wait(lambda: (job if (job := client.get(url).json()["data"][0])["status"] == "SUCCEEDED" else None))
        assert done["job_id"] == queued["job_id"]
        assert done["input_tokens"] == 20 and done["output_tokens"] == 30
        if fault == "kill":
            assert done["attempt"] == 2
        duplicate = client.post(url, json={"operation": "ring.execute", "payload": {"ring_no": 1},
                                           "idempotency_key": "recover-ring1"}).json()["data"]
        assert duplicate["job_id"] == queued["job_id"]
        if replacement.poll() is None:
            replacement.kill()
        replacement.wait(10)
        api.kill()
        api.wait(10)
        start(api_args)
        _wait(ready)
        assert client.get(url).json()["data"][0]["status"] == "SUCCEEDED"
        with closing(sqlite3.connect(tmp_path / "data" / "thesis.db")) as db:
            assert db.execute("SELECT phase_state FROM t_fsm_state WHERE task_id=?", (task_id,)).fetchone()[0] == "WAITING_APPROVAL"
        with closing(sqlite3.connect(tmp_path / "data" / "task_store.db")) as db:
            saved = json.loads(db.execute("SELECT payload FROM t_task_store WHERE task_id=?", (task_id,)).fetchone()[0])
            topic = json.loads(saved["ring1"])
            assert topic["_job_id"] == queued["job_id"]
            assert len(topic["candidates"]) == 1
    finally:
        release.set()
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(10)
        for log in logs:
            log.close()
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_worker_rejects_short_lease_before_opening_storage(tmp_path):
    from application.worker import main
    target = tmp_path / "not-created"
    with pytest.raises(SystemExit) as exc:
        main(["--data-dir", str(target), "--lease-seconds", "9"])
    assert exc.value.code == 2
    assert not target.exists()
