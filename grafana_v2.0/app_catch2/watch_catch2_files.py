#!/usr/bin/env python3
import shutil
import time
import logging
from pathlib import Path

import db
import resultSum
import csv2html

logging.basicConfig(
    level='INFO',
    format='%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

WATCH_DIR = Path('/data/details/catch2')
HTML_DIR = Path('/data/details/html')
LOGS_DIR = Path('/data/details/html/logs')
SECONDS = 2


def processNewFile(conn, f):
    logger.info(f"New file: {f}")

    if "tar.gz" in str(f):
        logger.info(f"Skipping tar.gz file: {f}")
        tm = Path(f).with_suffix("").stem
        logger.info(tm)
        ftm = resultSum.switchTime(tm)
        logger.info(ftm)
        dst = f"{LOGS_DIR}/{ftm}.tar.gz"
        shutil.move(f, dst)
        return

    if Path(f).suffix == '.json':
        tm, passNum, totalNum, rows = resultSum.getTestResultFromJson(f)
        resultSum.insertResult(conn, tm, passNum, totalNum, rows)
        html_file = HTML_DIR / f"report-{tm}.html"
        logger.info(f"json2html: {f} -> {html_file}")
        csv2html.switch_json2html(str(f), str(html_file), tm)
        return

    tm, passNum, totalNum, rows = resultSum.getTestResult(f)
    tm = resultSum.switchTime(tm)
    resultSum.insertResult(conn, tm, passNum, totalNum, rows)

    logger.info(f"csv2html: {f} -> report-{tm}.html")
    html_file = HTML_DIR / f"report-{tm}.html"
    csv2html.switch_csv2html(str(f), str(html_file), tm)


def watcher_task(conn, known):
    while True:
        time.sleep(SECONDS)
        current = {p for p in WATCH_DIR.rglob('*') if p.is_file()}
        new_files = current - known
        for f in new_files:
            processNewFile(conn, f)
        known = current


def initDir():
    WATCH_DIR.mkdir(parents=True, exist_ok=True)

    if HTML_DIR.exists():
        for item in HTML_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    else:
        HTML_DIR.mkdir(parents=True, exist_ok=True)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    conn = db.init_db()
    logger.info("Database initialized")

    known = {p for p in WATCH_DIR.rglob('*') if p.is_file()}
    logger.info(f"Processing {len(known)} existing files")
    for f in known:
        processNewFile(conn, f)

    return conn, known


def main():
    conn, known = initDir()
    logger.info(f"Watching {WATCH_DIR}, {len(known)} existing files")
    watcher_task(conn, known)


if __name__ == '__main__':
    main()
