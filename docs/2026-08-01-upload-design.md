# agent-html-drop — 设计文档

**状态**：草案 v1（2026-08-01）
**仓库位置**：`yzr-agent-tools/src/agent_html_drop/`（与 `model_switch` 同仓，遵循多工具规约）

## 1. 目的

为 `yzr-md-to-html`（及其它自包含 HTML 生成工具）的产物提供一个常驻的「dropbox + 管理页」：

- 一个**常驻 HTTP 服务**跑在 nginx server 上，监听 `127.0.0.1:8765`
- 对 agent（Claude Code / OpenCode）暴露 **MCP endpoint**（Streamable HTTP，Bearer token 鉴权）
- 对人暴露 **HTML 管理页**（列表 / 预览 / 删除 / 复制公开 URL）
- 把上传的 HTML 文件写到 nginx 服务的 docroot
- 输出一份 nginx server block 示例给用户接入；**不**管 nginx 配置、不 reload

agent 与 nginx server 之间走 **nginx HTTPS 反代**：agent 直连 `https://notes.example.com/mcp`（终止 TLS 的反代把请求转给 `127.0.0.1:8765`）。

## 2. 仓库规约（继承自 `yzr-agent-tools`）

| 规约 | 落实 |
|---|---|
| 测试绝不能触碰真实 `~/.config/agent-html-drop/` 与真实 docroot | `tests/conftest.py` autouse `isolate_agent_html_drop`：快照 `~/.config/agent-html-drop/`，重定向 XDG 解析到 tmp；daemon 端口用 `0`（内核 ephemeral）；teardown 断言真路径字节级一致 |
| Python 3.7+ 兼容；stdlib only（仅 `tomli>=1.1` for <3.11） | 全部用 `argparse` / `http.server` / `json` / `pathlib`；MCP JSON-RPC 自实现，**不**引官方 SDK |
| 未知字段透传 | `config.py` 同 `model_switch/store.py` 的 `extra` 桶规矩 |
| 原子写 | `storage.py` 写文件先 `.tmp` 再 `os.replace()`；config 同理 |
| 不在 import 时副作用注册 | daemon 在 `serve` 子命令内构造，单进程单实例 |
| API key / token 不落盘日志 | auth.py 的 `redact_token()`；storage.py 不打 HTML 内容 |
| daemon 前台跑，保活由用户负责 | 不生成 systemd unit / Docker recipe；README 写一句 hint |

## 3. 体系结构

```
┌──────────────────────┐                ┌──────────────────────────────────────┐
│  本机                 │                │  远端 (nginx server)                 │
│                      │                │                                      │
│  Claude Code /       │   HTTPS        │   ┌────────────────────────────┐    │
│  OpenCode            │ ─────────────► │   │ agent-html-drop daemon            │    │
│                      │  /mcp          │   │  127.0.0.1:8765            │    │
│                      │  Bearer        │   │                            │    │
│                      │                │   │  ├ /mcp    Streamable HTTP │    │
│                      │                │   │  ├ /        HTML 管理页     │    │
│                      │                │   │  ├ /api/    JSON API       │    │
│                      │                │   └────────────┬───────────────┘    │
│                      │                │                │                    │
│  浏览器（人）         │ ──HTTPS──────► │       ┌────────▼────────────┐      │
│   https://notes...   │                │       │ nginx               │      │
│                      │                │       │  listen :443         │      │
│                      │                │       │  serve docroot       │      │
│                      │                │       │  + reverse-proxy     │      │
│                      │                │       │    :8765             │      │
│                      │                │       └─────────┬────────────┘      │
│                      │                │                 │                   │
│                      │                │       /var/www/notes/                │
│                      │                │       ├ index.html (可选)             │
│                      │                │       ├ design.html                  │
│                      │                │       └ ...                          │
└──────────────────────┘                └──────────────────────────────────────┘
```

- 单 Python 进程 = 单 HTTP server = 同时提供 MCP / JSON API / 管理页
- 文件读取（`/files/*`）由 nginx 直读 docroot，不走 daemon
- 所有写操作走 daemon（MCP `tools/call` + HTTP `POST/DELETE`）
- 管理页 `/` 由 daemon 渲染（单文件 vanilla HTML + JS，零运行时依赖）

## 4. 组件与职责

