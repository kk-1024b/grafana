#!/bin/bash
set -e

IMAGE=dt_all:1.0
CONTAINER=dt_all
TMP_CONTAINER=dt_all_export_tmp
DATA_DIR=/home/kk/catch2_data/data
EXPORT_FILE="dt_all_1.0.tar"

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Build image
docker build -t "$IMAGE" "$SCRIPT_DIR"

# Export as flat tar via docker export (requires a container instance)
echo "Exporting image to $SCRIPT_DIR/$EXPORT_FILE ..."
docker rm -f "$TMP_CONTAINER" 2>/dev/null || true
docker create --name "$TMP_CONTAINER" "$IMAGE"
docker export "$TMP_CONTAINER" -o "$SCRIPT_DIR/$EXPORT_FILE"
docker rm "$TMP_CONTAINER"
echo "Export done: $SCRIPT_DIR/$EXPORT_FILE"

# Remove old container if exists
docker rm -f "$CONTAINER" 2>/dev/null || true

# Start container
docker run -d --restart=always --name "$CONTAINER" \
    -p 9696:3000 \
    -p 9699:8080 \
    -v "$DATA_DIR":/data \
    "$IMAGE"

echo "Started: Grafana -> http://localhost:9696  |  nginx -> http://localhost:9699"

# -------------------------------------------------------
# To load and run on another machine:
#
#   docker import dt_all_1.0.tar dt_all:1.0
#   docker run -d --restart=always --name dt_all \
#       -p 9696:3000 -p 9699:8080 \
#       -v /your/data/path:/data \
#       dt_all:1.0 \
#       /usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
#
# Note: docker export/import drops CMD metadata, so the startup
# command must be specified explicitly on docker run.
# -------------------------------------------------------
