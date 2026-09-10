"""Start the local API and static workbench from a source preview bundle."""

import argparse
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deep Thesis local preview")
    parser.add_argument("--data-dir", required=True, help="absolute persistent data directory")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--ui-port", type=int, default=8787)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    data = Path(args.data_dir)
    if not data.is_absolute():
        parser.error("--data-dir must be absolute")
    if args.api_port == args.ui_port or any(not 1 <= port <= 65535 for port in (args.api_port, args.ui_port)):
        parser.error("Use two different ports between 1 and 65535")
    if importlib.util.find_spec("uvicorn") is None:
        parser.error("Install dependencies first: python -m pip install ./backend")
    if not (root / "ui" / "index.html").is_file():
        parser.error("The complete ui directory is required")
    for port in (args.api_port, args.ui_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"Port {port} is already in use")
    environment = dict(os.environ)
    # A preview has one data location. Refuse hidden split-storage overrides.
    overrides = ("THESIS_DB_URL", "THESIS_TASK_STORE_DIR", "THESIS_KB_ROOT", "DOCX_UPLOAD_DIR", "DOCX_OUTPUT_DIR")
    if any(environment.get(name) for name in overrides) or any(
        name.startswith("THESIS_") and name.endswith("_DB") and value for name, value in environment.items()
    ):
        parser.error("Remove custom storage overrides before using the unified preview launcher")
    environment.update({"THESIS_DATA_DIR": str(data.resolve()), "THESIS_TASK_STORE_MEMORY": "false",
                        "THESIS_JOB_WORKER_ENABLED": "true",
                        "THESIS_CORS_ORIGINS": f"http://127.0.0.1:{args.ui_port},http://localhost:{args.ui_port}"})
    processes = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "application.main:app", "--host", "127.0.0.1",
                                "--port", str(args.api_port)], cwd=root / "backend", env=environment)
        processes.append(api)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if api.poll() is not None:
                raise RuntimeError("API startup failed; see the server output above")
            try:
                with opener.open(f"http://127.0.0.1:{args.api_port}/healthz", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("API startup timed out")
        ui = subprocess.Popen([sys.executable, str(root / "scripts" / "serve_preview_ui.py"), "--port", str(args.ui_port),
                               "--directory", str(root / "ui")], cwd=root, env=environment)
        processes.append(ui)
        print(f"Deep Thesis: http://127.0.0.1:{args.ui_port}/?apiBase=http://127.0.0.1:{args.api_port}", flush=True)
        print("Keep this terminal open. Press Ctrl+C to stop. Data remains in " + str(data.resolve()), flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
        raise RuntimeError("A preview service stopped; see its output above")
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"Deep Thesis preview: {exc}", file=sys.stderr)
        return 1
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
