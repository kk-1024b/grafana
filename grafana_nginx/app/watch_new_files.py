#!/usr/bin/env python3
import time
import os
import shutil
from pathlib import Path

# import pathlib
# import csv

import resultSum

import csv2html
import logging

logging.basicConfig(
    level='INFO',
    format='%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

WATCH_DIR = Path('/data/details/sources')  # watcher path
SECONDS = 2  # sleep time, sec
HTML_DIR = "/data/details/html"


def readNewFile(f):
    logging.info(f)
    ftm, passNum, totalNum = resultSum.getTestResult(f)
    ftm = resultSum.switchTime(ftm)
    resultSum.insertOneResult(ftm, passNum, totalNum)

    #
    logging.debug("csv2html.switch_csv2html")
    html_file = f"{HTML_DIR}/report-{ftm}.html"
    csv2html.switch_csv2html(f, html_file, ftm)
    return


def watcher_task(known):
    while True:
        time.sleep(SECONDS)
        current = {p for p in WATCH_DIR.rglob('*') if p.is_file()}
        new_files = current - known
        if new_files:
            # print('>>> new file:')
            for f in new_files:
                readNewFile(f)

        known = current  # update base


def initHtmlDir():
    p = Path(HTML_DIR)
    if not p.exists():
        p.mkdir(parents=True)
        return

    if not p.is_dir():
        return
    for item in p.iterdir():
        if item.is_file():
            item.unlink()
        else:
            shutil.rmtree(item)  # 递归删子目录


def main():
    initHtmlDir()
    known = resultSum.initCatch2Table(WATCH_DIR)

    watcher_task(known)


if __name__ == '__main__':
    main()
