#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standard-library only -> Excel-like column sorting (no filters) + paging + highlight + HTML timestamp
CSV columns: Num,module,binary,case,result
"""
import csv
import json
import html
import os
import sys
import logging

logger = logging.getLogger(__name__)


CSV_FILE = 'input.csv'
HTML_FILE = 'report_no_pandas.html'
PAGE_SIZE = 20
TEST_TIME = f"2025-09-28 17:22:31"


def escape(s):
    return html.escape(str(s))


def build_html(rows, tm: str, pagesize: int = 20):
    if not rows:
        headers = ['Num', 'module', 'binary', 'case', 'result']
        data = []
    else:
        headers = list(rows[0].keys())
        data = rows
    js_data = json.dumps(data, ensure_ascii=False)
    now = tm

    template = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>CSV Report - {now}</title>
<meta name="generated" content="{now}">
<style>
body{{font-family:Arial,Helvetica,sans-serif;margin:20px;font-size:14px}}
h2{{margin-top:0}}
#globalBox{{margin-bottom:10px}}
#globalBox input{{width:200px;padding:4px}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:4px 8px;text-align:left}}
th{{background:#f2f2f2;position:relative;cursor:pointer;user-select:none;white-space:nowrap}}
.pass{{color:green;font-weight:bold}}
.fail{{color:red;font-weight:bold}}
.sort-arrow{{font-size:10px;margin-left:4px;color:#666}}
.pagination{{margin-top:10px}}
.pagination button{{margin:0 3px;padding:4px 8px}}
</style>
</head>
<body>

<h2>Daily Test: {now}</h2>

<div id="globalBox">
  Global search: <input id="globalSearch" placeholder="keyword (any column)" onkeyup="doGlobalSearch()">
  Page size
  <select id="pageSizeSel" onchange="changePageSize()">
    <option value="10">10</option>
    <option value="20" selected>20</option>
    <option value="30">30</option>
    <option value="50">50</option>
  </select>
</div>

<table id="dataTable">
  <thead><tr>{thead}</tr></thead>
  <tbody id="tb"></tbody>
</table>

<div class="pagination" id="pageBar"></div>

<script>
const rawData = {js_data};
let viewData   = rawData.slice();
let curPage    = 1;
let pageSize   = {pagesize};
let sortState  = {{}};
const headers = {js_headers};

headers.forEach(h => sortState[h] = null);

function render() {{
    const tbody = document.getElementById('tb');
    tbody.innerHTML = '';
    const start = (curPage - 1) * pageSize;
    const end   = start + pageSize;
    const pageItems = viewData.slice(start, end);
    pageItems.forEach(row => {{
        let tr = '<tr>';
        headers.forEach(k => {{
            let v = row[k];
            let cls = (k === 'result') ? (v.toLowerCase() === 'pass' ? 'pass' : 'fail') : '';
            tr += `<td class="${{cls}}">${{v}}</td>`;
        }});
        tr += '</tr>';
        tbody.insertAdjacentHTML('beforeend', tr);
    }});
    const total = Math.ceil(viewData.length / pageSize) || 1;
    document.getElementById('pageBar').innerHTML =
        `<button onclick="prevPage()" ${{curPage === 1 ? 'disabled' : ''}}>Prev</button>
         <span>${{curPage}} / ${{total}}</span>
         <button onclick="nextPage()" ${{curPage === total ? 'disabled' : ''}}>Next</button>`;
}}

function sortTable(col) {{
    const cur = sortState[col];
    let dir = 'asc';
    if (cur === 'asc') dir = 'desc';
    else if (cur === 'desc') dir = null;
    headers.forEach(h => sortState[h] = null);
    sortState[col] = dir;
    headers.forEach(h => {{
        const arrow = document.getElementById(`arrow-${{h}}`);
        arrow.textContent = '';
    }});
    if (dir) {{
        document.getElementById(`arrow-${{col}}`).textContent = dir === 'asc' ? ' ▲' : ' ▼';
    }}
    if (!dir) viewData = rawData.slice();
    else {{
        viewData.sort((a, b) => {{
            let va = a[col], vb = b[col];
            if (!isNaN(va) && !isNaN(vb)) return dir === 'asc' ? (+va) - (+vb) : (+vb) - (+va);
            return dir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
        }});
    }}
    curPage = 1;
    render();
}}

function doGlobalSearch() {{
    const kw = document.getElementById('globalSearch').value.trim().toLowerCase();
    if (!kw) {{ viewData = rawData.slice(); }}
    else {{ viewData = rawData.filter(r => Object.values(r).some(v => String(v).toLowerCase().includes(kw))); }}
    curPage = 1;
    render();
}}

function changePageSize() {{
    pageSize = Number(document.getElementById('pageSizeSel').value);
    curPage = 1;
    render();
}}
function prevPage() {{ if (curPage > 1) {{ curPage--; render(); }} }}
function nextPage() {{ const max = Math.ceil(viewData.length / pageSize); if (curPage < max) {{ curPage++; render(); }} }}

render();
</script>
</body>
</html>"""

    # 6. dynamic header (sort only, no filter button)
    thead = '\n'.join(
        [
            f'    <th onclick="sortTable(\'{h}\')">{escape(h)}'
            f'<span id="arrow-{h}" class="sort-arrow"></span></th>'
            for h in headers
        ]
    )
    return template.format(
        now=now,  # timestamp injected
        pagesize=pagesize,
        js_data=json.dumps(data, ensure_ascii=False),
        js_headers=json.dumps(headers),
        thead=thead,
    )


def switch_csv2html(csv_file, html_file, test_time):
    logger.info(
        f"\n\nswitch_csv2html: csv:{csv_file} \nhtml:{html_file} \ntest_time:{test_time}\n\n"
    )
    if not os.path.isfile(csv_file):
        logger.info(f"❌  {csv_file} not found")
        sys.exit(1)
    with open(csv_file, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    if not rows:
        logger.info("❌  CSV is empty")
        sys.exit(1)
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(build_html(rows, test_time))

    logger.info(f"✅  Generated {html_file}  ({len(rows)} rows)")


def initHtmlDir(dir_path):
    return


if __name__ == '__main__':
    switch_csv2html(CSV_FILE, HTML_FILE, TEST_TIME)
