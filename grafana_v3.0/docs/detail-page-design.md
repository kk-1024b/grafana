# Detail Page Design

## Route

```
GET /detail/<platform>/<run_id>
```

Example: `/detail/82mock/1`

Opens in a new browser tab when clicking a badge on the dashboard.

---

## Data

Flask queries `DB_DIR/<platform>.db`:

```python
# Run summary
run = conn.execute('SELECT * FROM runs WHERE id=?', (run_id,))

# All test cases for this run
cases = conn.execute(
    'SELECT num, module, binary, case_name, result FROM test_cases WHERE run_id=? ORDER BY num',
    (run_id,)
)
```

Template receives: `run` (dict), `cases` (list of dicts).

---

## Layout

### Header

```
platform / os / arch : time                 ✓ N passed  ✗ N failed  N total
```

- Single `<h1>` at 17px, bold.
- `pass` / `fail` / `total` counts come from `run.pass` and `run.total` (JSON `summary` field).

### Controls bar

```
[ Search case name... ]  [All] [Failed] [Passed only]        Page Size: [20▾]
```

- **Search**: filters by case name (substring, case-insensitive), works across all row text.
- **Filter buttons**: mutually exclusive.
  - All — show every case
  - Failed — show `result != 'pass'` (includes FAILED, timeout, error, null, etc.)
  - Passed only — show `result == 'pass'` only
- **Page Size**: 10 / 20 (default) / 50 rows per page.
- Filter + search + pagination are linked: switching any resets to page 1.

### Table

| # | module | binary | case | result |
|---|--------|--------|------|--------|
| num | module | binary | case_name | ✓ pass (green) / ✗ FAILED (red) |

- Rows with non-pass result have class `fail-row` → light red background (`#fff8f8`).
- Hover: pass rows → `#f8f9fa`; fail rows → `#fff0f0`.
- `data-result` attribute holds the raw result string (`pass`, `FAILED`, `timeout`, etc.).  
  Null DB values are guarded with `or ''` to prevent the string "None" appearing.

### Pagination bar (inside table card)

```
‹ Prev     1 / 4     Next ›
```

- Prev/Next disabled at boundaries.
- When filter/search returns 0 rows: table shows a centered **"No results found"** row instead of a blank page.

---

## Behavior Notes

- All filtering and pagination is client-side JS — no additional server requests.
- `render()` is called on page load with defaults (filter=All, page=1, pageSize=20).
- Jinja2 template cache: `docker restart dt_v3` required after template file changes.

---

## Files

| File | Role |
|------|------|
| `app_web/templates/detail.html` | Template (HTML + inline CSS + JS) |
| `app_web/web.py` → `detail_page()` | Flask route, DB query |

---

## Known Fixes Applied (from code review)

| Issue | Fix |
|---|---|
| `tr.fail-row` CSS was dead | `<tr>` now gets `class="fail-row"` for non-pass rows |
| `data-result` rendered Python None as string "None" | `{{ c.result or '' }}` guard added |
| No empty-state when filter returns 0 rows | "No results found" row injected by `render()` |
| Dead `.header .meta` CSS rule | Removed |
| Redundant `td.case { font-size: 14px }` rule | Removed |
