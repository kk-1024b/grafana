#!/usr/bin/env python3
"""Rebuild the SQLite DB from scratch using all existing CSV source files."""
import argparse
import glob
import os
import sys
from pathlib import Path

import db
import resultSum

DEFAULT_SOURCE_DIR = '/data/details/catch2'
DEFAULT_DB_PATH = '/data/test_results.db'


def main():
    parser = argparse.ArgumentParser(description='Rebuild test_results.db from source CSV files.')
    parser.add_argument('--source-dir', default=DEFAULT_SOURCE_DIR,
                        help=f'Root directory containing timestamped subdirs (default: {DEFAULT_SOURCE_DIR})')
    parser.add_argument('--db-path', default=DEFAULT_DB_PATH,
                        help=f'Output DB file path (default: {DEFAULT_DB_PATH})')
    args = parser.parse_args()

    source_dir = args.source_dir
    db_path = Path(args.db_path)

    csv_files = sorted(
        glob.glob(os.path.join(source_dir, '**/testResult.csv'), recursive=True),
        key=lambda f: Path(f).parent.name
    )

    if not csv_files:
        print(f'No testResult.csv files found under {source_dir}')
        sys.exit(0)

    if db_path.exists():
        db_path.unlink()
        print(f'Removed existing DB: {db_path}')

    conn = db.init_db(db_path)
    print(f'Initialized DB: {db_path}')
    print(f'Found {len(csv_files)} CSV file(s). Starting rebuild...\n')

    ok = 0
    for i, f in enumerate(csv_files, 1):
        try:
            tm, pass_num, total_num, rows = resultSum.getTestResult(f)
            time_str = resultSum.switchTime(tm)
            resultSum.insertResult(conn, time_str, pass_num, total_num, rows)
            print(f'[{i}/{len(csv_files)}] OK  {f}  ({pass_num}/{total_num})')
            ok += 1
        except Exception as e:
            print(f'[{i}/{len(csv_files)}] SKIP {f}  ({e})')

    conn.close()
    print(f'\nDone. {ok}/{len(csv_files)} file(s) imported into {db_path}')


if __name__ == '__main__':
    main()
