"""Poll the durable SQLite Map-Reduce summary queue from an isolated process."""

from __future__ import annotations

import argparse
import os
import socket
import time

from app.config import Settings
from app.db import initialize
from app.services.summary_jobs import process_next


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--lease-seconds", type=float, default=1800.0)
    args = parser.parse_args()
    settings = Settings.from_env()
    initialize(settings.database_path)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    while True:
        processed = process_next(
            settings.database_path,
            settings,
            worker_id,
            lease_seconds=max(30.0, args.lease_seconds),
        )
        if args.once:
            return
        if processed is None:
            time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    main()
