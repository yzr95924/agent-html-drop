# agent-html-drop 实施任务书

> **迁移注记（2026-08-02）**：本工具原为 `yzr-agent-tools` 仓库的 `html-mcp`，已独立为单工具仓库
> `agent-html-drop` 并更名。本文成文于 monorepo 时期。

> 元信息：
>
> | 状态 | 关联设计文档 | 设计版本 | 创建日期 | 最近更新 |
> | --- | --- | --- | --- | --- |
> | T1–T12 已验收（V1）；T13–T18 批注扩展；T19–T25 容器化扩展（待验收 / 进行中）；T26 镜像发布流水线（进行中） | [`design.md`](./design.md) | V1 + 批注 + 容器化 + 镜像发布 | 2026-08-01 | 2026-08-03 |

<!-- 本文件"活文档"段与 §3 循环纪律，与 SKILL.md 执行原则「设计 SSOT、任务书活文档」故意重复：
生成的任务书脱离 skill 给执行者单读，必须自包含。SSOT 在 SKILL.md 执行原则；
本文件与 SSOT 措辞故意保持一致，改 SSOT 时同步改本文件。 -->

> 本文件是**执行期活文档**：进度与问题只更新在这里；设计文档评审后保持稳定。
> 设计要改时先修订设计文档，再回本文件同步受影响任务（见 §3 循环纪律）。

## 执行者操作指引（拿到本文件先读）

你（执行者，人或 agent）按以下循环操作本文件：

1. **认领**：从 §1 挑一个状态"未开始"且依赖已完成的任务，状态改"进行中"，
   在 §2 对应小节写下开始记录（日期 + 执行者）。
2. **回读设计**：按任务行的"设计落点 / 验收场景"指针读设计文档对应章节——本文件**不含**
   设计细节，不回读设计文档不许动手。
3. **执行 + 刷新**：每次有进展，在 §2 该任务小节追加一条执行记录（日期 / 内容 / 偏差 / 遗留）；
   状态变化时同步更新 §1 总表的"状态"列与元信息的"最近更新"。
4. **完成**：状态改"待验收"；验收者对照验收场景逐条验收、写结论，状态改"已验收"。
5. **遇到问题**：无法继续 → 状态"已阻塞"并在 §3 登记；发现**设计本身要改** →
   走 §3 循环纪律，不许绕过设计改实现。

你只能改三处：§1 的"状态"列、§2 的执行记录（只追加、不改历史）、§3 两张表。
任务定义（编号 / 内容 / 指针）由设计负责人维护——你觉得任务拆得不对，同样走 §3 登记。

## 1. 任务总表

