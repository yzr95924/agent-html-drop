# agent-html-drop

常驻 HTTP daemon，让本机 agent（Claude Code / OpenCode）经 MCP 把自包含 HTML
（`yzr-md-to-html` 等工具的产物）推到远端 nginx server，同时提供一个 HTML 管理页供人浏览 /
预览 / 删除 / 复制公开 URL。

## 形态

```
┌──────────────────────┐                ┌──────────────────────────────────────┐
│  本机 agent           │   HTTPS        │  远端 nginx server                   │
│  (Claude Code /      │ ─────────────► │   ┌────────────────────────────┐     │
│   OpenCode)          │  /mcp + Bearer │   │ agent-html-drop daemon     │     │
│                      │                │   │  127.0.0.1:8765            │     │
│                      │                │   │  ├ POST /mcp    MCP server │     │
│                      │                │   │  ├ GET  /       HTML 管理页│     │
│                      │                │   │  └ /api/* + /files/        │     │
│                      │                │   └────────────┬───────────────┘     │
│  浏览器（人）         │ ──HTTPS──────► │       ┌────────▼────────────┐       │
│   https://notes...   │                │       │ nginx               │       │
│                      │                │       │  :443 → 反代 → :8765│       │
│                      │                │       │  + 直 serve /files/*│       │
│                      │                │       └─────────┬───────────┘       │
│                      │                │           docroot/                  │
└──────────────────────┘                └──────────────────────────────────────┘
```

- **daemon 监听 `127.0.0.1` only**——由 nginx 在前面 HTTPS 反代 + 终结 TLS
- **单进程 stdlib `http.server.ThreadingHTTPServer`**——无第三方运行时依赖
- **MCP Streamable HTTP 自实现 ~150 行**——6 个 tool，无 MCP SDK

## Docker 部署

镜像发布在 `ghcr.io/yzr95924/agent-html-drop`（多架构 linux/amd64 + linux/arm64）。
`docker compose up -d` 会自动从 GHCR 拉取已发布版本，**不需要本地 build**。
`docker-compose.yaml` 里的 `image:` 字段指向带版本 tag（默认 `:v0.1.0`），不会随 `:latest`
静默换版。想本地重建：在 compose 里去掉 `image:` 前面的 `#` 注释并取消 `build: .` 注释。

把 daemon 打成自包含镜像，用自己的 nginx 反代 HTTP 到容器端口。
**容器自包含**：daemon 自己服务 `/files/*`，nginx 是纯反代、不碰 docroot；TLS 仍在你的 nginx
终结（边缘 HTTPS + 内部 HTTP，`Secure` cookie / CSRF 照常工作）。详见 `docs/design.md` §15。

```bash
# 1. 编辑 docker-compose.yaml：把 PUBLIC_BASE_URL 改成你的 HTTPS origin
# 2. 起服务（首次自动生成 token + config，持久化在 ./data/）
docker compose up -d

# 3. 取 token，配给本机 agent 的 MCP config（url = https://<origin>/mcp）
docker compose exec agent-html-drop agent-html-drop token show

# 4. 拿 nginx 反代片段，贴进你现有 nginx 的 HTTPS server block，reload
docker compose exec agent-html-drop agent-html-drop nginx-config
```

数据与卷（备份 / 迁移就靠这两个目录）：

| 卷 | 容器路径 | 宿主路径 | 用途 |
| --- | --- | --- | --- |
| docroot | `/data/docroot` | `./data/docroot` | HTML + 批注——备份目标 |
| config+token | `/data/config`（→ `…/agent-html-drop/config.toml`） | `./data/config` | 凭据，`0600`，单独备份 |

迁移到另一台机：`scp` 整个 `./data/` + `docker-compose.yaml`（+ 重新 build 镜像）即可。

> **uid 对齐**：容器以非 root（uid 1000）运行。若宿主 `./data/` 所有者不是 uid 1000，
> 写 docroot/config 会权限拒绝——`chown -R 1000:1000 ./data`，或在 compose 里覆盖 `user:`。
>
> **`docker exec` 不走 ENTRYPOINT**：跑子命令要用镜像里的 wrapper，即
> `docker compose exec agent-html-drop agent-html-drop <subcommand>`（service 名与命令名各出现一次）。
>
> 容器冒烟测试：`bash scripts/docker-smoke.sh`（需要 docker）。

容器起来后，在本机 agent 侧配 MCP：

```json
// Claude Code MCP config: ~/.claude.json (或类似)
{
  "mcpServers": {
    "agent-html-drop": {
      "url": "https://<origin>/mcp",
      "headers": {
        "Authorization": "Bearer <docker compose exec agent-html-drop agent-html-drop token show 输出>"
      }
    }
  }
}
```

