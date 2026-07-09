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

WATCH_DIR = Path('/data/details/catch2')
DB_DIR    = Path('/data/platforms')
SECONDS   = 2


def get_conn(platform, conns):
    if platform not in conns:
        db_path = DB_DIR / f'{platform}.db'
        conns[platform] = db.init_db(db_path)
        logger.info(f"Opened DB: {db_path}")
    return conns[platform]


def processNewFile(conns, f):
    f = Path(f)
    if f.suffix != '.json':
        logger.info(f"Skipping non-JSON: {f}")
        return
    logger.info(f"Processing: {f}")
    platform, os_, arch, tm, passNum, totalNum, rows = resultSum.getTestResultFromJson(str(f))
    conn = get_conn(platform, conns)
    resultSum.insertResult(conn, platform, os_, arch, tm, passNum, totalNum, rows)


def watcher_task(conns, known):
    while True:
        time.sleep(SECONDS)
        current = {p for p in WATCH_DIR.rglob('*') if p.is_file()}
        new_files = current - known
        for f in sorted(new_files):
            processNewFile(conns, f)
        known = current


def initDir():
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    WATCH_DIR.chmod(0o777)
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conns = {}
    known = {p for p in WATCH_DIR.rglob('*') if p.is_file()}
    logger.info(f"Processing {len(known)} existing files on startup")
    for f in sorted(known):
        processNewFile(conns, f)
    return conns, known


def main():
    conns, known = initDir()
    logger.info(f"Watching {WATCH_DIR} every {SECONDS}s")
    watcher_task(conns, known)


if __name__ == '__main__':
    main()
