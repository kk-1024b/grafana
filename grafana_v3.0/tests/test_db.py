import pytest
import db

@pytest.fixture
def conn(tmp_path):
    return db.init_db(tmp_path / 'test.db')

def test_init_creates_tables(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    assert 'runs' in tables
    assert 'test_cases' in tables

def test_insert_run_returns_id(conn):
    run_id = db.insert_run(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64', 93, 100)
    assert run_id == 1

def test_run_exists_true(conn):
    db.insert_run(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64', 93, 100)
    assert db.run_exists(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64') is True

def test_run_exists_false(conn):
    assert db.run_exists(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64') is False

def test_insert_test_cases(conn):
    run_id = db.insert_run(conn, '2026-07-07T10:00:00Z', 'tx8', 'kylin', 'amd64', 1, 2)
    rows = [
        {'Num': 1, 'module': 'mod', 'binary': 'bin', 'case': 'TestFoo::bar', 'result': 'pass'},
        {'Num': 2, 'module': 'mod', 'binary': 'bin', 'case': 'TestFoo::baz', 'result': 'FAILED'},
    ]
    db.insert_test_cases(conn, run_id, rows)
    cur = conn.execute('SELECT case_name FROM test_cases WHERE run_id=? ORDER BY num', (run_id,))
    names = [r[0] for r in cur.fetchall()]
    assert names == ['TestFoo::bar', 'TestFoo::baz']
