# app/ 模块说明

`app/` 下三个文件协同完成一件事：把 CI 上传的测试结果 CSV，转化为 Grafana 可读的汇总数据 + 可交互的 HTML 报告。

---

## watch_new_files.py — 主入口（文件监听器）

轮询 `/data/details/sources/` 目录，每 2 秒扫描一次，发现新文件就触发处理。

启动时做两件事：
1. 清空 `/data/details/html/`（删除旧报告）
2. 扫描 `sources/` 下所有已有文件，重建汇总 CSV 和 HTML（保证重启后数据一致）

之后进入无限循环，每次 diff（当前文件集 - 已知文件集）= 新文件，逐个处理。

---

## resultSum.py — CSV 解析 + 汇总写入

两个核心职责：

**1. 解析单次结果（`getTestResult`）**

读取 `testResult.csv`，逐行统计 `result` 列为 `pass` 的数量，返回 `(时间戳, pass数, total数)`。时间戳从文件的**父目录名**提取（如 `2026-06-23_10-00-00`）。

**2. 写入汇总（`insertOneResult`）**

把一行追加到 `/data/catch2Result.csv`，这个文件是 Grafana 趋势图的数据源：

```
2026-06-23 10:00:00,38,40
```

**时间戳格式转换（`switchTime`）：**

```
目录名  2026-06-23_10-00-00
           ↓
CSV值   2026-06-23 10:00:00
```

---

## csv2html.py — HTML 报告生成器

把单次 `testResult.csv` 渲染成自包含的交互式 HTML（无外部依赖，纯标准库）：

- 列排序（点表头升/降/清除）
- 分页（10/20/30/50 行可选）
- 全局关键字搜索（实时过滤所有列）
- `pass` 显示绿色，`failed`/`timeout` 显示红色

输出到 `/data/details/html/report-{时间戳}.html`，可通过 nginx 直接访问。

---

## 三者关系

```
watch_new_files.py          ← 调度中心
    ├── resultSum.py         ← 负责"数字"（pass/total → catch2Result.csv）
    └── csv2html.py          ← 负责"展示"（CSV → HTML 报告）
```
