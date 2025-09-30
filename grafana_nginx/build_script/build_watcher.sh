##!/bin/bash

# 
docker pull python:3.11-alpine

docker run --restart=always -d --name dt_watcher \
    -v /home/kk/catch2_data/data:/data \
    -v /home/kk/catch2_data/app:/app \
    python:3.11-alpine \
    sh -c "mkdir -p /data/htmp && python3 /app/watch_new_files.py"


# 
# docker logs -f dt_watcher