| 编号 | 任务 | 关联功能点 | 设计落点 | 验收场景 | 依赖 | 状态 | 预估 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | `paths.py` + `config.py`（XDG 解析 + TOML I/O + 未知字段透传）+ 单元测试 | F16, F9 | §7.2, §4 | S21, S32 | 无 | 已验收 | 半天 |
| T2 | `storage.py`（原子写 / 文件名 regex / 大小上限 / 路径穿越 / 冲突 + force）+ 单元测试 | F1, F17, F18 | §7.1.2, §7.3, §4 | S4, S12, S13, S14, S15, S18, S19, S28, S33, S34 | T1 | 已验收 | 1 天 |
| T3 | `auth.py`（Bearer 常量时间比较 + redact_token）+ 单元测试 | F18 | §7.3, §9.3 | S16, S17 | T1 | 已验收 | 半天 |
| T4 | `server.py`（HTTP server 装配 + 路由分发 + method 白名单 + body 限流）+ 单元测试 | — | §7.1.1, §7.3 | S3, S15 | T1 | 已验收 | 1 天 |
| T5 | `api.py`（`/api/files` GET/DELETE、`/api/nginx-config`、`/api/health`）+ 单元测试 | F2, F3, F5, F7, F13 | §7.3 | S5, S6, S10, S23, S24 | T2, T3, T4 | 已验收 | 1 天 |
| T6 | `mcp_handler.py`（JSON-RPC + Streamable HTTP + 4 个 tool）+ 单元测试 | F1, F2, F3, F4 | §7.3, §7.1.2 | S4, S5, S6, S7, S12, S13, S14, S15, S16, S17, S18, S28, S33, S34, S35 | T2, T3, T4 | 已验收 | 1.5 天 |
| T7 | `ui/index.html` + `ui/style.css`（管理页：列表 / iframe 预览 / 删除 / 复制 URL / token 输入框）+ smoke 测试 | F5, F6, F7, F8 | §7.3, §9.3 | S8, S9, S10, S11 | T4 | 已验收 | 1 天 |
| T8 | `assets/nginx.conf.template` + `nginx-config` 渲染逻辑 + 单元测试 | F13 | §7.3, §12 | S2, S23, S24 | T1 | 已验收 | 半天 |
| T9 | `cli.py`（9 个子命令）+ 单元测试 | F9–F14 | §7.3, §12 | S1, S2, S3, S11, S21, S22, S31, S32 | T1–T8 | 已验收 | 1.5 天 |
| T10 | `scripts/install.sh` / `scripts/uninstall.sh` 扩展 + `bin/agent-html-drop` wrapper + `completions/agent-html-drop.{bash,fish}` + 测试 | F15 | §7.4, §12 | S1, S26, S27 | T9 | 已验收 | 1 天 |
| T11 | README.md / AGENTS.md 更新（新增 agent-html-drop 工具章节） | — | §1, §12 | — | T9 | 已验收 | 半天 |
| T12 | 端到端 smoke：跑一次 install → init → serve → nginx-config → 上传 → list → delete，确认全链路 | — | §12 | S1–S11 全跑一遍 | T1–T11 | 已验收 | 半天 |
| T13 | `storage/annotations.py`（读 / 写 / 改 / 删 / 列 / 计数；`<name>.meta` 边车 JSON；ULID；author hash；atomic write）+ 单元测试 | F21, F23 | §4, §7.2, §9.3 | S37, S38, S40 | T2 | 未开始 | 1 天 |
| T14 | `api.py` 扩展：`POST /api/auth` + 批注 REST CRUD（GET/POST/PATCH/DELETE）+ session cookie + CSRF + `list_files` 增 `annotation_count` + 单元测试 | F20, F21, F24 | §7.3, §9.3 | S36, S37, S38, S8' | T3, T5, T13 | 未开始 | 1.5 天 |
| T15 | `mcp_handler.py` 扩展：`list_annotations` / `delete_annotation` 2 个 tool + 单元测试 | F23 | §7.3 | S39, S40 | T6, T13 | 未开始 | 半天 |
| T16 | `ui/index.html` + `ui/style.css` + `ui/app.js` 扩展：批注模式入口（header 按钮 + token 弹窗 + 状态切换）+ iframe 选区 → quote + 高亮注入（`<mark data-anno-id>`）+ 批注侧栏 + smoke 测试 | F19, F22, F25 | §7.3, §9.3 | S36, S37, S38, S39 | T7, T14 | 未开始 | 2 天 |
| T17 | `nginx.conf.template` + README 更新：加 `proxy_cookie_path ... SameSite=Lax` 行 + `limit_req` 注释 + nginx.conf.example | — | §9.3, §12 | S36 | T8, T14 | 未开始 | 半天 |
| T18 | 端到端 smoke：浏览器进入批注模式 → 写批注 → 高亮 → 改/删 → agent `list_annotations` 看批注改进 HTML | — | §9.3, §12 | S36–S40 全跑一遍 | T13–T17 | 未开始 | 半天 |
| T19 | daemon `GET /files/<name>` 路由（流式输出 + server 流式响应扩展 + 复用 `validate_name` + 缺失/非法/穿越统一 404）+ 单元测试 | F5, F6 | §15.3.1, §7.3 | S9 | T2, T4 | 待验收 | 1 天 |
| T20 | 公开 URL 统一加 `/files/` 段（`api._file_info_payload` 1 处 + `mcp_handler` upload/list/get_public_url 3 处 = 共 4 处构造）+ 迁移注记 + 单元测试更新 | F4, F8 | §15.3.2, §4 | S7, S11 | T5, T6 | 待验收 | 半天 |
| T21 | `assets/nginx.conf.template` 重写为极简反代片段（去 SSL/alias）+ `nginx_config` 渲染 + 单元测试更新 | F13 | §15.3.3, §7.3 | S2, S23 | T8 | 待验收 | 半天 |
| T22 | `Dockerfile` + `docker/entrypoint.sh` + `.dockerignore`（`python:3.12-slim`，非 root，首次自动种 config + token） | — | §15.4 | 容器启动（新） | T19–T21 | 待验收 | 1 天 |
| T23 | `docker-compose.yaml` + 反代片段 docs（两 bind mount + `ports: 127.0.0.1:8765:8765` + healthcheck） | — | §15.4, §15.5 | compose 部署（新） | T22 | 待验收 | 半天 |
| T24 | README / AGENTS 容器化章节（部署 / 备份 / 迁移 / token 获取） | — | §15, §12 | — | T22, T23 | 待验收 | 半天 |
| T25 | 容器冒烟测试（build → run → `/api/health` 200 → 上传 HTML → `/files/x.html` 200） | — | §15.7 | 容器 E2E（新） | T19–T24 | 进行中 | 半天 |
| T26 | 镜像发布流水线：GHCR + GitHub Actions（`v*` tag 触发 + 多架构 amd64/arm64 + 5 tag 矩阵 + post-publish smoke）；`docker-compose.yaml` 改 `image:` 走 pull；README 新增发布新版本章节 | — | §16 | 别人 clone repo 后 `docker compose up` 不需要本地 build | T25 | 进行中 | 半天 |

