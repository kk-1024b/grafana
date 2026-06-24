# grafana_v2.0 构建说明

## 概述

本目录将原有三个 Docker 容器（nginx、Python watcher、Grafana）合并为单一镜像，使用 `supervisord` 在容器内同时管理三个进程。

```
单一容器 dt_all
├── nginx          端口 8080 → 宿主 9699   接收 CI 上传
├── grafana-server 端口 3000 → 宿主 9696   仪表盘
└── python watcher                          监听新 CSV，写入 SQLite
```

### watcher 版本

| 目录 | 存储方式 | Grafana 插件 | 状态 |
|------|---------|-------------|------|
| `app/` | CSV 文件 + HTML 报告 | Infinity | 备用 |
| `app_2.0/` | SQLite 数据库 | frser-sqlite-datasource | **当前使用** |

切换版本只需修改 Dockerfile 中的 `COPY` 目标行和插件安装行。

---

## 目录结构

```
grafana_v2.0/
├── Dockerfile                  # 镜像构建定义（当前使用 app_2.0/）
├── conf/
│   ├── nginx.conf              # nginx WebDAV PUT 配置
│   └── supervisord.conf        # 三进程管理配置
├── app/                        # CSV 版本（保留备用）
├── app_2.0/                    # SQLite 版本（当前打包进镜像）
│   ├── db.py                   # SQLite 建表 + CRUD
│   ├── resultSum.py            # CSV 解析 + 写库
│   └── watch_new_files.py      # 文件监听主入口
└── build_script/
    └── build_all_in_one.sh     # 一键构建 + 导出 + 启动
```

---

## 前置条件

- 已安装 Docker（建议 20.x 及以上）
- 构建机器可访问外网（需下载 debian 软件包、Grafana apt 源、frser-sqlite-datasource 插件）

---

## 构建步骤（有网络）

在 `grafana_v2.0/` 目录下执行：

```bash
bash build_script/build_all_in_one.sh
```

脚本会依次执行：

1. `docker build`：构建镜像 `dt_all:1.0`
2. `docker export`：将镜像导出为 `dt_all_1.0.tar`（约 1~2 GB）
3. `docker run`：在本机启动容器

---

## 部署到其他机器

### 方式一：复制源码后在目标机器构建（目标机器有网络）

```bash
scp -r grafana_v2.0/ user@target:/path/to/
bash grafana_v2.0/build_script/build_all_in_one.sh
```

### 方式二：传输导出包（目标机器无网络 / 离线环境）

```bash
# 1. 在有网络的机器上构建并导出（脚本自动完成）
bash build_script/build_all_in_one.sh
# 生成 grafana_v2.0/dt_all_1.0.tar

# 2. 传输并加载
scp dt_all_1.0.tar user@target:/path/to/
docker import dt_all_1.0.tar dt_all:1.0

# 3. 启动（docker export/import 会丢失 CMD，需手动指定）
docker run -d --restart=always --name dt_all \
    -p 9696:3000 \
    -p 9699:8080 \
    -v /your/data/path:/data \
    dt_all:1.0 \
    /usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
```

---

## 数据目录挂载

容器内所有数据统一使用 `/data`，需挂载宿主机目录：

| 容器内路径 | 说明 |
|-----------|------|
| `/data/details/sources/` | CI 上传的 CSV 文件（按时间戳子目录组织） |
| `/data/test_results.db` | SQLite 数据库（watcher 写入，Grafana 读取） |

启动前确保宿主机目录存在：

```bash
mkdir -p /your/data/path/details/sources
```

---

## CI 上传测试结果

```bash
# 时间戳格式：YYYY-MM-DD_HH-MM-SS
curl -u user:pass123 -T testResult.csv \
  http://localhost:9699/details/sources/2026-06-23_10-00-00/testResult.csv
```

`testResult.csv` 格式：

```
Num,module,binary,case,result
0,module/device,DeviceTest,txGetDevice_Basic,pass
1,module/device,DeviceTest,txGetDevice_Fail,failed
```

---

## Grafana 数据源配置

安装 `frser-sqlite-datasource` 插件后，在 Grafana 中添加 SQLite 数据源，文件路径填写：

```
/data/test_results.db
```

**常用查询：**

```sql
-- 趋势图
SELECT time, pass, total FROM runs ORDER BY time

-- 明细表（配合变量 $run_id）
SELECT num, module, binary, case_name, result
FROM test_cases WHERE run_id = $run_id

-- 变量数据源（下拉选择运行）
SELECT id || ' - ' || time AS label, id AS value
FROM runs ORDER BY time DESC
```

---

## 默认账号

| 服务 | 用户名 | 密码 |
|------|-------|------|
| Grafana | `admin` | `admin` |
| nginx Basic Auth | `user` | `pass123` |

Grafana 密码由 `conf/supervisord.conf` 中 `GF_SECURITY_ADMIN_PASSWORD` 控制，nginx 凭据由 Dockerfile 中 `htpasswd` 命令控制，修改均需重新构建镜像。

---

## 验证容器运行状态

```bash
# 查看三个进程是否全部 RUNNING
docker exec dt_all supervisorctl status

# 确认 SQLite 数据写入
docker exec dt_all sqlite3 /data/test_results.db \
  "SELECT * FROM runs; SELECT COUNT(*) FROM test_cases;"

# 查看 watcher 日志
docker exec dt_all tail -f /var/log/supervisor/watcher.log
```

---

## 注意事项

1. **Grafana dashboard 不持久化**：`/var/lib/grafana` 在容器内，容器删除后 dashboard 配置丢失。如需持久化，增加挂载：
   ```bash
   -v /your/grafana/data:/var/lib/grafana
   ```

2. **`docker export/import` 丢失 CMD**：`import` 后启动时必须手动在 `docker run` 末尾指定 `/usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf`。

3. **frser-sqlite-datasource 需构建时联网**：离线环境需提前下载插件 zip 包并修改 Dockerfile 改为离线安装。

4. **Basic Auth 凭据硬编码**：账号 `user:pass123` 写入 Dockerfile，修改需重新构建。

5. **切换回 CSV 版本**：修改 Dockerfile 的 `COPY app_2.0/` → `COPY app/` 和插件为 `yesoreyeram-infinity-datasource`，并在 `conf/nginx.conf` 中恢复 `/data/` GET location。
