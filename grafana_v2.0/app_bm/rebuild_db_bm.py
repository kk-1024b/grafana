#!/usr/bin/env python3
"""Rebuild the SQLite DB from scratch using all existing benchmark JSON files."""
import argparse
import glob
import os
import sys
from pathlib import Path

import db_bm
import bm_parser

DEFAULT_SOURCE_DIR = '/data/details/benchmark'
DEFAULT_DB_PATH = '/data/benchmark_results.db'


def main():
    parser = argparse.ArgumentParser(description='Rebuild benchmark_results.db from source JSON files.')
    parser.add_argument('--source-dir', default=DEFAULT_SOURCE_DIR,
                        help=f'Root directory containing timestamped subdirs (default: {DEFAULT_SOURCE_DIR})')
    parser.add_argument('--db-path', default=DEFAULT_DB_PATH,
                        help=f'Output DB file path (default: {DEFAULT_DB_PATH})')
    args = parser.parse_args()

    source_dir = args.source_dir
    db_path = Path(args.db_path)

    json_files = sorted(
        glob.glob(os.path.join(source_dir, '**/*.json'), recursive=True),
        key=lambda f: Path(f).parent.name
    )

    if not json_files:
        print(f'No JSON files found under {source_dir}')
        sys.exit(0)

    if db_path.exists():
        db_path.unlink()
        print(f'Removed existing DB: {db_path}')

    conn = db_bm.init_db(db_path)
    print(f'Initialized DB: {db_path}')
    print(f'Found {len(json_files)} JSON file(s). Starting rebuild...\n')

    ok = 0
    for i, f in enumerate(json_files, 1):
        try:
            date, author, host_srv, benchmarks = bm_parser.parse_json(f)
            run_id = db_bm.insert_run(conn, date, author, host_srv)
            db_bm.insert_benchmarks(conn, run_id, benchmarks)
            print(f'[{i}/{len(json_files)}] OK  {f}  ({len(benchmarks)} benchmarks)')
            ok += 1
        except Exception as e:
            print(f'[{i}/{len(json_files)}] SKIP {f}  ({e})')

    conn.close()
    print(f'\nDone. {ok}/{len(json_files)} file(s) imported into {db_path}')


if __name__ == '__main__':
    main()