纪律：

- **只做指针，不复制设计**——"关联功能点 / 设计落点 / 验收场景"三列只写设计文档章节号
  （§3 功能点 / §7 详细设计 / §5 场景）；任务行复制设计内容 = 与设计文档必然漂移。
- **状态机**：未开始 → 进行中 → 待验收 → 已验收；异常状态：已阻塞（写明被什么卡住）/ 有偏差。
- **任务粒度**：一个任务 ≈ 一个执行者一个会话能闭环（半天到两天）；先后关系写进"依赖"列。
- 执行中拆出的新任务追加编号（T13、T14…），不重排已有编号。

## 2. 任务执行记录

每个任务一小节，**只追加、不改历史**。

### T1 paths.py + config.py + 测试

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`src/agent_html_drop/paths.py` + `config.py`，含未知字段透传；`tests/test_agent_html_drop_paths.py` + `test_agent_html_drop_config.py` 全过
- 验收：S21（损坏 config → 退出码 2）/ S32（权限警告）覆盖；与 model_switch store.py 同规约

### T2 storage.py + 测试

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`src/agent_html_drop/storage.py` + `tests/test_agent_html_drop_storage.py`；atomic write / name regex / path traversal / case-insensitive conflict 全覆盖
- 验收：S4 / S12 / S13 / S14 / S15 / S18 / S19 / S28 / S33 / S34 覆盖

### T3 auth.py + 测试

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`src/agent_html_drop/auth.py` + `tests/test_agent_html_drop_auth.py`；`hmac.compare_digest` 常量时间 + `redact_token`
- 验收：S16 / S17（Bearer 缺失 / 错误）覆盖

### T4 server.py + 测试

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`src/agent_html_drop/server.py` + `tests/test_agent_html_drop_server.py`；ThreadingHTTPServer + 路由注册 + 405 Allow + body 限流
  - 2026-08-01（commit `bcc3601`）补：SIGALRM watchdog 兜底优雅退出
- 验收：S3（启动）/ S15（size 突破 413）覆盖；测试同时覆盖 SIGTERM watchdog

### T5 api.py + 测试

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`src/agent_html_drop/api.py` + `tests/test_agent_html_drop_api.py`
  - 2026-08-01（commit `6d46ea2`）调整：`GET /api/files` 去 Bearer（公开元数据）；保留 Bearer 在 `DELETE /api/files/<name>` 与 `GET /api/nginx-config`
