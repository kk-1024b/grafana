#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB_PATH = Path('/data/benchmark_results.db')


def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            date     TEXT NOT NULL,
            author   TEXT,
            host_srv TEXT
        );

        CREATE TABLE IF NOT EXISTS benchmarks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     INTEGER NOT NULL REFERENCES runs(id),
            name       TEXT,
            run_name   TEXT,
            run_type   TEXT,
            threads    INTEGER,
            iterations INTEGER,
            real_time  REAL,
            cpu_time   REAL,
            time_unit  TEXT,
            metrics    REAL,
            size       REAL
        );
    """)
    conn.commit()
    return conn


def insert_run(conn, date, author, host_srv):
    cur = conn.execute(
        'INSERT INTO runs (date, author, host_srv) VALUES (?, ?, ?)',
        (date, author, host_srv)
    )
    conn.commit()
    return cur.lastrowid


def insert_benchmarks(conn, run_id, benchmarks):
    conn.executemany(
        'INSERT INTO benchmarks '
        '(run_id, name, run_name, run_type, threads, iterations, '
        ' real_time, cpu_time, time_unit, metrics, size) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            (
                run_id,
                b.get('name'),
                b.get('run_name'),
                b.get('run_type'),
                b.get('threads'),
                b.get('iterations'),
                b.get('real_time'),
                b.get('cpu_time'),
                b.get('time_unit'),
                b.get('Metrics'),
                b.get('size'),
            )
            for b in benchmarks
        ]
    )
    conn.commit()
