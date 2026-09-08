"""Standalone worker: python -m application.worker --data-dir ABSOLUTE_PATH."""

import argparse
import logging
import os
import signal

from .bootstrap import build_orchestration


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Deep Thesis standalone worker")
    parser.add_argument("--data-dir", default=os.getenv("THESIS_DATA_DIR"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="execute at most one available job")
    mode.add_argument("--check", action="store_true", help="reconcile storage without executing jobs")
    parser.add_argument("--worker-id", default="")
    args = parser.parse_args(argv)
    if not args.data_dir:
        parser.error("--data-dir or THESIS_DATA_DIR is required")
    os.environ["THESIS_DATA_DIR"] = args.data_dir
    logging.basicConfig(level=logging.INFO)
    try:
        orchestration = build_orchestration(require_persistent=True)
        report = orchestration.reconcile_startup().data
        print(f"Deep Thesis worker: reconciliation={report['status']}", flush=True)
        if report["status"] != "CONSISTENT":
            return 2
    except (ValueError, RuntimeError) as exc:
        logging.error(
            "Worker startup refused (%s). Check THESIS_DATA_DIR, persistent storage paths and permissions.",
            type(exc).__name__,
        )
        return 2

    from jobs import JobStatus, JobWorker

    worker = JobWorker(orchestration._jobs, orchestration.job_handlers(), worker_id=args.worker_id)
    previous = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda *_: worker.stop(timeout=0))
        if args.check:
            return 0
        if args.once:
            job = worker.run_once()
            print(f"Deep Thesis worker: status={job.status.value if job else 'IDLE'}", flush=True)
            return 0 if job is None or job.status == JobStatus.SUCCEEDED else 1
        worker.run_forever()
        return 0
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