- 验收：S5 / S6 / S10 / S23 / S24 覆盖

### T6 mcp_handler.py + 测试

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`src/agent_html_drop/mcp_handler.py` + `tests/test_agent_html_drop_mcp.py`；JSON-RPC 2.0 自实现 + 4 个 tool + Bearer 鉴权
- 验收：S4 / S5 / S6 / S7 / S12–S15 / S16 / S17 / S18 / S28 / S33 / S34 / S35 覆盖

### T7 ui/index.html + style.css + smoke

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`src/agent_html_drop/ui/{index.html,style.css,app.js}` + `tests/test_agent_html_drop_ui.py`
  - 2026-08-01（commit `6d46ea2`）调整：删除"操作"列 + token-bar；token 不再走 localStorage；401 触发版本不匹配 toast
- 验收：S8 / S9 / S11 覆盖；S10 验证管理页无删除按钮

### T8 nginx.conf.template + nginx-config 渲染 + 测试

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`src/agent_html_drop/assets/nginx.conf.template` + `nginx_config.py` + `tests/test_agent_html_drop_nginx.py`
- 验收：S2 / S23 / S24 覆盖

### T9 cli.py + 测试

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`src/agent_html_drop/cli.py` + `tests/test_agent_html_drop_cli.py`；9 个子命令全跑
- 验收：S1 / S2 / S3 / S11 / S21 / S22 / S31 / S32 覆盖

### T10 install.sh/uninstall.sh + wrapper + completions + 测试

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `b98826b`）交付：`bin/agent-html-drop` wrapper
  - 2026-08-01（commit `152e21f`）调整：bin/ wrappers 不入库；install.sh 重新生成
- 验收：S1 / S26 / S27 覆盖

### T11 README.md / AGENTS.md 更新

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `6809322`）交付：`src/agent_html_drop/README.md` + `AGENTS.md` 更新（多工具形态）
  - 2026-08-01（commit `6d46ea2`）调整：管理页只读 + token 不在 UI 章节
- 验收：文档与代码一致

### T12 端到端 smoke

- 状态：已验收
- 执行记录：
  - 2026-08-01（commit `1b466fa`）交付：`tests/test_agent_html_drop_smoke.py`；install → init → serve → nginx-config → upload → list → delete 全链路
- 验收：S1–S11 全过

### T13 storage/annotations.py + 测试

- 状态：未开始
- 执行记录：
  - （待填）
- 验收：（待填）

### T14 api.py 扩展（/api/auth + 批注 REST CRUD）

- 状态：未开始
- 执行记录：
  - （待填）
- 验收：（待填）

### T15 mcp_handler.py 扩展（list_annotations / delete_annotation）

- 状态：未开始
- 执行记录：
  - （待填）
- 验收：（待填）

### T16 ui/index.html + style.css + app.js 扩展（批注模式 + iframe 高亮）

- 状态：未开始
- 执行记录：
  - （待填）
- 验收：（待填）

### T17 nginx.conf.template + README 更新（SameSite + limit_req）

- 状态：未开始
- 执行记录：
  - （待填）
- 验收：（待填）

### T18 端到端 smoke（批注模式）

- 状态：未开始
- 执行记录：
  - （待填）
- 验收：（待填）

### T19 daemon /files/<name> 路由 + 流式响应 + 测试

- 状态：待验收
- 执行记录：
  - 2026-08-02 TDD 交付：`server.py` 加 `STREAMED` 哨兵 + `Handler.send_file` 流式方法（64KiB 分块）+ dispatcher 短路；`api.py` 加 `_make_get_file`（复用 `validate_name` + resolve-under-docroot 防穿越，缺失/非法/穿越统一 404）；`tests/test_files_route.py` 8 例全过（含 2MB 流式 round-trip）。
- 验收：S9（预览 `/files`）由 daemon 服务；全量 257 passed。

### T20 公开 URL 统一 /files/ 段 + 迁移 + 测试