```
src/agent_html_drop/
├── __main__.py            # python -m agent_html_drop 入口
├── __init__.py
├── cli.py                 # argparse：init / serve / token / config / nginx-config / status
├── paths.py               # XDG 路径解析
├── config.py              # config.toml I/O + 未知字段透传（仿 model_switch/store.py）
├── auth.py                # Bearer token 校验 + redact_token() + 常量时间比较
├── server.py              # http.server.ThreadingHTTPServer 装配 + 路由分发
├── mcp_handler.py         # Streamable HTTP MCP transport + tool 注册表
├── storage.py             # docroot 文件 CRUD：原子写、文件名 regex、大小上限、路径穿越防护
├── api.py                 # JSON API 端点：/api/files GET/DELETE、/api/nginx-config、/api/health
├── ui/
│   ├── index.html         # 管理页（vanilla HTML + JS，单文件）
│   └── style.css
└── _version.py
```

| 模块 | 单一职责 |
|---|---|
| `cli.py` | argparse 编排；子命令 dispatch；不写业务逻辑 |
| `paths.py` | XDG 解析：`config_dir` / `config_path` / `nginx_example_path` |
| `config.py` | 读写 `config.toml`；未知键进 `extra`，写回时原样吐出 |
| `auth.py` | 从 `Authorization` 头抠 Bearer；`hmac.compare_digest` 比对；日志脱敏 |
| `server.py` | HTTP server 装配；method 白名单；body 大小限流；路由 dispatch 到 mcp/api/ui |
| `mcp_handler.py` | JSON-RPC 2.0 解析；MCP `initialize` / `tools/list` / `tools/call` 分发；错误码表 |
| `storage.py` | 文件名 regex 校验；`Path.resolve()` 防穿越；`os.replace()` 原子写；冲突检测（大小写不敏感） |
| `api.py` | 管理页用的 JSON 端点；与 MCP 共用 `storage` / `auth` |
| `ui/index.html` | 列表（fetch `/api/files`）+ iframe 预览（`sandbox=""`）+ 删除按钮 + 复制 URL |

**驱动抽象**：本工具没有 driver 抽象（model_switch 那套是为多 agent 适配用的）。`storage` 是唯一可能演进的边界（docroot → S3 / Git），V1 不引入抽象层（YAGNI）。

**MCP 协议自实现**：MCP = JSON-RPC 2.0 + Streamable HTTP。官方 SDK 引入依赖与版本要求；自实现 ~150 行就够 4 个 tool + 3 个标准 method（`initialize` / `tools/list` / `tools/call`）。如未来复杂度上升再切换到 SDK。

## 5. 配置

`~/.config/agent-html-drop/config.toml`（`XDG_CONFIG_HOME` 优先）：

```toml
host = "127.0.0.1"
port = 8765
docroot = "/var/www/notes"
public_base_url = "https://notes.example.com"
max_file_size = 52428800       # 50 MB

[auth]
token = "<64 hex chars>"        # `init` 时生成；chmod 0600
```

**未知字段透**：`config.py` 加载时把不在白名单的顶层 / `[auth]` 键收集到 `extra`，`save()` 时原样写回。

**token 生命周期**：

- `init`：`secrets.token_hex(32)` 生成；写 `[auth] token`
- `token show`：stdout 打印明文（**仅本地运行**，可信终端）
- `token rotate`：重新生成；打印「daemon 需要重启后才生效」
- daemon 启动时把 token 读进内存；运行期读 config 不重读（避免热改引起 confusion）

## 6. docroot 与文件命名

```
/var/www/notes/
├── index.html       # 可选：daemon `init` 时建议放一个简单的占位页（让 nginx 有东西 serve）
├── design.html
└── meeting-2026-08-01.html
```

**命名规则**（`storage.py` 的 `_NAME_RE`）：

- regex：`^[A-Za-z0-9._-]+\.html$`（大小写不敏感匹配 `.html` 后缀）
- 长度 ≤ 200 字符
- 拒绝 `/`、`..`、控制字符、空格、中文
- 冲突检测用 `name.lower()` 比较；写入保留用户写的大小写

**路径穿越防护**：写文件前 `Path.resolve()` 算绝对路径，断言仍在 `docroot.resolve()` 之下。否则抛 `invalid_name`。

