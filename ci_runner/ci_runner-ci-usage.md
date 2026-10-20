---
name: ci_runner-ci-usage
description: 记录 Docker 定时 GitLab 构建测试系统（ci_runner）的完整使用方法和设计决策
metadata: 
  node_type: memory
  type: project
  originSessionId: 989a1d21-7e23-4729-ba62-671893397670
  modified: 2026-07-28T09:31:47.543Z
---

# Docker 定时 GitLab 构建 & 测试系统 — ci_runner

## 项目位置

`/home/kk/toWsl/virtualBox/001_my_framework/grafana/ci_runner/`

## 一句话

一个跑在 Docker 里的轻量 CI 系统：每天 00:00 Asia/Shanghai 从自建 GitLab 拉 C/C++（可能带 Python）项目代码 → 编译 → 跑 test，也支持 HTTP 和 `docker exec` 手动触发。

## 架构

- 单容器长跑 Python 进程：**FastAPI**（HTTP 端点）+ **APScheduler**（cron 调度）+ **CLI 入口**
- 三种触发方式（cron / HTTP / CLI）都收敛到同一个 `run_pipeline(project, trigger)` 函数
- SQLite 存运行元数据，文件卷存日志（clone.log / build.log / test.log / status.json）
- ccache 持久化加速重复编译

## Docker 构建与使用

### 构建镜像

```bash
cd /home/kk/toWsl/virtualBox/001_my_framework/grafana/ci_runner

# 方式一：通过 docker-compose 构建（推荐）
docker compose build

# 方式二：直接 docker build（可指定 GITLAB_HOST）
docker build --build-arg GITLAB_HOST=gitlab.internal -t ci_runner .

# 方式三：构建时跳过 known_hosts（如果后续手动挂载）
docker build --build-arg GITLAB_HOST= -t ci_runner .
```

镜像包含：Ubuntu 22.04 + gcc/g++/make/cmake/ccache + Python3 + git + openssh + vim + sqlite3 + procps。

### 运行容器

```bash
# 方式一：docker-compose（推荐）
docker compose up -d        # 后台启动
docker compose logs -f      # 看实时日志
docker compose restart      # 改配置后重启
docker compose down         # 停止并删除容器

# 方式二：直接 docker run
docker run -d \
  --name ci_runner \
  -e TZ=Asia/Shanghai \
  -p 127.0.0.1:8080:8080 \
  -v ./data:/data \
  -v ./cache/ccache:/cache/ccache \
  -v ./config:/app/config:ro \
  -v ./secrets/id_rsa:/root/.ssh/id_rsa:ro \
  --restart unless-stopped \
  ci_runner
```

### 前置准备

```bash
# 1. 改配置
vim config/config.yaml          # 填你的 GitLab 地址、项目 repo_url、branch
vim docker-compose.yml          # 改 GITLAB_HOST 参数为你自建 GitLab 的域名/IP

# 2. 放 SSH 私钥
cp ~/.ssh/id_rsa secrets/id_rsa
chmod 600 secrets/id_rsa

# 3. 启动
docker compose up -d

# 4. 确认启动成功
curl http://127.0.0.1:8080/healthz    # 返回 {"status":"ok"}
```

### 进入容器调试

```bash
docker exec -it ci_runner bash

# 容器内可直接查数据库
sqlite3 /data/db.sqlite "SELECT id, status, started_at FROM runs ORDER BY started_at DESC LIMIT 10;"

# 查看日志
tail -f /data/runs/*/build.log
ls -la /data/runs/

# 查看 ccache 命中率
ccache -s
```

### 日常运维

```bash
# 查看容器状态
docker ps -a --filter name=ci_runner
docker stats ci_runner

# 查看实时日志
docker compose logs -f --tail=50

# 改配置后重启（config 是只读挂载，改了不会自动生效）
docker compose restart

# 清理旧日志（手动）
rm -rf data/runs/*

# 重置所有数据（包括历史记录和缓存）
docker compose down
rm -rf data cache/ccache/*
docker compose up -d
```

### 问题排查

```bash
# 容器起不来
docker compose logs ci_runner

# 端口冲突（8080 被占）
lsof -i :8080
# 改 docker-compose.yml 里映射端口，如 "127.0.0.1:8081:8080"

# SSH 认证失败
docker exec ci_runner ssh -T git@<gitlab-host>  # 测试连通性
docker exec ci_runner ls -la /root/.ssh/         # 检查密钥是否挂载成功

# 构建超时
# 改 config.yaml 的 build_timeout_sec / test_timeout_sec

# 磁盘空间不足
du -sh data/ cache/ccache/
```

