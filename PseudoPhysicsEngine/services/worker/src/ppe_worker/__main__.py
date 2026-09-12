import argparse
import socket
import time
from uuid import uuid4

from ppe_worker.runtime import HttpJobGateway, Worker


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PseudoPhysicsEngine rules worker")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker_id = f"{socket.gethostname()}-{uuid4()}"
    worker = Worker(HttpJobGateway(args.api_url), worker_id)

    while True:
        try:
            claimed = worker.run_once()
        except Exception as error:
            print(f"Worker poll failed: {error}", flush=True)
            claimed = False
        if args.once:
            return
        if not claimed:
            time.sleep(max(args.poll_seconds, 0.1))


if __name__ == "__main__":
    main()