**原子写**：写入 `<docroot>/<name>.tmp` → `os.replace()` 到 `<docroot>/<name>`。

**大小上限**：HTTP 层累计 body 字节数，超 `max_file_size` 立即断连 + 返 413，不读进内存。

## 7. MCP 接口

JSON-RPC 2.0 over Streamable HTTP at `POST /mcp`。所有 tool 强制 Bearer。

### Tool: `upload_html`

**输入**：

| 字段 | 类型 | 必选 | 说明 |
|---|---|---|---|
| `name` | string | ✓ | 文件名（含 `.html`） |
| `content` | string | ✓ | HTML 内容（UTF-8） |
| `force` | bool | ✗ | 重名时是否覆盖，默认 `false` |

**输出**：`{ "url": string, "name": string, "size": int }`

**错误**：`invalid_name` / `conflict` / `too_large` / `docroot_unwritable`

### Tool: `list_html`

**输入**：（无）

**输出**：

```json
{
  "files": [
    { "name": string, "size": int, "mtime": int, "url": string, "title": string|null }
  ]
}
```

`title` 是从 HTML `<title>` 标签解析的；解析失败为 `null`。

### Tool: `delete_html`

**输入**：`{ "name": string }`

**输出**：`{ "deleted": bool }`

**错误**：`not_found`

### Tool: `get_public_url`

**输入**：`{ "name": string }`（可以是还没上传的文件 — 提前预览 URL）

**输出**：`{ "url": string }`

### 错误码表

| HTTP | MCP code | 含义 |
|---|---|---|
| 400 | `-32602` | 参数非法（含 `invalid_name`） |
| 401 | `-32001` | 鉴权失败 |
| 404 | `-32020` | 文件不存在 |
| 409 | `-32010` | 同名冲突（未带 `force`） |
| 413 | `-32011` | 超过 `max_file_size` |
| 500 | `-32012` | docroot 不可写 |
| 500 | `-32603` | 内部错误 |
| 405 | — | HTTP method 不在白名单 |

## 8. HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET /api/files` | 列文件（与 MCP `list_html` 同一 JSON 形状） | |
| `DELETE /api/files/<name>` | 删除 | |
| `GET /api/nginx-config` | 渲染 nginx server block 示例（占位符填入 `docroot`/`port`/`public_base_url`） | |
| `GET /api/health` | `{ "status": "ok", "version": "X.Y.Z" }` | |

所有 `/api/*` 强制 Bearer。

## 9. CLI

```
agent-html-drop init [--force]                  # 创建 config 目录 + 默认 config + 生成 token
agent-html-drop serve [--config PATH]           # 前台启动 daemon
agent-html-drop token show                      # stdout 明文 token
agent-html-drop token rotate                    # 重新生成；提示 daemon 需重启
agent-html-drop config show                     # 打印 config（token 掩码）
agent-html-drop config path                     # 打印 config 路径
agent-html-drop config edit                     # $EDITOR 打开 config.toml
agent-html-drop nginx-config                    # stdout 打印 nginx server block
agent-html-drop nginx-config --write [PATH]     # 写到 ~/.config/agent-html-drop/nginx.conf.example（默认）
agent-html-drop status                          # 简报：config path / token 是否已生成 / docroot 是否存在
```

**`init`**：幂等 — 已存在 config 不覆盖（除非 `--force`）。docroot 不存在则提示 `sudo mkdir -p ... && sudo chown $USER ...`，**不**自动 sudo。

**`nginx-config`**：从 `assets/nginx.conf.template`（包内静态资源）渲染。占位符：

- `{{DOCROOT}}` → `docroot`
- `{{PORT}}` → `port`
- `{{PUBLIC_BASE_URL}}` → `public_base_url`

生成的 server block 不写证书路径 — 用户自己填或用 `$ssl_certificate` 变量。

## 10. 安全护栏