agent 可以调 6 个 tool：`upload_html` / `list_html` / `delete_html` / `get_public_url`
/ `list_annotations` / `delete_annotation`。
配合 `yzr-md-to-html` 使用流程：`md2html file.md → upload_html(name="file.html", content=...)`。

## 命令一览

```
agent-html-drop init [--force]                  # 创建 config + 生成 token
agent-html-drop serve [--config PATH]           # 前台启动 daemon
agent-html-drop token show                      # stdout 明文 token(CLI 路径,UI 不再使用)
agent-html-drop token rotate                    # 重生成(daemon 需重启才生效)
agent-html-drop config show                     # 打印 config (token 掩码)
agent-html-drop config path                     # 打印 config 路径
agent-html-drop config edit                     # $EDITOR 打开 config
agent-html-drop nginx-config                    # stdout 打印反代片段(location 块)

## 查询 token

token 是 daemon 的凭据，不会出现在管理页 UI / localStorage（设计原则）。
所有查询都走 CLI。两条路径：

**Classic（直接装在宿主）**

```bash
# 明文，打印到 stdout —— 复制粘贴给 agent 的 MCP config
agent-html-drop token show

# Masked（首 4 + **** + 末 4），日常检查 token 是否设置推荐
agent-html-drop config show

# 生成新 token（旧 token 立刻作废，需重启 daemon 才生效）
agent-html-drop token rotate
```

**Docker（容器化部署）**

`exec` 不走 ENTRYPOINT，必须用镜像里的 wrapper —— `agent-html-drop` 在命令里出现两次是正常的：

```bash
# 明文
docker compose exec agent-html-drop agent-html-drop token show

# 或
docker exec <container_name> agent-html-drop token show

# 容器内的 config（含 masked token）
docker compose exec agent-html-drop agent-html-drop config show
```

> **安全提示**：完整 token 会进 shell history / 终端快照 / 屏幕录制。
> 日常查看优先用 `config show`（自动 masked）。想批量管理凭据可：
> `chmod 600 ~/.bash_history`、设 `HISTCONTROL=ignorespace`（命令前加空格不进 history）、
> 或临时 `unset HISTFILE` 再跑。

## Docker 常用命令

集中在这一节，避免翻各处凑。**`compose exec` 一定要写两遍 `agent-html-drop`**（service 名 + 命令名）—— 这是 exec 不走 ENTRYPOINT 的代价。

```bash
# —— 起停 ——
docker compose up -d --build       # 首次：构建镜像 + 后台启动
docker compose up -d               # 已有镜像：直接启动
docker compose restart             # 重启容器（卷 / config 保留）
docker compose down                # 停 + 删容器（卷 ./data 保留）
docker compose down --volumes      # ⚠️ 连 ./data 一起删——会丢 token + 所有 HTML

# —— 状态 / 日志 ——
docker compose ps                  # 容器状态
docker compose logs -f --tail 50   # 实时跟踪最近 50 行
docker compose logs agent-html-drop  # 只看 daemon 输出

# —— 取凭据 / 片段 ——
docker compose exec agent-html-drop agent-html-drop token show     # 明文 token
docker compose exec agent-html-drop agent-html-drop config show    # masked token
docker compose exec agent-html-drop agent-html-drop nginx-config   # nginx location 块
docker compose exec agent-html-drop agent-html-drop status         # config/token/docroot 状态

# —— 调试 / 验证 ——
docker compose exec agent-html-drop sh                             # 进容器 shell
docker compose exec agent-html-drop ls -la /data                   # 看持久化卷
bash scripts/docker-smoke.sh                                       # 一键冒烟：build → /api/health → /files → token
```

**常见踩坑**

- 容器跑一会变 `Restarting`：当前版本（v0.1.0 之前）有此 bug，已修复；升级镜像即可。
- `exec` 报 "executable file not found"：写漏了第二个 `agent-html-drop`。
- 改了 `docker-compose.yaml` 但没生效：要 `docker compose up -d`（不是 `restart`）。
- `data/` 权限拒绝：容器以 uid 1000 跑，`chown -R 1000:1000 ./data` 对齐。
agent-html-drop nginx-config --write [PATH]     # 写到 ~/.config/agent-html-drop/nginx.conf.example
agent-html-drop status                          # 简报:config / token / docroot 状态
```

服务控制（用户级，无 sudo / systemd 依赖）：

```
docker compose start|stop|restart|ps                # 或 docker compose down / up -d
```

