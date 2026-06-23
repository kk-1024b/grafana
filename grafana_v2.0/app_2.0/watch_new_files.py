#!/usr/bin/env python3
import time
import logging
from pathlib import Path

import db
import resultSum

logging.basicConfig(
    level='INFO',
    format='%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

WATCH_DIR = Path('/data/details/sources')
SECONDS = 2


def processNewFile(conn, f):
    logger.info(f"New file: {f}")
    tm, passNum, totalNum, rows = resultSum.getTestResult(f)
    tm = resultSum.switchTime(tm)
    resultSum.insertResult(conn, tm, passNum, totalNum, rows)


def watcher_task(conn, known):
    while True:
        time.sleep(SECONDS)
        current = {p for p in WATCH_DIR.rglob('*') if p.is_file()}
        new_files = current - known
        for f in new_files:
            processNewFile(conn, f)
        known = current


def main():
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    conn = db.init_db()
    logger.info("Database initialized")

    known = {p for p in WATCH_DIR.rglob('*') if p.is_file()}
    logger.info(f"Watching {WATCH_DIR}, {len(known)} existing files")

    watcher_task(conn, known)


if __name__ == '__main__':
    main()
