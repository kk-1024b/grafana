#!/usr/bin/env bash
# Smoke test: build Docker image, start container, trigger a run, verify.
# Run from the project root:  bash scripts/smoke.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Smoke test: build image ==="
docker compose build ci_runner 2>&1 | tail -5

echo "=== Start container ==="
# Remove any previous instance.
docker rm -f ci_runner 2>/dev/null || true
docker compose up -d

# Wait for uvicorn.
echo "=== Wait for uvicorn ==="
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8080/healthz >/dev/null 2>&1; then
        echo "  ready after ${i}s"
        break
    fi
    sleep 1
done

echo "=== Trigger run ==="
RESP=$(curl -s -X POST http://127.0.0.1:8080/projects/my_cpp_project/run 2>&1)
echo "  $RESP"
RUN_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])" 2>/dev/null || echo "")

if [ -z "$RUN_ID" ]; then
    echo "FAIL: no run_id in response"
    docker compose logs ci_runner | tail -20
    docker compose down
    exit 1
fi

echo "=== Poll run $RUN_ID ==="
for i in $(seq 1 60); do
    META=$(curl -s "http://127.0.0.1:8080/runs/$RUN_ID")
    STATUS=$(echo "$META" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "running")
    if [ "$STATUS" = "success" ] || [ "$STATUS" = "failed" ]; then
        echo "  status=$STATUS after ${i}s"
        echo "$META" | python3 -m json.tool
        break
    fi
    sleep 1
done

if [ "$STATUS" != "success" ]; then
    echo "FAIL: run status is $STATUS"
    docker compose logs ci_runner | tail -30
    docker compose down
    exit 1
fi

echo "=== Check logs ==="
curl -s "http://127.0.0.1:8080/runs/$RUN_ID/log/build" | tail -5
curl -s "http://127.0.0.1:8080/runs/$RUN_ID/log/test" | tail -5

echo "=== Check DB ==="
docker exec ci_runner sqlite3 /data/db.sqlite "SELECT id,status,trigger,started_at FROM runs" 2>&1 | head -5

echo "=== Smoke test PASSED ==="
docker compose down