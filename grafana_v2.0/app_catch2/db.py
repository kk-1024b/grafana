#!/usr/bin/env python3
import sqlite3
from pathlib import Path

DB_PATH = Path('/data/test_results.db')


def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            time  TEXT    NOT NULL,
            pass  INTEGER NOT NULL,
            total INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS test_cases (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id    INTEGER NOT NULL REFERENCES runs(id),
            num       INTEGER,
            module    TEXT,
            binary    TEXT,
            case_name TEXT,
            result    TEXT
        );
    """)
    conn.commit()
    return conn


def run_exists(conn, time):
    cur = conn.execute('SELECT 1 FROM runs WHERE time = ? LIMIT 1', (time,))
    return cur.fetchone() is not None


def insert_run(conn, time, pass_, total):
    cur = conn.execute(
        'INSERT INTO runs (time, pass, total) VALUES (?, ?, ?)',
        (time, pass_, total)
    )
    conn.commit()
    return cur.lastrowid


def insert_test_cases(conn, run_id, rows):
    conn.executemany(
        'INSERT INTO test_cases (run_id, num, module, binary, case_name, result) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        [
            (run_id, row.get('Num'), row.get('module'), row.get('binary'),
             row.get('case'), row.get('result'))
            for row in rows
        ]
    )
    conn.commit()