> 管理页只读：`GET /` 和 `GET /api/files` 都不鉴权；`DELETE /api/files/<name>` 与
> `GET /api/nginx-config` 仍要 Bearer（给运维 / 脚本用）；`POST /mcp` 仍要 Bearer
> （agent 走）。**管理页里不再有 token 输入框，token 也不进 localStorage**——token
> 只在 server 端 `config.toml` 与本机 agent MCP config 之间手动同步。

## 文件命名 / 大小 / 覆盖规则

- **文件名 regex**：`^[A-Za-z0-9._-]+\.html$`（大小写不敏感匹配 `.html`），≤ 200 字符
- **大小**：默认上限 50 MB（`config.max_file_size` 可调）
- **同名上传**：默认 409 + `-32010`；带 `force=true` 才覆盖
- **公开 URL**：`<config.public_base_url>/files/<name>`（`public_base_url` 为纯 origin）

## 设计文档

- 设计：`docs/design.md`
- 任务书：`docs/tasks.md`

## 发布新版本（维护者）

发布流水线：push 一个 `v*` tag → GitHub Actions 自动 buildx 多架构构建（amd64 + arm64）
→ push 到 `ghcr.io/yzr95924/agent-html-drop` → post-publish smoke（pull + 起容器 + `/api/health`）。
详见 `docs/design.md` §16 / `.github/workflows/release-image.yml`。

```bash
# 1. 确保所有变更已 commit + push 到 master
# 2. 打语义化版本 tag
git tag v0.2.0
git push --tags

# 3. 看 CI：https://github.com/yzr95924/agent-html-drop/actions/workflows/release-image.yml
# 4. 镜像 tag 矩阵：v0.2.0, 0.2, 0.2.0, latest, sha-<short>
#    全部指向同一 manifest list（多架构自动挑）
```

**首次发布**：GHCR 包默认创建为 private。push 后去
<https://github.com/yzr95924/agent-html-drop/settings/packages> 改成 public，
否则别人 `docker pull` 不到。

**失败回滚**：如果 smoke 失败但镜像已推，workflow 标红 ✗ 但镜像留在 GHCR——手动到包页面删
坏 tag 或发一个 patch 版本覆盖；不要自动删，避免误删正在用的版本。

## 测试

```bash
pytest                    # 全量(含 install→serve→MCP→uninstall 冒烟)
pytest tests/test_cli.py -v
```

测试隔离：autouse fixture 把 `~/.config/agent-html-drop/` 重定向到 tmp，并在每个测试结束
校验真实配置目录 mtime 未变——详见 `tests/conftest.py`。

## 局限性

- 不管 nginx 配置 / 不 reload / 不写证书——daemon 只产生反代片段模板，用户自己装
- 不做 mTLS / OAuth（单 Bearer 静态密钥）
- 不做多 docroot / 多租户
- 不存元数据库（title 从 HTML 解析，mtime/size 从 `stat` 取）
- daemon 保活由 Docker 负责（`docker-compose.yaml` 里 `restart: unless-stopped`）
- 管理页只读：list / 预览 / 复制公开 URL 在浏览器完成；**删除** 与 **上传** 只能通过
  agent MCP（本机 Claude Code / OpenCode 调 `delete_html` / `upload_html`），管理页
  故意不做删除按钮 / 上传表单，token 也不在 UI 出现。

## 批注（可选）

管理页支持浏览器侧批注：选中 iframe 中的文本，填评论，提交。批注不影响原始 HTML
文件（`.html` 与 `.meta` 严格分离），所以可以放心反复修改设计稿，批注留档。

启用方式：

1. 进入批注模式：管理页右上角 **"批注(需 token)"** 按钮 → 弹框 → 粘贴 token
   （在 server 端跑 `agent-html-drop token show` 获取）→ 进入。
2. 选中文本 → 弹出评论输入框 → 提交。批注高亮（`<mark>`）自动注入到 iframe。
3. 退出批注模式：点 "退出" 链接。cookie 30 分钟自动过期。

agent 视角：

- `list_annotations(name)` —— 读取某文件的全部批注（结构化字段）
- `delete_annotation(name, id)` —— 删除某条（用于清理 spam / 已解决）
- **不开放** `add_annotation` 给 agent（写批注由浏览器发起）

安全模型：

- 浏览器写批注走短期 session cookie（30 分钟，HttpOnly / Secure / SameSite=Lax）
- agent 改 HTML 走原有 Bearer token
- 两条路径**互不重叠**，agent 无批注写接口，浏览器无 HTML 写接口
- nginx 模板默认带 `limit_req` 防 `/api/auth` 暴力穷举
