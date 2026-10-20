# ci_runner

Docker 定时 CI 系统：每天固定时间从自建 GitLab 拉代码 → 编译 → 跑测试，也支持手动触发。

## 快速开始

```bash
# 1. 把 SSH 私钥丢到 secrets/ 目录
cp ~/.ssh/id_rsa secrets/id_rsa
chmod 600 secrets/id_rsa

# 2. 修改 gitlab.internal 为你的自建 GitLab 地址
vim docker-compose.yml  # GITLAB_HOST 参数
vim config/config.yaml  # repo_url 字段

# 3. 启动
docker compose up -d

# 4. 手动触发一次测试
curl -X POST http://127.0.0.1:8080/projects/my_cpp_project/run

# 5. 查看运行历史
curl http://127.0.0.1:8080/runs?limit=5 | python3 -m json.tool
```

## 触发方式

| 方式 | 用法 |
|---|---|
| 定时 (cron) | 每天 00:00 Asia/Shanghai（在 `config.yaml` 的 `cron` 字段配置） |
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

## 配置

编辑 `config/config.yaml`，改完 `docker compose restart ci_runner` 生效。

```yaml
timezone: Asia/Shanghai
defaults:
  clone_depth: 1
  build_timeout_sec: 3600
  test_timeout_sec: 1800
  keep_runs: 30           # 每个项目保留最近 30 次运行日志

projects:
  - name: my_cpp_project
    repo_url: git@gitlab.internal:group/my-project.git
    branch: main
    cron: "0 0 * * *"
    workdir: ""
    build_cmd: |
      mkdir -p build && cd build
      cmake -DCMAKE_C_COMPILER_LAUNCHER=ccache \
            -DCMAKE_CXX_COMPILER_LAUNCHER=ccache ..
      make -j$(nproc)
    test_cmd: |
      cd build && ctest --output-on-failure
    env:
      CCACHE_DIR: /cache/ccache
```

## 数据持久化

| 目录/文件 | 说明 |
|---|---|
| `./data/db.sqlite` | 运行历史（元数据） |
| `./data/runs/<id>/` | 每次运行的日志（clone.log / build.log / test.log / status.json） |
| `./cache/ccache/` | ccache 编译缓存（加速重复构建） |
| `./config/` | 配置文件（只读挂载） |
| `./secrets/id_rsa` | SSH 私钥（只读挂载） |

## 开发

```bash
# 创建虚拟环境
python3 -m venv .venv && source .venv/bin/activate

# 安装依赖
pip install -r requirements-dev.txt

# 运行测试
pytest tests/unit tests/integration tests/e2e -v

# 运行 smoke 测试（需要 Docker）
bash scripts/smoke.sh
```

## 扩展点

| 方向 | 怎么做 |
|---|---|
| 多项目 | `config.yaml` 里加新的 `projects` 条目 |
| 通知 | 继承 `app/notifier.py` 的 `Notifier` 基类，实现 `on_finish(run)` |
| Web UI | 挂 `/ui` 静态路由，复用现有 JSON API |
| HTTP 认证 | 加 `Depends(verify_token)` 中间件，读 `API_TOKEN` 环境变量 |
| 不同构建镜像 | 每个 project 配 `docker_image` 字段，容器内用 `docker run` 或 `podman` |
| GitLab push webhook | 加 `POST /webhook/gitlab` 路由，验签后调 `pipeline.run()` |