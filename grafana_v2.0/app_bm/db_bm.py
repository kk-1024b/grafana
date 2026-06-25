#!/usr/bin/env python3
import re
import sqlite3
from pathlib import Path

DB_PATH = Path('/data/benchmark_results.db')


def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def _safe(name):
    return re.sub(r'[^\w]', '_', name)


def ensure_table(conn, name):
    safe = _safe(name)
    conn.execute(f'''
        CREATE TABLE IF NOT EXISTS "{safe}" (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT NOT NULL,
            host_srv   TEXT,
            author     TEXT,
            size       REAL,
            real_time  REAL,
            cpu_time   REAL,
            time_unit  TEXT,
            metrics    REAL,
            iterations INTEGER
        )
    ''')


def insert_benchmark(conn, name, date, host_srv, author, bm):
    ensure_table(conn, name)
    safe = _safe(name)
    conn.execute(
        f'INSERT INTO "{safe}" '
        '(date, host_srv, author, size, real_time, cpu_time, time_unit, metrics, iterations) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        (date, host_srv, author,
         bm.get('size'), bm.get('real_time'), bm.get('cpu_time'),
         bm.get('time_unit'), bm.get('Metrics'), bm.get('iterations'))
    )
    conn.commit()