1. **路径穿越防护**：`Path.resolve()` 后断言在 `docroot.resolve()` 下
2. **文件名 regex**：`^[A-Za-z0-9._-]+\.html$`
3. **Bearer 常量时间比较**：`hmac.compare_digest`
4. **token 日志脱敏**：`redact_token()` — 保留首 4 / 末 4，中间 `****`
5. **HTML 内容不入日志**：storage 只记 name + size + mtime
6. **method 白名单**：未识别 method 直接 405
7. **body 大小硬限**：HTTP 层累计字节数，超 `max_file_size` 立即断连
8. **管理页 iframe `sandbox=""`**：禁止 iframe 内 JS / 表单 / 同源访问
9. **token 文件权限**：写入 / 修改 `config.toml` 后 `os.chmod(path, 0o600)`；如已有更宽松权限，发出 warning 但不强行收紧（不破坏用户现有所有权）
10. **不解析 HTML**：daemon 不把上传内容当作代码运行 / 解析

## 11. 进程模型与日志

- 单进程 `python -m agent_html_drop serve`，前台运行，Ctrl+C 优雅退出
- SIGTERM：等最多 5 秒让 in-flight 请求完成，再退出
- 启动失败：端口占用 → 退出码 3；配置损坏 → 退出码 2
- 日志：stderr 单行 `[time] [level] [msg]`，level 由 `--log-level` 控制
- 请求日志：`time LEVEL METHOD /path STATUS [tool/tool_args] size`

## 12. 安装与补全

- `bin/agent-html-drop`：bash wrapper（仿 `bin/model-switch`），3 行
- `scripts/install.sh`：在现有 model-switch 安装基础上，追加写 `bin/agent-html-drop` wrapper + 链接 `completions/agent-html-drop.{bash,fish}`
- `scripts/uninstall.sh`：剥离 PATH marker 里的 `bin/`（已经是整个 marker 一起剥，无需区分）+ 移除补全 symlink
- `completions/agent-html-drop.bash`、`completions/agent-html-drop.fish`：覆盖 9 个子命令 + `nginx-config --write` 的 `--write` 参数

## 13. 测试

**隔离机制**（沿用 `yzr-agent-tools` 规约）：

`tests/conftest.py` 新增 autouse fixture `isolate_agent_html_drop`：
- 快照真实 `~/.config/agent-html-drop/` mtime + sha256
- `monkeypatch` `agent_html_drop.paths.*` 解析到 tmp
- `monkeypatch` 默认 docroot 到 tmp 子目录
- daemon 启动端口用 `0`
- teardown 断言 `~/.config/agent-html-drop/` 字节级一致

**测试文件**（粗粒度，覆盖率门槛同 model_switch：≥ 90%）：

```
tests/
├── test_agent_html_drop_paths.py
├── test_agent_html_drop_config.py     # 重点：未知字段透传
├── test_agent_html_drop_auth.py       # 重点：Bearer + redact + timing
├── test_agent_html_drop_storage.py    # 重点：原子写 / 命名 / 大小 / 穿越 / 冲突 / force
├── test_agent_html_drop_mcp.py        # 重点：JSON-RPC 错误码 + 4 个 tool
├── test_agent_html_drop_api.py
├── test_agent_html_drop_server.py     # smoke：路由 + method 白名单
├── test_agent_html_drop_cli.py        # init / serve / token rotate / nginx-config
└── test_agent_html_drop_install.py    # 仿 test_install.py：wrapper / rc / 补全
```

**不追求枚举大量 case** — 用法还会调整；保留**关键不变量**测试：路径穿越、Bearer 鉴权、未知字段透传、原子写、命名 regex、JSON-RPC 错误码。

## 14. 局限与不做

- **不做**：协议转换 / 多 agent 适配 / systemd unit / Docker image / TLS 终结（交给 nginx）/ mTLS / 元数据库 / 自动 reload nginx / 多 docroot / 多租户
- **不做**：上传 `.htm` / `.xhtml` / 非 HTML 文件 — 拒绝（regex 不匹配）
- **不做**：版本化（旧版保留为 `<name>.v<n>.html`）— 显式 force 覆盖
- **不做**：管理页的鉴权 cookie / 登录页 — 直接复用 Bearer token（输入框 → localStorage），单用户信任模型

## 15. 不在范围（V2+ 候选）

- 多 docroot（按 project 分）
- 上传附件（图片 / 字体）— 当前 yzr-md-to-html 输出已自包含，无需
- 管理页编辑 HTML
- 与 yzr-md-to-html 联动：CLI 一个 `md-to-html-and-upload` 命令，省去 agent 两次调用
- E 方案（agent 侧 `agent-html-drop tunnel` 子命令）：如果用户多、跨网连 server 频繁，再加