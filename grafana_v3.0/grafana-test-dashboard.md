# Grafana 测试结果看板 — 部署指南（Ubuntu）

## 前提条件

- 已有 Docker 镜像，内置 `frser-sqlite-datasource` 插件
- SQLite 数据库路径：`/app/matrix.db`（容器内）
- 表结构：`test_result(platform, os, arch, test_day, pass, total, update_time)`

---

## 1. 在项目目录下创建新文件

假设你的 Docker 项目根目录为 `~/myproject/`，以下所有路径均相对于此。

### 1.1 创建目录

```bash
mkdir -p conf/grafana/datasources
mkdir -p conf/grafana/dashboards
mkdir -p scripts
```

### 1.2 数据源配置

**文件：`conf/grafana/datasources/sqlite.yaml`**

```yaml
apiVersion: 1
datasources:
  - name: SQLite
    type: frser-sqlite-datasource
    uid: sqlite_ds
    jsonData:
      path: /app/matrix.db
```

### 1.3 Dashboard Provider 配置

**文件：`conf/grafana/dashboards/provider.yaml`**

```yaml
apiVersion: 1
providers:
  - name: default
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards
```

### 1.4 Dashboard 模板 JSON

**文件：`conf/grafana/dashboards/test-results-template.json`**

```json
{
  "title": "测试结果看板",
  "uid": "test-results",
  "panels": [
    {
      "type": "table",
      "title": "测试结果汇总（最近7天）",
      "gridPos": {"h": 20, "w": 24, "x": 0, "y": 0},
      "datasource": {"type": "frser-sqlite-datasource", "uid": "sqlite_ds"},
      "targets": [
        {
          "rawQueryText": "SELECT platform, os, arch, MAX(CASE WHEN test_day = date('now','-6 day') THEN pass||'/'||total END) AS d6, MAX(CASE WHEN test_day = date('now','-5 day') THEN pass||'/'||total END) AS d5, MAX(CASE WHEN test_day = date('now','-4 day') THEN pass||'/'||total END) AS d4, MAX(CASE WHEN test_day = date('now','-3 day') THEN pass||'/'||total END) AS d3, MAX(CASE WHEN test_day = date('now','-2 day') THEN pass||'/'||total END) AS d2, MAX(CASE WHEN test_day = date('now','-1 day') THEN pass||'/'||total END) AS d1, MAX(CASE WHEN test_day = date('now') THEN pass||'/'||total END) AS d0 FROM test_result WHERE test_day >= date('now','-6 day') GROUP BY platform, os, arch ORDER BY platform, os, arch",
          "queryType": "table"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "custom": {"width": 90, "align": "center"},
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "red", "value": null},
              {"color": "yellow", "value": 90},
              {"color": "green", "value": 95}
            ]
          }
        },
        "overrides": []
      },
      "options": {
        "sortBy": [{"displayName": "platform"}, {"displayName": "os"}, {"displayName": "arch"}]
      }
    }
  ],
  "schemaVersion": 39,
  "version": 1,
  "refresh": "5m",
  "time": {"from": "now-7d", "to": "now"}
}
```

### 1.5 日期列标题生成脚本

**文件：`scripts/gen_dashboard.py`**

```python
#!/usr/bin/env python3
import json
from datetime import date, timedelta

TEMPLATE = "/etc/grafana/provisioning/dashboards/test-results-template.json"
OUTPUT   = "/etc/grafana/provisioning/dashboards/test-results.json"

today = date.today()

overrides = []
for offset in range(6, -1, -1):   # d6 最旧 → d0 今日
    alias = f"d{offset}"
    d = today - timedelta(days=offset)
    label = f"{d.month}月{d.day}日"
    props = [{"id": "displayName", "value": label}]
    if offset == 0:                # 今日列蓝色高亮
        props += [
            {"id": "custom.displayMode", "value": "color-background"},
            {"id": "color", "value": {"mode": "fixed", "fixedColor": "#1F60C4"}}
        ]
    overrides.append({
        "matcher": {"id": "byName", "options": alias},
        "properties": props
    })

with open(TEMPLATE) as f:
    dash = json.load(f)

dash["panels"][0]["fieldConfig"]["overrides"] = overrides

with open(OUTPUT, "w") as f:
    json.dump(dash, f, ensure_ascii=False, indent=2)

print(f"Dashboard generated for {today}")
```

---

## 2. 修改 Dockerfile

在原 Dockerfile 中找到以下内容并按说明修改：

### 2.1 在 `COPY conf/...` 附近新增 3 行 COPY

```dockerfile
# 新增（放在其他 COPY 语句附近）
COPY conf/grafana/datasources  /etc/grafana/provisioning/datasources/
COPY conf/grafana/dashboards   /etc/grafana/provisioning/dashboards/
COPY scripts/gen_dashboard.py  /app/gen_dashboard.py
```

### 2.2 修改 CMD（最后一行）

```dockerfile
# 原来
CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/all.conf"]

# 改为
CMD python3 /app/gen_dashboard.py && /usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
```

---

## 3. 构建并运行

```bash
# 构建镜像
docker build -t myproject:latest .

# 运行容器（根据你原有的 run 命令调整端口和 volume）
docker run -d \
  -p 3000:3000 \
  -p 8080:8080 \
  --name myproject \
  myproject:latest
```

---

## 4. 验证

```bash
# 查看 gen_dashboard.py 是否成功执行
docker logs myproject | head -5

# 进入容器手动检查生成的 JSON
docker exec myproject cat /etc/grafana/provisioning/dashboards/test-results.json | python3 -m json.tool | head -20

# 验证 SQLite 数据可查询
docker exec myproject sqlite3 /app/matrix.db \
  "SELECT platform, os, arch, test_day, pass, total FROM test_result LIMIT 5;"
```

打开浏览器访问 `http://<your-host>:3000`，在 Dashboards 菜单中找到 **测试结果看板**。

---

## 5. 每日刷新列标题（可选 cron）

容器每次重启会自动重新生成列标题。如果容器长期不重启，可加一条 cron：

```bash
# 宿主机上，每天凌晨 00:05 刷新
echo "5 0 * * * docker exec myproject python3 /app/gen_dashboard.py" | crontab -
```

或在容器内手动触发：

```bash
docker exec myproject python3 /app/gen_dashboard.py
```

Grafana 会**自动热加载**，无需重启进程。

---

## 6. 变动文件汇总

| 操作 | 文件 |
|---|---|
| 新增 | `conf/grafana/datasources/sqlite.yaml` |
| 新增 | `conf/grafana/dashboards/provider.yaml` |
| 新增 | `conf/grafana/dashboards/test-results-template.json` |
| 新增 | `scripts/gen_dashboard.py` |
| 修改 | `Dockerfile` — 加 3 行 COPY + 改 CMD 最后一行 |
