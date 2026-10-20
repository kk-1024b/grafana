"""CLI entry point for `docker exec python -m app.cli run <project>`.

Uses HTTP to talk to the same process (so it respects the global lock).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from urllib.error import URLError

API_BASE = "http://127.0.0.1:8080"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{API_BASE}{path}") as resp:
        return json.loads(resp.read())


def _post(path: str) -> dict:
    req = urllib.request.Request(f"{API_BASE}{path}", method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def cmd_run(args: list[str]) -> int:
    if not args:
        print("Usage: python -m app.cli run <project-name>", file=sys.stderr)
        return 2
    project = args[0]

    try:
        data = _post(f"/projects/{project}/run")
    except URLError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3

    run_id = data.get("run_id")
    if not run_id:
        print(f"Error: no run_id in response: {data}", file=sys.stderr)
        return 3

    status = data.get("status", "running")
    print(f"Run {run_id} started (status={status})")

    if status == "skipped":
        print(f"  Note: {data.get('note', '')}")
        return 2

    # Poll until done.
    while True:
        time.sleep(1)
        meta = _get(f"/runs/{run_id}")
        if meta["status"] in ("success", "failed"):
            break
        print(".", end="", flush=True)
    print()

    # Print tails.
    for log_name in ("clone", "build", "test"):
        try:
            with urllib.request.urlopen(
                f"{API_BASE}/runs/{run_id}/log/{log_name}"
            ) as resp:
                log_text = resp.read().decode(errors="replace")
                if log_text.strip():
                    tail = "\n".join(log_text.rstrip().splitlines()[-40:])
                    print(f"--- {log_name}.log (tail 40) ---\n{tail}\n")
        except URLError:
            pass

    print(json.dumps(meta, indent=2, ensure_ascii=False))
    # Return test_exit if present, else build_exit, else 1.
    if meta["status"] == "success":
        return 0
    meta_test = meta.get("test_exit")
    meta_build = meta.get("build_exit")
    return meta_test if meta_test is not None else (meta_build if meta_build is not None else 1)


def cmd_list(args: list[str]) -> int:
    project = args[0] if args else None
    path = "/runs" + (f"?project={project}" if project else "")
    try:
        runs = _get(path)
    except URLError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    for r in runs:
        print(
            f"{r['id']:50s} {r['status']:10s} "
            f"{r['trigger']:12s} "
            f"{r.get('started_at',''):25s} "
            f"{r.get('note','')}"
        )
    return 0


def cmd_show(args: list[str]) -> int:
    if not args:
        print("Usage: python -m app.cli show <run-id>", file=sys.stderr)
        return 2
    run_id = args[0]
    try:
        meta = _get(f"/runs/{run_id}")
    except URLError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    for log_name in ("clone", "build", "test"):
        try:
            with urllib.request.urlopen(
                f"{API_BASE}/runs/{run_id}/log/{log_name}"
            ) as resp:
                log_text = resp.read().decode(errors="replace")
                if log_text.strip():
                    tail = "\n".join(log_text.rstrip().splitlines()[-50:])
                    print(f"\n--- {log_name}.log (tail 50) ---\n{tail}")
        except URLError:
            pass
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m app.cli <run|list|show> [args...]", file=sys.stderr)
        return 2

    command = sys.argv[1]
    rest = sys.argv[2:]

    if command == "run":
        return cmd_run(rest)
    elif command == "list":
        return cmd_list(rest)
    elif command == "show":
        return cmd_show(rest)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Available: run, list, show", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())