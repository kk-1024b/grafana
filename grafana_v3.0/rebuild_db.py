#!/usr/bin/env python3
"""
Seed per-platform SQLite DBs from a directory of JSON result files.

Usage:
    python3 rebuild_db.py <json_dir> [--db-dir <path>]

Examples:
    python3 rebuild_db.py demo/
    python3 rebuild_db.py demo/ --db-dir /home/kk/catch2_data/data/platforms
"""
import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level='INFO',
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE / 'app_catch2'))  # expose app_catch2/ modules without packaging

import db          # app_catch2/db.py        — SQLite schema + CRUD (init_db, insert_run, ...)
import resultSum   # app_catch2/resultSum.py  — JSON parser + insertResult()


def main():
    parser = argparse.ArgumentParser(description='Seed platform DBs from JSON result files')
    parser.add_argument('json_dir', help='Directory containing *.json result files')
    parser.add_argument('--db-dir', default='/data/platforms', help='Directory for platform DB files (default: /data/platforms)')
    args = parser.parse_args()

    json_dir = Path(args.json_dir)
    db_dir   = Path(args.db_dir)

    if not json_dir.is_dir():
        logger.error(f"Not a directory: {json_dir}")
        sys.exit(1)

    if not db_dir.exists():
        logger.warning(f"DB dir does not exist, creating: {db_dir}")
    db_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(json_dir.rglob('*.json'))
    if not files:
        logger.warning(f"No JSON files found in {json_dir}")
        sys.exit(1)

    conns   = {}
    inserted = 0

    try:
        for f in files:
            logger.info(f"Processing: {f}")
            try:
                platform, os_, arch, tm, passNum, totalNum, rows = resultSum.getTestResultFromJson(str(f))
            except Exception as e:
                logger.warning(f"Skipping {f.name}: {e}")
                continue

            if not platform:
                logger.warning(f"Skipping {f.name}: platform is empty")
                continue

            if platform not in conns:
                db_path = db_dir / f'{platform}.db'
                conns[platform] = db.init_db(db_path)
                logger.info(f"Opened DB: {db_path}")

            run_id = resultSum.insertResult(conns[platform], platform, os_, arch, tm, passNum, totalNum, rows)
            if run_id:
                logger.info(f"  → inserted run_id={run_id}  {platform}/{os_}/{arch}  {passNum}/{totalNum}")
                inserted += 1
            else:
                logger.info(f"  → duplicate, skipped")

    finally:
        for conn in conns.values():
            conn.close()

    logger.info(f"Done. {inserted} run(s) inserted into {db_dir}/")
    if inserted == 0:
        logger.warning("No new runs were inserted — all files were duplicates or failed to parse")
        sys.exit(1)


if __name__ == '__main__':
    main()