## 三种触发方式

| 方式 | 用法 |
|---|---|
| 定时 (cron) | 每天 00:00 Asia/Shanghai（在 `config.yaml` 的 `cron` 字段配） |
| HTTP | `curl -X POST http://127.0.0.1:8080/projects/my_cpp_project/run` |
| CLI | `docker exec ci_runner python -m app.cli run my_cpp_project` |

## CLI 命令

```bash
docker exec ci_runner python -m app.cli list              # 最近 20 次运行
docker exec ci_runner python -m app.cli show <run_id>      # 查看某次详情 + 日志尾
docker exec ci_runner python -m app.cli run <project_name> # 触发并等待完成
```

## HTTP 端点

| 路径 | 说明 |
|---|---|
| `GET /healthz` | 健康检查 |
| `GET /projects` | 列所有项目及最近运行状态 |
| `POST /projects/{name}/run` | 触发一次运行（返回 409 若已在跑） |
| `GET /runs?project=&limit=20` | 分页列历史 |
| `GET /runs/{id}` | 单次运行元数据 |
| `GET /runs/{id}/log/clone` | 克隆日志（流式） |
| `GET /runs/{id}/log/build` | 构建日志 |
| `GET /runs/{id}/log/test` | 测试日志 |

## 数据持久化

| 目录/文件 | 说明 |
|---|---|
| `./data/db.sqlite` | 运行历史（元数据） |
| `./data/runs/<id>/` | 每次运行的日志（clone.log / build.log / test.log / status.json） |
| `./cache/ccache/` | ccache 编译缓存（加速重复构建） |
| `./config/` | 配置文件（只读挂载，改完 `docker compose restart` 生效） |
| `./secrets/id_rsa` | SSH 私钥（只读挂载） |

## 运行流程

1. 拿全局锁（非阻塞）→ 拿不到写 SKIPPED 返回
2. 生成 run_id 和 log_dir，DB 插入 status='running'
3. 全新 git clone（`--depth=1`）到临时目录
4. 跑 build_cmd（subprocess，进程组，timeout）
5. 成功则跑 test_cmd（同样处理）
6. finally：写 status.json、删临时目录、调 notifier（v1 noop）、释放锁、旋转旧日志

## 并发行为

正在跑时新的触发直接拒绝：HTTP 返回 409，CLI 退出码 2，scheduled 记 SKIPPED 行。

## 6 个扩展点

| 方向 | 以后改哪里 |
|---|---|
| 多项目 | `config.yaml` 加 project 条目，`run_pipeline` 已参数化 |
| 通知 | 继承 `Notifier` 基类实现 `on_finish(run)`，v1 是 `NoopNotifier` |
| Web UI | 挂 `/ui` 静态路由，复用 JSON API |
| HTTP 认证 | 加 `Depends(verify_token)` 中间件，读 env `API_TOKEN` |
| 不同构建镜像 | project 配置加 `docker_image` 字段 |
| GitLab push webhook | 加 `POST /webhook/gitlab` 路由，验签后调 `pipeline.run()` |

## 关键设计决策（为什么这么做）

- **Python + FastAPI + APScheduler**：跟现有 Python 栈重合，扩展性好，代码量适中
- **单进程长跑**（vs 每次起一次性容器）：调度器在容器内，不易漏掉 cron 触发
- **全新 clone + ccache**：源码干净无污染，编译对象复用
- **`127.0.0.1` 绑 HTTP**：v1 无认证，不暴露到外网
- **`threading.Lock` 非阻塞**：简单可靠，适合单进程场景
- **容器内装 `vim`/`sqlite3`**：便于 `docker exec -it` 进容器查日志和数据库

## 测试

```bash
cd /home/kk/toWsl/virtualBox/001_my_framework/grafana/ci_runner
source .venv/bin/activate
pytest tests/unit tests/integration tests/e2e -v   # 47 passed
```

三层测试：单元测试（秒级）、集成测试（假 git 仓库 + 假命令）、HTTP/CLI 端到端测试。无需真连 GitLab、无需真编译 C++ 就能测透所有逻辑。

## 技术栈

- Ubuntu 22.04（基础镜像）
- Python 3 + FastAPI + APScheduler + Pydantic + PyYAML
- SQLite（标准库，零依赖）
- C/C++ 工具链：gcc/g++/make/cmake/ccache
- Git + OpenSSH（自建 GitLab 认证）