#!/usr/bin/env python3
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _switch_time(tm):
    '''2026-05-22_10-10-32 -> 2026-05-22T10:10:32Z (RFC3339)'''
    parts = tm.replace('_', 'T').rsplit('-', 2)
    return f"{parts[0]}:{':'.join(parts[1:])}Z"


def parse_json(file):
    with Path(file).open(encoding='utf-8') as f:
        data = json.load(f)

    date_raw = data.get('date', '')
    date = _switch_time(date_raw) if date_raw else ''
    author = data.get('auther', '')
    host_srv = data.get('hostSrv', '')
    benchmarks = data.get('benchmarks', [])

    logger.info(f"Parsed {file}: date={date} author={author} host={host_srv} benchmarks={len(benchmarks)}")
    return date, author, host_srv, benchmarks
