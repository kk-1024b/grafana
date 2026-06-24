# Grafana 仪表盘设计

## 数据源配置

插件：`frser-sqlite-datasource`

在 Grafana → Configuration → Data Sources 中添加 SQLite 数据源：
- **Name**：`test_results`
- **Path**：`/data/test_results.db`

---

## Dashboard 结构

两个独立 Dashboard：

```
主 Dashboard（趋势）                详情 Dashboard
┌─────────────────────┐    点击     ┌──────────────────────────┐
│  趋势图：pass/total  │  ────────▶ │  变量：run_id（URL 传入） │
│  点击数据点 →        │            ├──────────────────────────┤
│  跳转详情页          │            │  明细表：该次运行所有用例  │
└─────────────────────┘            └──────────────────────────┘
```

---

## 主 Dashboard（趋势图）

### 趋势图面板（Time series）

```sql
SELECT time, pass, total, id FROM runs ORDER BY time
```

### Data link（点击跳转详情页）

Panel → Data links → Add link：

| 字段 | 值 |
|------|-----|
| Title | `查看详情` |
| URL | `/d/<detail-dashboard-uid>?var-run_id=${__data.fields.id}` |
| Open in new tab | 推荐开启 |

`<detail-dashboard-uid>` 替换为详情 Dashboard 的 UID（创建后从 URL 获取）。

---

## 详情 Dashboard（独立页面）

### 1. 创建变量 `run_id`

Dashboard Settings → Variables → New Variable：

| 字段 | 值 |
|------|-----|
| Type | Query |
| Name | `run_id` |
| Data source | `test_results` |
| Query | `SELECT id \|\| ' - ' \|\| time AS __text, id AS __value FROM runs ORDER BY time DESC` |

变量支持两种来源：
- URL 参数自动填入（从主 Dashboard 跳转时）
- 手动下拉选择

### 2. 标题面板（Text）

显示当前运行时间，SQL Panel 类型：

```sql
SELECT time AS '运行时间', pass AS '通过', total AS '总计',
       ROUND(pass * 100.0 / total, 1) || '%' AS '通过率'
FROM runs WHERE id = $run_id
```

### 3. 明细表面板（Table）

```sql
SELECT num, module, binary, case_name, result
FROM test_cases
WHERE run_id = $run_id
ORDER BY num
```

**列着色（Overrides）：**

Panel → Overrides → `result` 字段：
- Value mappings：`pass` → 绿色，`failed` → 红色，`timeout` → 橙色

---

## 常用 SQL 参考

```sql
-- 趋势图
SELECT time, pass, total FROM runs ORDER BY time

-- 明细表（绑定变量）
SELECT num, module, binary, case_name, result
FROM test_cases WHERE run_id = $run_id

-- 变量数据源
SELECT id || ' - ' || time AS __text, id AS __value
FROM runs ORDER BY time DESC

-- 统计某次运行通过率
SELECT
    r.time,
    r.pass,
    r.total,
    ROUND(r.pass * 100.0 / r.total, 1) AS pass_rate
FROM runs r
WHERE r.id = $run_id

-- 查询失败用例
SELECT num, module, binary, case_name, result
FROM test_cases
WHERE run_id = $run_id AND result != 'pass'
```