- 状态：待验收
- 执行记录：
  - 2026-08-02 TDD 交付：4 处 URL 构造（`api._file_info_payload` + `mcp` upload/list/get_public_url）改 `public_base_url.rstrip("/") + "/files/" + name`，`public_base_url` 语义为「纯 origin」；`test_mcp` 两处精确断言更新、`test_api`/`test_mcp` list 前缀断言收紧到 `/files/`。
- 验收：迁移注记入 design §4 / §15.3.2（旧 `public_base_url` 含 `/files` 需去掉）；257 passed。

### T21 nginx.conf.template 重写极简反代片段 + 测试

- 状态：待验收
- 执行记录：
  - 2026-08-02 TDD 交付：模板重写为纯反代 location 块 + `limit_req_zone`（去 SSL / server 包装 / docroot alias / proxy_cookie_path）；`nginx_config.render/render_to` 删 `docroot` 死参数，cli/api 调用方同步；`test_nginx.py` 重写。连带修 `test_api`/`test_cli`/`test_smoke` 的 nginx-config 断言 + README/AGENTS/design 的「server block」措辞。
- 验收：单一真源 = 模板；257 passed。

### T22 Dockerfile + entrypoint.sh + .dockerignore

- 状态：待验收
- 执行记录：
  - 2026-08-02 交付：`Dockerfile`（`python:3.12-slim`，零运行时依赖，非 root uid 1000，`PYTHONPATH=/app/src`，`XDG_CONFIG_HOME=/data/config`）+ `docker/entrypoint.sh`（首次 serve 用项目自身 `Config`/`save_config` 种容器友好 config + token）+ `.dockerignore` + wrapper `/usr/local/bin/agent-html-drop`（让 `docker exec ... agent-html-drop <cmd>` 可用）。
  - entrypoint 种 config 逻辑在本机无 docker 下已离线验证：TOML 正确、`load_config`+`validate_for_serve` round-trip 过、perms 0600。
- 验收：镜像未本机构建（本机无 docker）；bootstrap 逻辑已离线验证，待 T25 实跑。

### T23 docker-compose.yaml + 反代片段 docs

- 状态：待验收
- 执行记录：
  - 2026-08-02 交付：`docker-compose.yml`（单服务 + 两 bind mount + `127.0.0.1:8765:8765` + `PUBLIC_BASE_URL` env + `restart: unless-stopped`）；反代片段走 `nginx-config` CLI 渲染（单一真源，README 指向 `docker compose exec agent-html-drop agent-html-drop nginx-config`）。
- 验收：compose 未本机 up（无 docker）。

### T24 README / AGENTS 容器化章节

- 状态：待验收
- 执行记录：
  - 2026-08-02 交付：README 加「Docker 部署」章节（部署 / token / nginx 片段 / 卷表 / 迁移 / uid 对齐 / exec 陷阱）+ 修快速上手 step4-5 与公开 URL 公式（T20/T21 连带）；AGENTS.md 加容器化命令块 + `/files` 双模式注记 + nginx-config 措辞。
- 验收：文档与代码一致。

### T25 容器冒烟测试

- 状态：进行中（脚本已写，本机无 docker 未实跑）
- 执行记录：
  - 2026-08-02 交付：`scripts/docker-smoke.sh`（build → `/api/health` 200 → `/files/smoke.html` 200 → token 64-hex；`--user root` 绕开 bind-mount uid）。`bash -n` 语法过。
- 验收：待在有 docker 的环境实跑 `bash scripts/docker-smoke.sh` 确认。

### T26 镜像发布流水线（GHCR + GitHub Actions）

