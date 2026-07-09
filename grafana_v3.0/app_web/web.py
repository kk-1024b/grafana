#!/usr/bin/env python3
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, str(Path(__file__).parent.parent / 'app_catch2'))

DB_DIR = Path(os.environ.get('DB_DIR', '/data/platforms'))

app = Flask(__name__)

CST = timezone(timedelta(hours=8))

@app.template_filter('utc_to_cst')
def utc_to_cst(s):
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt.astimezone(CST).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return s


PIVOT_SQL = """
SELECT r.platform, r.os, r.arch,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-9 day') THEN r.id END) AS d9_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-9 day') THEN r.pass||'/'||r.total END) AS d9,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-8 day') THEN r.id END) AS d8_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-8 day') THEN r.pass||'/'||r.total END) AS d8,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-7 day') THEN r.id END) AS d7_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-7 day') THEN r.pass||'/'||r.total END) AS d7,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-6 day') THEN r.id END) AS d6_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-6 day') THEN r.pass||'/'||r.total END) AS d6,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-5 day') THEN r.id END) AS d5_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-5 day') THEN r.pass||'/'||r.total END) AS d5,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-4 day') THEN r.id END) AS d4_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-4 day') THEN r.pass||'/'||r.total END) AS d4,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-3 day') THEN r.id END) AS d3_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-3 day') THEN r.pass||'/'||r.total END) AS d3,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-2 day') THEN r.id END) AS d2_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-2 day') THEN r.pass||'/'||r.total END) AS d2,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-1 day') THEN r.id END) AS d1_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours','-1 day') THEN r.pass||'/'||r.total END) AS d1,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours')          THEN r.id END) AS d0_id,
  MAX(CASE WHEN date(r.time,'+8 hours')=date('now','+8 hours')          THEN r.pass||'/'||r.total END) AS d0
FROM runs r
JOIN (
    SELECT platform, os, arch, date(time,'+8 hours') AS day, MAX(time) AS latest_time
    FROM runs
    GROUP BY platform, os, arch, date(time,'+8 hours')
) l ON r.platform=l.platform AND r.os=l.os AND r.arch=l.arch
    AND date(r.time,'+8 hours')=l.day AND r.time=l.latest_time
WHERE date(r.time,'+8 hours') >= date('now', '+8 hours', '-9 day')
GROUP BY r.platform, r.os, r.arch
ORDER BY r.platform, r.os, r.arch
"""


def pivot_query():
    today = datetime.now(CST).date()
    days = [today - timedelta(days=i) for i in range(9, -1, -1)]
    all_rows = []
    if not DB_DIR.exists():
        return all_rows, days
    for db_file in sorted(DB_DIR.glob('*.db')):
        try:
            conn = sqlite3.connect(str(db_file))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(PIVOT_SQL).fetchall()
            all_rows.extend([dict(r) for r in rows])
            conn.close()
        except Exception as e:
            app.logger.warning(f"Skipping {db_file.name}: {e}")
    all_rows.sort(key=lambda r: (r['platform'], r['os'], r['arch']))
    return all_rows, days


@app.route('/')
def index():
    rows, days = pivot_query()
    return render_template('index.html', rows=rows, days=days)


@app.route('/detail/<platform>/<int:run_id>')
def detail_page(platform, run_id):
    db_file = DB_DIR / f'{platform}.db'
    if not db_file.exists():
        return f'DB not found for platform: {platform}', 404
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    run = conn.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    if not run:
        conn.close()
        return f'Run {run_id} not found', 404
    cases = conn.execute(
        'SELECT num, module, binary, case_name, result FROM test_cases WHERE run_id=? ORDER BY num',
        (run_id,)
    ).fetchall()
    conn.close()
    return render_template('detail.html', run=dict(run), cases=[dict(c) for c in cases])


@app.route('/platform/<platform>')
def platform_page(platform):
    os   = request.args.get('os',   '')
    arch = request.args.get('arch', '')
    db_file = DB_DIR / f'{platform}.db'
    if not db_file.exists():
        return f'DB not found for platform: {platform}', 404
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT id, time, pass, total FROM runs '
        'WHERE os=? AND arch=? ORDER BY time DESC',
        (os, arch)
    ).fetchall()
    conn.close()
    runs = []
    for r in rows:
        d = dict(r)
        d['time_cst'] = utc_to_cst(d['time'])
        d['pass_rate'] = round(d['pass'] / d['total'] * 100, 1) if d['total'] else 0
        runs.append(d)
    chart_runs = list(reversed(runs))
    cutoff = (datetime.now(CST) - timedelta(days=60)).date()
    chart_runs = [r for r in chart_runs if datetime.fromisoformat(r['time_cst']).date() >= cutoff]
    return render_template(
        'platform.html',
        platform=platform, os=os, arch=arch,
        runs=runs, chart_runs=chart_runs
    )


@app.route('/api/detail')
def detail():
    run_id   = request.args.get('run_id', type=int)
    platform = request.args.get('platform', '')
    if not run_id or not platform:
        return jsonify([])
    db_file = DB_DIR / f'{platform}.db'
    if not db_file.exists():
        return jsonify([])
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cases = conn.execute(
        "SELECT case_name, result FROM test_cases "
        "WHERE run_id=? AND result!='pass' ORDER BY num",
        (run_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(c) for c in cases])


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=False)
