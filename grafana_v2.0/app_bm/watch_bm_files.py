#!/usr/bin/env python3
import time
import logging
from pathlib import Path

import db_bm
import bm_parser

logging.basicConfig(
    level='INFO',
    format='%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

WATCH_DIR = Path('/data/details/benchmark')
SECONDS = 2


def process_new_file(conn, f):
    logger.info(f"New file: {f}")
    date, author, host_srv, benchmarks = bm_parser.parse_json(f)
    run_id = db_bm.insert_run(conn, date, author, host_srv)
    db_bm.insert_benchmarks(conn, run_id, benchmarks)
    logger.info(f"Inserted run_id={run_id} date={date} benchmarks={len(benchmarks)}")


def watcher_task(conn, known):
    while True:
        time.sleep(SECONDS)
        current = {p for p in WATCH_DIR.rglob('*.json') if p.is_file()}
        new_files = current - known
        for f in new_files:
            process_new_file(conn, f)
        known = current


def main():
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    conn = db_bm.init_db()
    logger.info("Benchmark database initialized")

    known = {p for p in WATCH_DIR.rglob('*.json') if p.is_file()}
    logger.info(f"Watching {WATCH_DIR}, {len(known)} existing files")

    watcher_task(conn, known)


if __name__ == '__main__':
    main()
