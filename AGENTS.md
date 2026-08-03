# AGENTS.md

> **关键**：本文件里凡 `@path/to/file` 形式的引用（如 `@MEMORY/MEMORY.md`），都用 Read 工具按需
> 读取——它们与你**当前任务**直接相关。不自动展开 `@import` 的 agent 尤须手动执行，否则漏上下文。

## 项目定位

`agent-html-drop` 是一个常驻 HTTP daemon：让本机 AI coding agent
通过 MCP（Streamable HTTP）把 `yzr-md-to-html` 等产出的自包含 HTML 推到远端 nginx server，
同时提供一个浏览器管理页（列表 / 预览 / 删除 / 复制公开 URL）与可选的浏览器侧批注。

前身是 `yzr-agent-tools` 仓库里的 `html-mcp`，2026-08 独立成单工具仓库并更名。

> **文档分层**：本文件承载 agent 工作上下文（规约 / 命令 / 架构）；**用户文档**（安装 /
> 快速上手 / 命令一览 / 局限性）见根 `README.md`。**设计文档**在 `docs/`（`design.md` +
> `tasks.md` + 决策日志）。

## 仓库规约

- **测试绝不能触碰真实的服务配置**（`~/.config/agent-html-drop/`——线上 daemon 的
  config.toml / token 就在那里）。`tests/conftest.py` 的 autouse fixture 强制：snapshot
  真实配置目录的 mtime，重定向 `paths.*` 到 tmp，测试结束后断言未变。
- **Python 3.7+ 兼容**。pyproject 固定 `tomli>=1.1`（<3.11 时）。CLI 用 stdlib `argparse`，
  无第三方运行时依赖。禁 `dict[str, str]` 语法、walrus、`match`；用 `from typing import Dict, List, Optional`。
- **config TOML 必须透传未知字段**（`config.py` 读写往返不丢用户自定义键）。
- **原子写文件**。TOML 与 docroot 文件都先写 `.tmp` 再 `os.replace()`，永远不出现半写状态。
- **路径穿越防护**：所有文件名过 `^[A-Za-z0-9._-]+\.html$` regex，绝不拼接未校验的用户输入进路径。

<!-- ↓ 默认启用：repo-local 记忆管理（让多 agent 共用同一份 MEMORY/，而非各自私有 memory）。
     记忆跟 repo 走——本注释 + 以下规约 + 下方「跨会话记忆（索引）」段一律保留（R6）。 -->
- 跨会话需持久化的"为什么 / 边界规则"写入根目录 `MEMORY/`（`MEMORY.md` 是索引），**禁写** agent
  私有 memory——私有路径不随仓迁移 / 不进 git / 多 agent 各写各的会分裂成 N 份。
  - 完整 memory（设计决策 / 工作流约束）→ `MEMORY/<slug>.md`，带 frontmatter 三件套：
    `name`(=文件 slug) + `description`(≤200 字符事实摘要) + `metadata.type`(user|feedback|project|reference)
  - 短 memory（一句话事实）→ 直接写 `MEMORY.md` 索引行，不单独建文件

## 常用命令

```bash
# 容器化（2026-08-02 起为唯一种部署模式；详见 docs/design.md §15）。
# daemon 自服务 /files/*、nginx 退化为纯反代；TLS 在边缘 nginx 终结，容器内纯 HTTP。
docker compose up -d --build                    # 首次自动种 config + token（持久化在 ./data/）
docker compose exec agent-html-drop agent-html-drop token show   # 取 token（exec 不走 ENTRYPOINT，用 wrapper）
bash scripts/docker-smoke.sh                    # 容器冒烟（build→/api/health→/files→token，需 docker）

# 测试 — 需要 pytest + pytest-cov 自装（pip install --user pytest pytest-cov）。
# pyproject.toml 的 [tool.pytest.ini_options].pythonpath 已含 src/，
# 不需要 `pip install -e .` 也能 import agent_html_drop。
pytest
pytest tests/test_cli.py -v                   # 单文件
pytest --cov=agent_html_drop                  # 带覆盖率

# CLI 自身
agent-html-drop init                            # 初始化 ~/.config/agent-html-drop/,生成 bearer token
agent-html-drop serve                           # 前台启动 (Ctrl+C 停);生产建议 tmux / systemd 用户单元
agent-html-drop token show                      # 打印 token,配到 agent MCP config
agent-html-drop nginx-config                    # 打印 nginx 反代片段到 stdout
agent-html-drop nginx-config --write            # 写到 ~/.config/agent-html-drop/nginx.conf.example
agent-html-drop status                          # config / token / docroot 状态
```

## 高层结构

```
src/
└── agent_html_drop/           # 常驻 daemon(单包)
    ├── cli.py                 argparse (init / serve / token / config / nginx-config / status)
    ├── __main__.py            python -m agent_html_drop 入口
    ├── _version.py            VERSION 字符串 (/api/health + CLI --version)
    ├── paths.py               XDG 路径解析 (~/.config/agent-html-drop)
    ├── config.py              TOML I/O + 透传未知字段 + validate_for_serve
    ├── auth.py                Bearer token 常量时间比较 + redact_token
    ├── auth_anno.py           批注 session cookie(30 分钟,HttpOnly/Secure/SameSite=Lax)
    ├── _legacy_storage.py     docroot 文件 CRUD (atomic write / 命名 regex / 路径穿越防护)
    ├── storage/               批注存储 (annotations.py,.meta 与 .html 严格分离)
    ├── server.py              http.server.ThreadingHTTPServer + 路由 + body 限流
    ├── mcp_handler.py         JSON-RPC Streamable HTTP + 6 个 tool
    ├── api.py                 /api/files /api/nginx-config /api/health /api/auth /api/annotations
    ├── nginx_config.py        assets/nginx.conf.template 渲染
    ├── ui.py                  ui/{index.html,style.css,app.js} 静态路由
    ├── _compat.py             TOML loader (tomllib/tomli) + 手写 dumper
    ├── assets/
    │   └── nginx.conf.template  nginx server block 模板(含 /api/auth limit_req)
    └── ui/                    管理页静态资源 (vanilla JS;批注模式状态机 + iframe <mark> 注入 + 选区→批注提交)
```

### 形态要点

daemon 监听 `127.0.0.1:8765`（默认），由 nginx 在前面 HTTPS 反代 + 终结 TLS。同一进程暴露 4 类入口：

- `POST /mcp` —— MCP Streamable HTTP（agent 走这里，`Authorization: Bearer <token>` 强制）
- `GET /` —— HTML 管理页（浏览器，只读；批注模式走 session cookie）
- `* /api/*` —— JSON API（管理页背后；DELETE 等写操作仍要 Bearer）
- `/files/*` —— 经典模式 nginx 直接从 docroot 读取；**容器模式（§15.3.1）由 daemon 自服务**（流式 + 路径穿越防护），nginx 退化为纯反代。两种模式都无 auth（公开 docroot）

MCP 工具（`tools/call`）：`upload_html` / `list_html` / `delete_html` / `get_public_url`
/ `list_annotations` / `delete_annotation`。MCP 协议自实现，无第三方 SDK 依赖。

详见 `docs/design.md` / `docs/tasks.md`。

## 跨会话记忆（索引）

@MEMORY/MEMORY.md

## 注意事项

- 管理页**故意**只读：删除 / 上传只能走 agent MCP；token 不进 UI、不进 localStorage。
- 批注写路径（浏览器 session cookie）与 HTML 写路径（agent Bearer）**互不重叠**；
  agent 无 `add_annotation`，浏览器无 HTML 写接口。
