# grafana_v2.0 构建说明

## 概述

本目录将原有三个 Docker 容器（nginx、Python watcher、Grafana）合并为单一镜像，使用 `supervisord` 在容器内同时管理三个进程。

```
单一容器 dt_all
├── nginx          端口 8080 → 宿主 9699   接收 CI 上传 / 提供静态文件
├── grafana-server 端口 3000 → 宿主 9696   仪表盘
└── python watcher                          监听新 CSV，生成 HTML 报告
```

---

## 目录结构

```
grafana_v2.0/
├── Dockerfile                  # 镜像构建定义
├── conf/
│   ├── nginx.conf              # nginx WebDAV + 静态文件配置
│   └── supervisord.conf        # 三进程管理配置
├── app/                        # Python 脚本（打包进镜像）
│   ├── watch_new_files.py
│   ├── csv2html.py
│   └── resultSum.py
└── build_script/
    └── build_all_in_one.sh     # 一键构建 + 导出 + 启动
```

---

## 前置条件

- 已安装 Docker（建议 20.x 及以上）
- 构建机器可访问外网（需下载 debian 软件包、Grafana apt 源、Infinity 插件）

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

构建时间约 3~10 分钟（取决于网速），主要耗时在下载 Grafana 安装包和 Infinity 插件。

---

## 部署到其他机器

### 方式一：复制源码后在目标机器构建（目标机器有网络）

```bash
# 1. 将整个 grafana_v2.0/ 目录复制到目标机器
scp -r grafana_v2.0/ user@target:/path/to/

# 2. 在目标机器上执行构建
bash grafana_v2.0/build_script/build_all_in_one.sh
```

### 方式二：传输导出包（目标机器无网络 / 离线环境）

```bash
# 1. 在有网络的机器上构建并导出（脚本自动完成）
bash build_script/build_all_in_one.sh
# 生成 grafana_v2.0/dt_all_1.0.tar

# 2. 将 tar 包传到目标机器
scp dt_all_1.0.tar user@target:/path/to/

# 3. 在目标机器上 import 并启动
docker import dt_all_1.0.tar dt_all:1.0

docker run -d --restart=always --name dt_all \
    -p 9696:3000 \
    -p 9699:8080 \
    -v /your/data/path:/data \
    dt_all:1.0 \
    /usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf
```

> **注意**：`docker export/import` 会丢失镜像的 `CMD`/`ENTRYPOINT` 元数据，
> 因此 `docker import` 后启动时必须在命令末尾**手动指定启动命令**：
> `/usr/bin/supervisord -n -c /etc/supervisor/conf.d/all.conf`
>
> 若使用 `docker save/load` 则不需要此步骤（保留元数据），但文件更大。

---

## 数据目录挂载

容器内所有数据统一使用 `/data`，需挂载宿主机目录：

| 容器内路径 | 说明 |
|-----------|------|
| `/data/details/sources/` | CI 上传的 CSV 文件存放位置（按时间戳子目录组织） |
| `/data/details/html/` | watcher 生成的 HTML 报告 |
| `/data/catch2Result.csv` | watcher 生成的汇总 CSV（Grafana 读取） |

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

`result` 列支持：`pass`、`failed`、`timeout`

---

## 验证容器运行状态

```bash
# 查看三个进程是否全部 RUNNING
docker exec dt_all supervisorctl status

# 预期输出：
# grafana                          RUNNING   pid 123, uptime 0:01:00
# nginx                            RUNNING   pid 124, uptime 0:01:00
# watcher                          RUNNING   pid 125, uptime 0:01:00

# 查看各进程日志
docker exec dt_all tail -f /var/log/supervisor/watcher.log
docker exec dt_all tail -f /var/log/supervisor/nginx_err.log
docker exec dt_all tail -f /var/log/supervisor/grafana.log

# 测试 nginx 静态文件访问
curl -u user:pass123 http://localhost:9699/data/catch2Result.csv

# 访问 Grafana（默认账号 admin / admin）
http://localhost:9696
```

---

## 注意事项

1. **Grafana Infinity 插件**：构建时自动在线安装。若无网络，需提前下载 zip 包放入目录，并修改 Dockerfile 改为离线安装。

2. **nginx WebDAV**：使用 `nginx-extras` 包（含 `ngx_http_dav_module`），Basic Auth 账号固定为 `user:pass123`，如需修改请更新 Dockerfile 中的 `htpasswd` 命令后重新构建。

3. **watcher 重启行为**：容器重启时 watcher 会清空 `/data/details/html/` 并重新扫描所有已有 CSV 重建 HTML，这是设计行为（`watch_new_files.py` 中 `initHtmlDir()` 的逻辑）。`/data/catch2Result.csv` 也会被重置，只保留当前 `sources/` 目录下已有文件的汇总。

4. **数据持久化**：Grafana 自身数据（dashboard 配置、数据源等）存储在容器内 `/var/lib/grafana`，容器删除后会丢失。如需持久化，额外挂载：
   ```bash
   -v /your/grafana/data:/var/lib/grafana
   ```
