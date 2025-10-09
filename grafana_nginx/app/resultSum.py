#!/usr/bin/env python3
import time
import os

from pathlib import Path
import pathlib
import csv

import csv2html
import logging

logger = logging.getLogger(__name__)

CATCH2_TABLE = Path('/data/catch2Result.csv')


def getTestResult(file):
    logger.info(f"getTestResult file: {file}")
    tm = pathlib.Path(file).parent.name

    src = file
    passNum = 0
    totalNum = 0

    # 1) 读成「列表」
    with src.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)  # 默认逗号分隔
        header = next(reader)  # 首行当表头

        for row in reader:  # row 是 list
            logger.debug(row)

            if row:
                totalNum += 1
                if "pass" == row[-1]:
                    passNum += 1

    logger.info(f"{tm}, {passNum}, {totalNum}")
    return tm, passNum, totalNum


def insertOneResult(tm, passNum, totalNum):
    localCSV = CATCH2_TABLE
    with open(localCSV, 'a', newline='', encoding='utf-8') as f:
        f.write(f"{tm},{passNum},{totalNum}\n")


def switchTime(tm):
    '''switch 2025-09-22_04-03-23 to 2025-09-22 04:03:23'''
    parts = tm.replace('_', ' ').rsplit('-', 2)  # ['2025-09-22 ', '04', '03', '23']
    new_tm = f"{parts[0]}:{':'.join(parts[1:])}"
    logger.info(f"{tm}, {new_tm}")  # 2025-09-22 04:03:23
    return new_tm


def initCatch2Table(watchDir):
    tableHeader = f"time,pass,total\n"
    localCSV = CATCH2_TABLE

    known = {p for p in watchDir.rglob('*') if p.is_file()}

    with open(localCSV, "w") as csv_f:
        csv_f.write(tableHeader)

        if known:
            for f in known:
                # print(f)
                ftm, passNum, totalNum = getTestResult(f)
                ftm = switchTime(ftm)

                oneRec = f"{ftm},{passNum},{totalNum}\n"
                csv_f.write(oneRec)
                logger.debug(f"save {oneRec}")

                logger.info("switch_csv2html start")
                html_file = f"/data/details/html/report-{ftm}.html"
                csv2html.switch_csv2html(f, html_file, ftm)

    return known
