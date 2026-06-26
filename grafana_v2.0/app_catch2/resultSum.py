#!/usr/bin/env python3
import csv
import pathlib
import logging
from datetime import datetime, timezone

import db

logger = logging.getLogger(__name__)


def getTestResult(file):
    logger.info(f"getTestResult file: {file}")
    tm = pathlib.Path(file).parent.name

    passNum = 0
    totalNum = 0
    rows = []

    with pathlib.Path(file).open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row:
                totalNum += 1
                if row.get('result') == 'pass':
                    passNum += 1
                rows.append(dict(row))

    logger.info(f"{tm}, {passNum}/{totalNum}")
    return tm, passNum, totalNum, rows


def switchTime(tm):
    '''switch 2025-09-22_04-03-23 to 2025-09-22T04:03:23Z (RFC3339)'''
    parts = tm.replace('_', 'T').rsplit('-', 2)
    new_tm = f"{parts[0]}:{':'.join(parts[1:])}Z"
    logger.info(f"{tm} -> {new_tm}")
    return new_tm


def insertResult(conn, time, passNum, totalNum, rows):
    if db.run_exists(conn, time):
        logger.info(f"Run already in DB, skipping: {time}")
        return None
    run_id = db.insert_run(conn, time, passNum, totalNum)
    db.insert_test_cases(conn, run_id, rows)
    logger.info(f"Inserted run_id={run_id} time={time} {passNum}/{totalNum} cases={len(rows)}")
    return run_id
