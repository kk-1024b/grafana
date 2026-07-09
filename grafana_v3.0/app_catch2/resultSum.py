#!/usr/bin/env python3
import json
import logging

import db

logger = logging.getLogger(__name__)


def getTestResultFromJson(file):
    with open(file, encoding='utf-8') as f:
        data = json.load(f)
    platform = data.get('platform') or ''
    os_      = data.get('os')       or ''
    arch     = data.get('arch')     or ''
    tm       = data['time'].replace(' ', 'T') + 'Z'
    passNum  = data['summary']['pass']
    totalNum = data['summary']['total']
    rows = [{**{k: v for k, v in r.items() if k != 'num'}, 'Num': r['num']}
            for r in data['results']]
    return platform, os_, arch, tm, passNum, totalNum, rows


def insertResult(conn, platform, os_, arch, time, passNum, totalNum, rows):
    if db.run_exists(conn, time, platform, os_, arch):
        logger.info(f"Skipping duplicate: {time} {platform}/{os_}/{arch}")
        return None
    run_id = db.insert_run(conn, time, platform, os_, arch, passNum, totalNum)
    db.insert_test_cases(conn, run_id, rows)
    return run_id