- 状态：进行中（代码已交付，待第一次 `v*` tag push 触发 CI）
- 执行记录：
  - 2026-08-03 交付：
    - `.github/workflows/release-image.yml`：trigger `push tags: 'v*'`；`docker/metadata-action@v5` 派生 5 tag 矩阵（`vX.Y.Z` / `X.Y` / `X.Y.Z` / `latest`（仅 default branch） / `sha-<short>`）；`docker/build-push-action@v6` 推 `linux/amd64 + linux/arm64` manifest list；`cache-from: type=gha` + `cache-to: type=gha,mode=max`；post-publish 跑 `scripts/docker-smoke.sh`（`SMOKE_IMAGE` env 路径）。
    - `scripts/docker-smoke.sh`：加 `SMOKE_IMAGE` 环境变量分支——设置时走 `docker pull`，默认仍走 `docker build`（本地开发）。`bash -n` 语法过。
    - `docker-compose.yaml`：`image: agent-html-drop:latest` → `image: ghcr.io/yzr95924/agent-html-drop:v0.1.0`；`build: .` 注释掉；顶部注释说明发布镜像来源 + 本地重建开关。
    - 同次提交把所有 `<owner>` 占位符批量替换为 `yzr95924`（覆盖 `docker-compose.yaml` / `README.md` / `docs/design.md` §16 / `docs/tasks.md` T26 log / workflow 注释）；fork 用户自行替换。
    - `README.md`：`Docker 部署` 段加 GHCR 说明 + `docker compose up`（无 `--build`）；新增 `## 发布新版本（维护者）` 段（tag 命令 + CI 流程 + 首次 public 切换 + 失败回滚）。
    - `docs/design.md`：新增 §16（决策表 + workflow 流程 + compose diff + 范围外 + 验收）。
- 验收：
  - workflow YAML 合法（`yaml.safe_load` 过）
  - `bash scripts/docker-smoke.sh` 语法过（不实跑）
  - 现有 258 个 pytest 仍通过
  - 实际 CI 验收需 push 第一个 `v0.1.0` tag 后看 Actions 跑通——本机无 docker / 不动真实 tag

## 3. 问题反馈与设计变更

执行中遇到的问题登记在这里——**尤其是"设计本身要改"的问题**：

| 编号 | 发现于 | 问题描述 | 影响 | 处置（改设计 / 绕过 / 挂起） | 状态 |
| --- | --- | --- | --- | --- | --- |
| I1 |  |  |  |  | 待处理 |
| I2 |  |  |  |  | 待处理 |

设计修订同步记录（设计文档每次因问题修订后在此留痕）：

| 日期 | 设计文档变更（章节 + 摘要） | 同步更新的任务 | 操作人 |
| --- | --- | --- | --- |
| 2026-08-01 | §1 假设 A3 拆 A3 / A3'(单 token 浏览器+agent 共用)；§2 非目标 N8 改写 + N10 / N11；§3 F19–F25；§4 批注字段 / cookie / CSRF / nginx 限流；§5 S36–S40；§7.2 `.meta` schema；§7.3 `/api/auth` + 批注 REST + MCP `list_annotations` / `delete_annotation`；§8 异常 +5；§9.3 批注写接口安全段；§10 否决 J / K；§13 Q8–Q11 | T13–T18 全新增（§1 §11 段落同步更新） | Zuoru YANG |
| 2026-08-02 | §2 N5 撤销「Docker image」；§4 公开 URL 加 `/files/` 段（行为变更 + 迁移）+ 部署约束增容器模式；§7.3 / §9.3 `/files` 注记改双模式；§12.1 容器部署路径；§13 Q12–Q15 闭环；新增 §15 容器化设计（拓扑 / delta / 交付物 / 卷 / 安全 / 测试） | T19–T25 全新增 | Zuoru YANG |
| 2026-08-03 | 新增 §16 镜像发布流水线（GHCR + GitHub Actions 多架构 + tag 矩阵 + post-publish smoke；范围外列 cosign / SBOM / Trivy 等 v2 增强） | T26 全新增 | Zuoru YANG |

循环纪律（偏差回流）：

1. 执行中发现设计要改 → 在问题表登记（状态：待处理），**先停该方向的实现**。
2. 修订设计文档相关章节并更新其元信息日期；改动大时挂进设计文档"开放问题"，走二次评审。
3. 回本文件：受影响任务行的"设计落点 / 验收场景"指针同步更新，填"设计修订同步记录"，
   问题状态置"已闭环"。
4. 继续执行。

**不许绕过设计直接改实现**——实现与设计悄悄分叉 = 设计文档和任务书同时失效。
反过来，实现走样但设计没错：不走本表，属于该任务的返工，记在执行记录里。