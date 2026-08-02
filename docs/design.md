# agent-html-drop 设计文档

> **迁移注记（2026-08-02）**：本工具原为 `yzr-agent-tools` 仓库的 `html-mcp`，已独立为单工具仓库
> `agent-html-drop` 并更名（包 `agent_html_drop`，配置目录 `~/.config/agent-html-drop`）。本文成文于
> monorepo 时期，涉及的同仓工具（model-switch 等）与仓库级路径描述均为历史背景。

> 元信息（评审流转的跟踪字段，全部必填；无评审人写"待定"）：
>
> | 状态 | 作者 | 评审人 | 创建日期 | 更新日期 | 关联需求 / 链接 |
> | --- | --- | --- | --- | --- | --- |
> | V1 已实现；容器化扩展草稿 | Zuoru YANG | 待定 | 2026-08-01 | 2026-08-02 | 容器化扩展见 §15；上游 skill：`~/yzr-SKILL/yzr-md-to-html/` |

> **章节分层**：§1–5 **需求层**（不依赖实现：为什么做 / 做什么 / 做成什么样）→ §6–10 **方案层**
> （怎么做）→ §11–14 **落地层**（怎么拆解执行、怎么上线、何时交付）；§13 开放问题贯穿两层。
> 评审顺序同理：先对齐需求层，再进方案层争怎么做。

## 1. 背景与现状

`yzr-agent-tools` 当前只有一根独苗：`model-switch`——一个改写 agent 全局配置的 stdlib-only CLI。
本次新增第二个工具 `agent-html-drop`：在远端 nginx server 上跑一个常驻 HTTP 服务，让 AI agent
（Claude Code / OpenCode …）通过 MCP 把 `yzr-md-to-html` 等工具产出的自包含 HTML 推上去，
并提供一个 HTML 管理页供人浏览 / 删除 / 复制公开 URL。

**远端"分发 HTML"这条路目前怎么做的（痛点来源）**：

`yzr-md-to-html` 的 `--deploy <target>` 走 **rsync + SSH**：agent 在本机跑 skill，
skill 把产出的单文件 HTML 经 `rsync` over `ssh user@server` 推到远端 docroot。

**痛点（量化 + 形容词）**：

| # | 痛点 | 量化 |
| --- | --- | --- |
| 1 | 每次上传都是 agent 本机 → 跨网 SSH → 远端落盘 | 一次 doc（~5 MB）跨网 SSH 实测 800–1500 ms；上传 100 篇 ≈ 100 次 SSH 调用 |
| 2 | 远端没有浏览 / 删除 / 复制 URL 的页面 | 100% 用户只能手 ls docroot 或让 nginx 列目录 |
| 3 | agent 跨会话无法查"我上次传了哪些" | 0% 可查询——只能重传 |
| 4 | CI / 无 ssh agent 环境用不了 `--deploy` | 100% 不可用 |
| 5 | 多份文档并发上传（CI 批量）会触发 n 次 SSH | n 次握手 / n 次密钥验证 |

**为什么现在做**：

agent 想主动把 HTML 推到 server 端、希望 server 端可观测 / 可治理——一条稳定 HTTP
通道比 SSH 反复握手更适合这个场景；同时给"已经堆了几十篇 HTML 的 docroot"补一个管理 UI。

**上下文链接**：

- 仓库规约：[AGENTS.md](../../AGENTS.md)（测试隔离、原子写、未知字段透传、stdlib only）
- yzr-md-to-html：[`~/yzr-SKILL/yzr-md-to-html/SKILL.md`](../../../yzr-SKILL/yzr-md-to-html/SKILL.md)

**假设清单**（评审时逐条确认）：

- **A1**：Claude Code / OpenCode 支持 MCP Streamable HTTP transport（不能只走 stdio / SSE）
- **A2**：远端 server 由用户管（systemd / 包管理 / certbot / sudo 都能用）
- **A3**：单用户信任模型，无多租户 / 多 docroot
- **A3'**：单 token 范式——agent 改 HTML 与浏览器写批注共用同一 Bearer token，浏览器在"批注模式"下临时出示以获得短期 session cookie；不引入多 token / 多角色
- **A4**：上传的 HTML 都是"自包含的 UTF-8 文本 HTML"（`yzr-md-to-html` 的产物形态，CSS / Pygments 内联）
- **A5**：docroot 用 ext4 / tmpfs / xfs / 之类标准 POSIX fs，符号链接行为正常
- **A6**：nginx ≥ 1.18（HTTP/2 + TLS SNI + 反代基本盘）
- **A7**：远端 server 与 agent 本机之间的网络延迟 < 100 ms（局域网 / VPN / 同 IDC）

## 2. 目标与非目标

**目标**（每条可验证）：

- **G1**：agent 调 `tools/call upload_html` 上传 ≤ 50 MB HTML 文件，P99 < 1 s（局域网）
- **G2**：agent 能通过 MCP `list_html` / `delete_html` / `get_public_url` 完整管理 docroot
- **G3**：浏览器访问 `https://<public_base_url>/` 后能浏览 / 删除 / 复制公开 URL，无需其它登录
- **G4**：远端 server 接入只需 1 份 nginx server block + 1 次 daemon 启动；失败 / 冲突 / token 错配都有清晰处置
- **G5**：`pytest --cov=agent_html_drop` 覆盖率 ≥ 90%（同 model_switch 现有门槛）
- **G6**：测试绝不能触碰真实的 `~/.config/agent-html-drop/` 或真实 docroot（继承 `yzr-agent-tools` 测试隔离规约）

**非目标**（本期明确不做）：

- **N1**：不做协议转换（OpenAI ↔ Anthropic 翻译层等）
- **N2**：不管 nginx 配置 / 不 reload / 不写证书 / 不动 `/etc/`
- **N3**：不做 mTLS / OAuth / 多 token（单 Bearer 静态密钥）
- **N4**：不做多 docroot / 多项目（V1 一个 daemon = 一个 docroot）
- **N5**：不做 systemd unit / launchd plist（README 一句 hint）。~~Docker image~~——**2026-08-02 变更**：新增容器化部署模式（§15），N5 中「Docker image」部分撤销；systemd / launchd 仍不做
- **N6**：不存元数据库（mtime / size 从 `stat()` 取；title 从 HTML 解析）
- **N7**：不上传非 `.html` 文件（regex 拒绝）
- **N8**：不做管理页长期登录 / session；批注写接口用"用户主动出示 token + 短期 cookie"的临时模式，不引入持久身份系统
- **N9**：不做上传时自动渲染 mermaid / KaTeX 检查——daemon 不解析 HTML
- **N10**：不做批注的多人协作 / 权限分级 / author 身份管理；单 token 范式延续到批注层
- **N11**：不做 agent 端写批注——批注由浏览器发起，agent 仅读 + 删（V1）

## 3. 功能点拆解

| 编号 | 功能点 | 优先级 | 设计落点 |
| --- | --- | --- | --- |
| F1 | agent 通过 MCP `upload_html` 上传文件 | P0 | §7.1, §7.3 |
| F2 | agent 通过 MCP `list_html` 列文件 | P0 | §7.3 |
| F3 | agent 通过 MCP `delete_html` 删文件 | P0 | §7.3 |
| F4 | agent 通过 MCP `get_public_url` 查 URL | P1 | §7.3 |
| F5 | 管理页列出所有文件 + 元数据 | P0 | §7.3, §9.3 |
| F6 | 管理页 iframe 预览（sandbox） | P1 | §9.3 |
| F7 | 管理页删除文件（带确认） | P0（**本期不做**——管理页只读，删除走 agent MCP `delete_html`） | §7.3 |
| F8 | 管理页一键复制公开 URL | P1 | §7.3 |
| F9 | `agent-html-drop init` 创建 config + 生成 token | P0 | §7.3, §12 |
| F10 | `agent-html-drop serve` 前台启动 daemon | P0 | §7.1 |
| F11 | `agent-html-drop token show / rotate` | P0 | §7.3 |
| F12 | `agent-html-drop config show / path / edit` | P2 | §7.3 |
| F13 | `agent-html-drop nginx-config` 输出 server block | P0 | §7.3, §12 |
| F14 | `agent-html-drop status` 简报 | P2 | §7.3 |
| F15 | install.sh 写入 wrapper + bash/fish 补全 | P0 | §7.4, §12 |
| F16 | config.toml 未知字段透传 | P0 | §7.2 |
| F17 | 上传同名默认拒绝、`force=true` 覆盖 | P0 | §4, §7.3 |
| F18 | 路径穿越 / 文件名非法 / 鉴权失败 / 磁盘满 各有清晰错误码 | P0 | §7.3, §8 |
| F19 | 管理页头部"批注(需 token)"按钮 → 进入批注模式弹 token 框 | P0 | §3 入口形态, §9.3 |
| F20 | `POST /api/auth` 提交 token → 签发短期 session cookie | P0 | §7.3, §9.3 |
| F21 | 浏览器写 / 改 / 删批注（边车 `.html.meta` JSON） | P0 | §7.2, §7.3, §9.3 |
| F22 | 浏览器在 iframe 选区触发批注提交；quote 从 `getSelection()` 取得 | P1 | §9.3 iframe 注入 |
| F23 | agent 通过 MCP `list_annotations` 读 / `delete_annotation` 删 | P0 | §7.3 |
| F24 | `list_html` 出参含每文件 `annotation_count` | P1 | §7.3 |
| F25 | 批注 quote 在 iframe 失配时显示 ⚠️ 但保留 comment 文本 | P1 | §9.3 容错 |

## 4. 功能规格与约束

**功能规格**（精确规则 / 数值 / 默认策略 / 硬约束）：

- **文件名 regex**：`^[A-Za-z0-9._-]+\.html$`（大小写不敏感匹配 `.html` 后缀）
- **文件名长度**：≤ 200 字符
- **冲突检测**：用 `name.lower()` 比较；保留用户写的大小写
- **单文件大小上限**：默认 50 MB（`max_file_size = 52428800`），可配
- **同名上传默认行为**：拒绝（HTTP 409 / MCP `-32010`）；传 `force=true` 才覆盖
- **Bearer token**：`secrets.token_hex(32)` 生成；存 `[auth] token`；config 文件 `chmod 0600`
- **token rotate 行为**：写盘后立即生效；daemon 必须重启才用新 token；stdout 给出 hint
- **HTTP method 白名单**：daemon 仅接受路径声明里的 method；其它直接 405
- **HTTP body 限流**：累计 body 字节数超 `max_file_size` 立即断连 + 413（不读完整 body）
- **路径穿越防护**：写文件前 `Path.resolve()` 算绝对路径，断言仍在 `docroot.resolve()` 下
- **iframe sandbox**：管理页预览 iframe 加 `sandbox="allow-same-origin"`（禁用 JS / 表单 / 弹窗；**允许同源**以便主页面注入 `<mark>` 高亮）
- **Bearer 比较**：`hmac.compare_digest` 常量时间
- **docroot**：扁平结构，文件直存 `<docroot>/<name>`；批注以 `<docroot>/<name>.meta` 边车 JSON 文件存储
- **批注 schema**：每条 `{id: ulid, quote: str, comment: str, author: "tk_<sha256[:8]>", ts: int}`；quote 用于 iframe 高亮定位，author 由 token 哈希得到（不可逆），同 token 多次提交 author 一致
- **批注 cookie TTL**：30 分钟；`HttpOnly; Secure; SameSite=Lax`，无 refresh，关闭浏览器即失效
- **批注写入口形态**：管理页 header 右上角"批注(需 token)"按钮 → 点击弹 token 输入对话框 → 校验通过后激活批注模式（高亮 + 选区 + 提交）。普通浏览者**不主动看到批注 UI 控件**——按钮文案明示"需 token"
- **CSRF 防护**：批注写 API（`POST/PATCH/DELETE`）双层防御——`SameSite=Lax` cookie + 服务端 `Origin` 头校验（Origin 存在时必须等于 `https://<Host>`）
- **nginx 限流**：`/api/auth` 与所有批注写接口经 `limit_req zone=auth limit=10r/s` 防暴力穷举；token 256 bit 随机本身已不可能穷举
- **mtime / size 读取**：`os.stat()` 取
- **title 解析**：`re.search(r'<title>(.*?)</title>', content, re.DOTALL | re.IGNORECASE)`；解析失败返 `null`
- **公开 URL**：`public_base_url.rstrip('/') + '/files/' + name`（**2026-08-02 变更**：加 `/files/` 路径段，修既有脚枪——原先 `public_base_url + '/' + name` 无 `/files/`，与 nginx `/files/` 路由及前端预览 iframe 不一致，迫使用户把 `/files` 偷偷塞进 `public_base_url`。现 `public_base_url` 语义为「纯 origin」。**迁移**：旧 `public_base_url` 若含 `/files` 需去掉，否则双 `/files/files/`。详见 §15.3.2）（name 不再做 URL encode——regex 已限定安全字符）
- **MCP 协议**：JSON-RPC 2.0 + Streamable HTTP at `POST /mcp`
- **管理页**：单文件 `index.html`（vanilla HTML + JS，无第三方运行时依赖）
- **JSON API**：与 MCP 共用 storage / auth；shape 与 MCP tool 出参保持一致

**约束**（限制解空间）：

- **技术约束**：
  - Python 3.7+
  - 运行时仅 `tomli>=1.1`（<3.11 时）
  - 不引官方 MCP Python SDK；JSON-RPC 自实现约 150 行
  - HTTP server 用 stdlib `http.server.ThreadingHTTPServer`
- **业务约束**：HTML 内容是用户上传给自己的内容，daemon **不解析 / 不执行 / 不隔离 XSS**（信任模型）
- **兼容约束**：现有 `yzr-agent-tools` 的 `install.sh` / `uninstall.sh` / `completions/` **扩展**而非重写
- **部署约束**：经典模式 daemon 监听 `127.0.0.1` only（默认 `8765`），**不**直接暴露公网；容器模式（§15）daemon 在容器内 bind `0.0.0.0`，compose 以 `127.0.0.1:8765:8765` 发布到宿主 loopback——公网仍不可达，只用户 nginx 可访问
- **进程约束**：单进程 = 单 daemon；不引入多 worker / 异步框架
- **可移植约束**：macOS / Linux 行为一致（不依赖 `/proc`、不依赖 systemd）

## 5. 场景拆解

全量场景枚举表（"设计前先穷举"——既是覆盖性自检，也是验收清单）。

| 编号 | 场景 | 类型 | 触发条件 | 期望行为 | 设计落点 |
| --- | --- | --- | --- | --- | --- |
| S1 | 首次部署 | 主流程 | 用户 ssh 进 server，跑 `agent-html-drop init` | config 创建、token 生成、docroot 不存在给 hint、stdout 打印 token | §7.3, §12 |
| S2 | 接入 nginx | 主流程 | 跑 `agent-html-drop nginx-config --write`，拷到 sites-available, reload | nginx serve `https://notes.example.com` | §7.3, §12 |
| S3 | 启动 daemon | 主流程 | 跑 `agent-html-drop serve` | 监听 127.0.0.1:8765；stderr 打印 access 日志 | §7.1 |
| S4 | agent upload | 主流程 | `tools/call upload_html` 带合法 name + content | 写到 docroot；返 `{url, name, size}` | §7.3 |
| S5 | agent list | 主流程 | `tools/call list_html` | 列出所有 `.html`，含 mtime/size/title/url | §7.3 |
| S6 | agent delete | 主流程 | `tools/call delete_html` 带合法 name | 从 docroot 删；返 `{deleted:true}` | §7.3 |
| S7 | agent get_public_url | 主流程 | `tools/call get_public_url` 带 name | 返 `{url}`（无论文件是否存在） | §7.3 |
| S8 | 人进管理页 | 主流程 | 浏览器开 `https://notes.example.com/` | 直接显示列表（无 token 输入框）；fetch `/api/files` 无 Bearer | §7.3 |
| S9 | 人预览文件 | 分支 | 点文件名 | iframe 加载 `/files/<name>.html`，sandbox 隔离 | §9.3 |
| S10 | 人删文件 | 撤销 | — | 管理页不做删除按钮；用户让 agent 调 `delete_html` 工具 | §7.3 |
| S11 | 人复制公开 URL | 分支 | 点 Copy URL | `navigator.clipboard.writeText` + toast | §7.3 |
| S12 | 重名上传未带 force | 异常 | upload 同名 | 409 + MCP `-32010` | §7.3, §8 |
| S13 | 重名上传带 force | 主流程 | upload 同名 + `force=true` | 覆盖；200 | §7.3 |
| S14 | 文件名非法 | 异常 | name 含 `/` / `../` / 控制字符 | 400 + invalid_name | §7.3, §8 |
| S15 | 文件超大 | 异常 | content > 50MB | 累计字节数超限；断连；413 | §7.3, §8 |
| S16 | Bearer 缺失 | 异常 | 请求无 Authorization | 401 | §7.3, §8 |
| S17 | Bearer 错误 | 异常 | token 错 | 401 | §7.3, §8 |
| S18 | 删除不存在的文件 | 异常 | delete 不存在的 name | 404 | §7.3, §8 |
| S19 | docroot 不可写 | 异常 | docroot 不存在 / 权限不够 | 500 + docroot_unwritable | §8 |
| S20 | 端口被占 | 异常 | 8765 已被占 | 退出码 3 | §8 |
| S21 | config 损坏 | 异常 | `tomli.loads()` 失败 | 退出码 2 + stderr 报错 | §8 |
| S22 | token rotate 不重启 daemon | 分支 | rotate 后 daemon 仍跑 | daemon 用旧 token；rotate 输出"需重启" | §7.3 |
| S23 | nginx-config 打印 | 主流程 | 跑 `agent-html-drop nginx-config` | 读 template，替换占位符，stdout | §7.3 |
| S24 | nginx-config --write | 分支 | 同上 + `--write` | 写 `~/.config/agent-html-drop/nginx.conf.example` | §7.3 |
| S25 | daemon 优雅退出 | 分支 | Ctrl+C / SIGTERM | 等 in-flight 请求最多 5s；exit 0 | §9.2 |
| S26 | install 重跑 | 分支 | 已有 PATH marker | 不重复添加 | §7.4 |
| S27 | uninstall 后 | 分支 | uninstall.sh 跑过 | wrapper / PATH marker / 补全 symlink 全清 | §7.4 |
| S28 | 文件名大小写变体 | 分支 | 先传 `Design.HTML`，再传 `design.html` | 第二次视为同名冲突（大小写不敏感） | §4, §7.3 |
| S29 | nginx 配置错误 | 异常 | 用户填错 server block | nginx reload 失败；daemon 不感知 | §8, §12 |
| S30 | daemon 进程死 | 异常 | OOM / 段错误 | 端口释放；外部 502；用户手动重启 | §8, §9.2 |
| S31 | config 已有 init | 分支 | init 时 config 已存在 | 默认拒绝（除非 `--force`） | §7.3 |
| S32 | token 文件权限被改宽 | 分支 | 用户手 chmod 644 | daemon 启动时 warning 但不阻止 | §7.3, §9.3 |
| S33 | 大小写重名 + force | 分支 | S28 第二次带 force=true | 覆盖；200 | §4 |
| S34 | content 为空 | 分支 | upload 空字符串 content | 写入 0 字节文件；200 | §7.3 |
| S35 | title 解析失败 | 分支 | HTML 无 `<title>` | list_html 该项 `title=null` | §7.3 |
| S36 | 浏览器进入批注模式 | 主流程 | 头部"批注(需 token)"按钮点击 → 弹 token 输入框 → 提交 | `POST /api/auth` 校验通过 → 签发短期 cookie → 页面进入批注模式 | §7.3, §9.3 |
| S37 | 浏览器提交新批注 | 主流程 | 批注模式下在 iframe 选中文本 → 弹框写评论 → 提交 | `POST /api/files/<name>/annotations` 写 `<name>.meta`(atomic write)；iframe 重新扫描高亮；侧栏更新 | §7.3, §9.3 |
| S38 | 浏览器改 / 删自己批注 | 主流程 | 批注模式下点侧栏笔 / 垃圾桶 | `PATCH / DELETE /api/files/<name>/annotations/<id>`；author 校验通过(hash(token) == entry.author) | §7.3, §9.3 |
| S39 | agent 看批注改进文档 | 主流程 | agent 调 `list_annotations(name)` → 改 md → `upload_html(force=true)` | 改 .html 不动 .meta；批注留档，失效 quote 标 ⚠️ | §7.3 |
| S40 | agent 删 spam 批注 | 分支 | agent 调 `delete_annotation(name, id)` | 不要求 author 匹配(token 已是 agent 凭据) | §7.3 |

---

—— 方案层：怎么做 ——————————————————————————

## 6. 方案总览

**核心思路**：在远端 nginx server 上跑一个 Python daemon（`agent-html-drop serve`），同时提供
MCP Streamable HTTP endpoint（agent 走）+ HTML 管理页（人走）+ JSON API（页面背后）。
所有写操作走 daemon，文件读由 nginx 直接从 docroot serve。daemon 与 nginx 在同一台机器，
daemon 监听 `127.0.0.1:8765`，nginx HTTPS 反代 `:443 → :8765`。所有非文件读请求强制
Bearer 鉴权。

**整体流程图**：

```
┌──────────────────────┐                ┌──────────────────────────────────────┐
│  本机                 │                │  远端 (nginx server)                 │
│                      │                │                                      │
│  Claude Code /       │   HTTPS        │   ┌────────────────────────────┐    │
│  OpenCode            │ ─────────────► │   │ agent-html-drop daemon            │    │
│                      │  /mcp          │   │  127.0.0.1:8765            │    │
│                      │  Bearer        │   │                            │    │
│                      │                │   │  ├ POST /mcp  MCP server   │    │
│                      │                │   │  ├ GET  /      HTML 页      │    │
│                      │                │   │  ├ *     /api/  JSON API   │    │
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
│                      │                │       ├ design.html                  │
│                      │                │       └ meeting-2026-08-01.html     │
└──────────────────────┘                └──────────────────────────────────────┘
```

**关键设计决策速览**（每条一句话，细节指 §7 / §10）：

1. **daemon 监听 localhost，由 nginx 反代**——TLS 终结交给 nginx（经典模式；容器模式见 §15——daemon 在容器内 bind `0.0.0.0`、由 compose 发布到宿主 loopback，对外形态仍是「nginx 反代 HTTP 到本地端口」）
2. **单进程 stdlib `http.server.ThreadingHTTPServer`**——满足单用户低并发
3. **MCP JSON-RPC 自实现 ~150 行**——4 个 tool 需求，SDK overkill
4. **docroot 是唯一存储，不存元数据**——mtime/size 从 stat 取；title 从 `<title>` 解析
5. **Bearer 静态 token 单密钥**——MCP endpoint + 管理页共用；rotate 需 daemon 重启
6. **管理页 inline JS + iframe sandbox**——单 HTML 文件，vanilla JS fetch
7. **测试隔离 autouse fixture**——继承 model_switch 规约：快照真配置、重定向 XDG、daemon 端口 0

## 7. 详细设计

### 7.1 流程与状态机

**7.1.1 daemon 启动时序**

```
agent-html-drop serve [--config PATH]
  │
  ├─ 读 config（默认 ~/.config/agent-html-drop/config.toml）
  │    ├─ 不存在 → 报错退出（提示跑 init）
  │    └─ TOML 损坏 → 报错退出（退出码 2）
  ├─ 校验必填字段：host/port/docroot/public_base_url/auth.token/max_file_size
  ├─ 检查 docroot：不存在/不可写 → 警告（仍可启动，read-only 模式）
  ├─ 构造 ThreadingHTTPServer((host, port), Handler)
  ├─ 注册路由表：
  │    POST /mcp           → mcp_handler.handle_jsonrpc
  │    GET  /              → ui.serve_index
  │    GET  /api/files     → api.list_files
  │    DELETE /api/files/<name> → api.delete_file
  │    GET  /api/nginx-config → api.nginx_config
  │    GET  /api/health    → api.health (无鉴权)
  ├─ 注册 signal handler：SIGINT/SIGTERM → graceful_shutdown
  ├─ server.serve_forever()
  └─ (signal) → server.shutdown() → 等 in-flight ≤ 5s → sys.exit(0)
```

**7.1.2 MCP upload 时序**

```
agent (Claude Code)
  │ POST /mcp
  │ Authorization: Bearer <token>
  │ {"jsonrpc":"2.0","id":1,"method":"tools/call",
  │  "params":{"name":"upload_html",
  │            "arguments":{"name":"design.html",
  │                          "content":"<html>...</html>",
  │                          "force":false}}}
  ▼
daemon: mcp_handler.handle_jsonrpc
  │
  ├─ auth.require_bearer(headers) → 失败 401 / -32001
  ├─ 解析 JSON-RPC envelope → 失败 -32600
  ├─ method == "tools/call" + params.name == "upload_html"
  │
  storage.upload_html(name, content, force)
  │
  ├─ validate_name(name) → 失败 invalid_name / -32602
  ├─ 检查 docroot 可写 → 失败 docroot_unwritable / -32012
  ├─ 检查大小：累计 len(content.encode('utf-8')) ≤ max_file_size → 失败 too_large / -32011
  ├─ target_path = (docroot / name).resolve()
  │    └─ 断言 startswith(docroot.resolve()) → 失败 invalid_name
  ├─ 冲突检测：target_path.exists() and not force → 抛 Conflict / -32010
  ├─ 写：tmp = target_path.with_suffix(target_path.suffix + '.tmp')
  │    ├─ open(tmp, 'w', encoding='utf-8') → write(content)
  │    ├─ (finally) tmp.unlink(missing_ok=True) 失败时清理
  │    ├─ os.chmod(target_path, 0o644) (写完才 chmod)
  │    └─ os.replace(tmp, target_path)
  ├─ public_url = public_base_url + '/' + name
  └─ 返 { name, size, url }
  │
  ▼
agent: 收到 { "result": { "content": [{"type":"text","text":"{...}"}] } }
```

**7.1.3 token rotate 时序**

```
agent-html-drop token rotate
  │
  ├─ 读 config.toml
  ├─ secrets.token_hex(32) → new_token
  ├─ 写回 [auth].token = new_token（保留其它字段 / 未知字段）
  ├─ os.chmod(config_path, 0o600)
  ├─ stdout: "Token rotated. Restart `agent-html-drop serve` to use the new token.\n  new token: <token>"
  └─ exit 0
```

daemon **不监听** config 变化——rotate 不通知 daemon（避免热改引起 confusion）；
rotate 输出明确"需重启"。

**7.1.4 状态机**

docroot 中的单个 HTML 文件只有 3 个稳定状态：无 / 存在 / 正在写（`.tmp` 存在）。
不存在版本化 / lock 概念。

```
  ┌─────────────┐
  │ 不存在       │◄───────────────────────────────┐
  └──────┬──────┘                                │
         │ upload(name, force=false)             │
         │ (无冲突)                                │
         ▼                                        │
  ┌─────────────┐                                │
  │ 存在         │──── upload(name, force=true) ──┤
  │ (target.html)│      (覆盖)                    │
  └──────┬──────┘                                │
         │ delete(name)                            │
         ▼                                        │
  ┌─────────────┐                                │
  │ 正在写       │  (os.replace 原子)              │
  │ (target.html │───────────────────────────────┘
  │  .tmp)      │
  └─────────────┘
```

### 7.2 数据设计

**config.toml schema**：

```toml
host: str                  # 默认 "127.0.0.1"
port: int                  # 默认 8765
docroot: str               # 默认 "/var/www/notes"
public_base_url: str       # 默认 "https://notes.example.com"
max_file_size: int         # 默认 52428800 (50 MB)

[auth]
token: str                 # secrets.token_hex(32); chmod 0600
```

**未知字段透传**（F16）：`config.py` 加载时把不在白名单的顶层 / `[auth]` 键收集到 `extra`，`save()` 时原样写回。同 `model_switch/store.py` 的 `extra` 桶规矩。

**docroot 文件结构**：

```
/var/www/notes/
├── <name>.html            # agent 上传的 HTML 文件（nginx 直 serve）
├── <name>.html.meta       # 边车 JSON：批注（仅 daemon 读写；nginx 不读）
└── ...
```

无 `index.html` 默认文件——用户自己写或不放。`.meta` 与 `.html` 严格共存：删除 `.html` 时**不**自动删 `.meta`（批注是独立资源），由调用方显式管理。

**批注 schema（`<name>.meta` 文件内容）**：

```json
{
  "version": 1,
  "annotations": [
    {
      "id": "01JC8X1A2B3C4D5E6F7G8H9J0K",
      "quote": "sudo mkdir -p",
      "comment": "改成用户级目录",
      "author": "tk_a1b2c3d4",
      "ts": 1754025600
    }
  ]
}
```

- `id`：ULID（lexicographically sortable, 26 chars）；生成不依赖外部库（`os.urandom` + base32 即可）
- `quote`：用户选中的原文片段；用于 iframe 高亮定位（substring match + normalize whitespace）
- `comment`：评论文本
- `author`：`tk_<sha256(token)[:8]>`，不可逆；同 token 多次提交 author 一致；服务端比对以鉴"自己的批注"
- `ts`：unix seconds，写入时刻
- **原子写**：`.meta` 写盘沿用 `.tmp + os.replace`，与 `.html` 写规则一致（§4 + §7.1）
- **空列表**：`{"version": 1, "annotations": []}`——文件存在即"有记录",空列表与"无批注"语义不区分

**无元数据库**（N6）：mtime / size 从 `os.stat()` 取；title 从 HTML 解析
（`re.search(r'<title>(.*?)</title>', content, re.DOTALL | re.IGNORECASE)`）。
若 V2 需要上传者 / 描述 / 标签字段，再引入 SQLite——V1 不做。

### 7.3 接口设计

**MCP tools**（`POST /mcp`，JSON-RPC 2.0 over Streamable HTTP）：

| Tool | 入参 | 出参 | 错误码 |
| --- | --- | --- | --- |
| `upload_html` | `{name: str, content: str, force?: bool}` | `{url: str, name: str, size: int}` | invalid_name / conflict / too_large / docroot_unwritable |
| `list_html` | `{}` | `{files: [{name, size, mtime, url, title?, annotation_count: int}]}` | — |
| `delete_html` | `{name: str}` | `{deleted: bool}` | not_found |
| `get_public_url` | `{name: str}` | `{url: str}` | — |
| `list_annotations` | `{name: str}` | `{name: str, annotations: [{id, quote, comment, author, ts}]}` | not_found |
| `delete_annotation` | `{name: str, id: str}` | `{deleted: bool}` | not_found |

**HTTP API**（管理页背后）：

| 方法 | 路径 | 鉴权 | 出参 |
| --- | --- | --- | --- |
| GET | `/api/files` | 无（公开元数据：docroot 文件 nginx 本来就公开 serve） | `{files: [...]}`（同 list_html，含 `annotation_count`） |
| DELETE | `/api/files/<name>` | Bearer | `{deleted: bool}` |
| GET | `/api/nginx-config` | Bearer | text/plain（反代片段，§15.3.3） |
| GET | `/api/health` | 无 | `{status, version}` |
| GET | `/` | 无（管理页本身是只读 shell） | HTML |
| POST | `/mcp` | Bearer | JSON-RPC |
| GET | `/files/*` | （由 nginx 直 serve） | text/html |
| POST | `/api/auth` | 无（提交 Bearer token） | 204 + `Set-Cookie: anno_session=...; HttpOnly; Secure; SameSite=Lax; Max-Age=1800`（成功）/ 401（失败） |
| GET | `/api/files/<name>/annotations` | 无（公开：批注与 .html 同生命周期） | `{name, annotations: [...]}` |
| POST | `/api/files/<name>/annotations` | session cookie + CSRF | `{id, quote, comment, author, ts}` |
| PATCH | `/api/files/<name>/annotations/<id>` | session cookie + CSRF + author 匹配 | `{id, ...}` |
| DELETE | `/api/files/<name>/annotations/<id>` | session cookie + CSRF + author 匹配 | `{deleted: bool}` |

> 注：经典模式下 `/files/*` **不走 daemon**——nginx 直接从 docroot 读取，daemon 不挂这条路由。**容器模式（§15.3.1）下相反**：daemon 自己服务 `GET /files/<name>`（流式 + 路径穿越防护），nginx 退化为纯反代；两种模式下 `/files/*` 的公开访问语义一致（无 auth，公开 docroot）。

**错误码**：

| HTTP | MCP | 含义 |
| --- | --- | --- |
| 400 | -32602 | 参数非法（含 invalid_name） |
| 401 | -32001 | 鉴权失败 |
| 404 | -32020 | 文件不存在 |
| 405 | — | method 不在白名单 |
| 409 | -32010 | 同名冲突（未带 force） |
| 413 | -32011 | 超过 max_file_size |
| 500 | -32012 | docroot 不可写 |
| 500 | -32603 | 内部错误 |

**幂等性**：upload_html（force=true）幂等；list_html / get_public_url 只读天然幂等；delete_html 对不存在返 404，不算幂等。HTTP DELETE 沿用 REST 惯例：成功 200，文件不存在 404。

**CLI 子命令**：

```
agent-html-drop init [--force]
agent-html-drop serve [--config PATH]
agent-html-drop token show
agent-html-drop token rotate
agent-html-drop config show
agent-html-drop config path
agent-html-drop config edit
agent-html-drop nginx-config [--write [PATH]]
agent-html-drop status
```

`init` 行为：幂等——已存在 config 不覆盖（除非 `--force`）；docroot 不存在时 hint
`sudo mkdir -p <docroot> && sudo chown $USER <docroot>`（**不**自动 sudo）。

`nginx-config` 行为：从 `assets/nginx.conf.template`（包内静态资源）渲染。占位符：

- `{{DOCROOT}}` → `docroot`
- `{{PORT}}` → `port`
- `{{PUBLIC_BASE_URL}}` → `public_base_url`

### 7.4 兼容与影响面

| 维度 | 影响 | 依据 |
| --- | --- | --- |
| 现有 `model_switch` | 无 | 新 `src/agent_html_drop/` 目录独立；`install.sh` 扩展而非重写 |
| `yzr-md-to-html` | 无；可选未来联动（V2+） | md-to-html 产本地 HTML，daemon 与之无运行时耦合 |
| 远端 server nginx | 新增 1 个 server block | 用户手动拷配置 + reload；daemon 不碰 nginx |
| 现有 nginx sites | 无 | daemon 仅 listen 127.0.0.1；反代写到独立 sites-available/notes.conf，不动 default |
| 用户 shell rc | 扩展 PATH marker | `install.sh` 复用同一个 marker block（PATH = bin dir） |
| 用户 `~/.config/` | 新建 `~/.config/agent-html-drop/` | 不碰 model_switch 的 `~/.config/model-switch/` |
| 现有 port 8765 | 可能冲突 | daemon 启动失败退出码 3，用户改 `config.port` |
| 现有 systemd unit | 无 | 不引入 |
| `tomli` / Python 包 | 同 model_switch | 复用既有依赖；不新增 |
| shell 补全 | 复用 model_switch 的 bash / fish 安装流程 | install.sh 的 link_completion 循环扩展 |

## 8. 异常与边界处置

| 异常 | 处置 | 落点 |
| --- | --- | --- |
| 端口被占 | `OSError(EADDRINUSE)` → 退出码 3 + stderr「Port 8765 is in use; set port in config.toml」 | §7.1 |
| docroot 不可写（启动时） | warning 但不阻止（read-only 模式） | §7.1, §9.2 |
| docroot 不可写（运行时） | upload 返 500 + `-32012` | §7.3 |
| 磁盘满 | `OSError(ENOSPC)` → 500 + `-32012`；临时文件 `.tmp` 写入失败时清理（finally 块 unlink） | §7.3 |
| 并发上传同名 | 单用户场景概率极低；后写者覆盖（last-writer-wins）；不带 force 自然 race-friendly | §4 |
| config 损坏 | `tomli.TOMLDecodeError` → 退出码 2 + stderr 含文件路径 + 行号 | §7.1 |
| token 泄露 | rotate 重新生成，旧 token 立即失效（daemon 重启后）；运行期 `auth.redact_token()` 永远首 4 / 末 4 + `****` | §7.3, §9.3 |
| nginx 配置错误 | daemon 不感知；nginx 报错回滚 reload；daemon 继续工作但外部 502 | §12 |
| daemon 进程崩溃 | 端口释放，外部 502；需外部 monitor 报警 `/api/health`；无自动重启 | §9.2 |
| size limit 突破 | HTTP 层累计 body 字节数（`request.rfile.read(n)` 累计），超 `max_file_size` 立即 `self.close()` + 413；不读完整 body | §7.3 |
| path traversal | 所有 docroot 文件路径过 `Path.resolve()` + 断言 `startswith(docroot.resolve())` | §7.3, §9.3 |
| iframe 逃逸 | iframe `sandbox=""` 禁用 JS / 表单 / 同源 / 顶级导航 / 弹窗 / 定向 | §9.3 |
| token 文件权限被改宽（S32） | daemon 启动时 warning（不阻止） | §7.3 |
| Bearer timing attack | `hmac.compare_digest` 常量时间比较 | §9.3 |
| quote 失配 | 批注在 iframe 中找不到 quote（HTML 重传 / 改写）→ UI 显示 ⚠️ 但保留 comment 文本；不删除批注 | §9.3 |
| 批注 cookie 过期 | session cookie 30 min TTL 到期 → 写接口返 401 → 前端弹框引导重新出示 token | §7.3, §9.3 |
| Origin 头不匹配 | CSRF 攻击或浏览器异常 → 批注写接口返 403；`GET` 跨站仍允许（cookie 已 SameSite 拦截） | §9.3 |
| 暴力点击 `/api/auth` | nginx `limit_req zone=auth limit=10r/s` 限流；超阈值返 503 + `Retry-After` | §9.3, §12 |
| token 错配（agent 端） | agent 用旧 / 错 token 调 MCP → 401；用户跑 `agent-html-drop token show` + 改 agent MCP config | §7.3, §9.2 |

最可能出线上事故的 3–5 条：**端口被占 / token 泄露 / docroot 不可写 / size 突破 / path traversal**——上面已逐条钉死技术处置。

## 9. DFX 设计

### 9.1 性能与容量

**量级估算**（G1）：

| 项 | 值 |
| --- | --- |
| 并发请求数 | < 10（agent 一个长连接 + 浏览器几个请求 + 管理页 fetch） |
| docroot 文件数 | < 10000（单用户 5 年上传量级） |
| 上传 P99（局域网，50 MB） | < 1 s（受磁盘 I/O 限制，daemon 不引入额外开销） |
| list_html P99（10000 文件） | < 500 ms（opendir + N stat） |
| iframe preview P99 | nginx 直 serve，daemon 不参与；与 nginx 直 serve docroot 文件同等 |

**关键路径开销**：

- upload: 1 atomic write + 1 chmod + 1 stat = O(file size)
- list: 1 opendir + N stat = O(N files)
- delete: 1 unlink = O(1)

**优化不做**：不做缓存（list 不缓存）；不做压缩（HTML 已自包含）；不做 CDN（局域网部署，没必要）。

### 9.2 可靠性

**依赖降级**：

- docroot 不可写 → upload 返 500，其他功能继续（F18）
- nginx 挂了 → daemon 暴露在 `:8765` 但外部不可达，用户排查 nginx
- token 错配（agent 用旧 token, daemon 已 rotate）→ agent 所有 MCP 调用 401，agent 报错，用户跑 `token show` + 改 agent 配置

**进程保活**：daemon 无内置重启机制。README hint「建议 systemd 用户单元 / tmux / nohup」。外部挂掉靠 monitor + manual restart。

**优雅退出**：SIGINT/SIGTERM → `server.shutdown()` → 等 in-flight 请求最多 5s → exit 0。
`install_signal_shutdown()` 同时装一个 SIGALRM watchdog：`serve_forever()` 5s 内
未返回则 `os._exit(0)`。这是 Python 3.12+ `ThreadingHTTPServer.shutdown()`
在某些平台不立即 wake `serve_forever` 的兜底，与"≤ 5s graceful"语义一致。
正常 in-flight 请求 < 5s 完成走 graceful 路径，watchdog 不触发。

**数据持久性**：docroot 是唯一数据，靠文件系统保证。无数据库无事务。

**降级模式**：docroot 不可写时 daemon 仍能 list / preview / delete（如果允许删除），但 upload 全 500——这是用户感知到的"读 OK 写挂"信号。

### 9.3 安全与合规

**鉴权**（G3 / F18 / §7.3）：

- Bearer token 常量时间比较（`hmac.compare_digest`）
- token 存 `~/.config/agent-html-drop/config.toml`，文件 `chmod 0600`；启动时若权限更宽松则 warning
- token 在日志中脱敏（`auth.redact_token()` 首 4 / 末 4 + `****`）
- 所有非 `/files/*` 入口强制 Bearer；`/files/*` 公开访问——经典模式由 nginx 直 serve、容器模式（§15.3.1）由 daemon 服务，**两种模式都不对 `/files/*` 加 auth**（视为公开 docroot，符合"推送即公开"的 yzr-md-to-html 设计本意）

**越权防护**：

- 路径穿越：`Path.resolve()` + 断言
- 文件名 regex：仅 `[A-Za-z0-9._-]+\.html`

**注入防护**：HTTP body 是 HTML 文本，daemon **不解析不执行**，存为 UTF-8 字节。nginx serve 时按 `text/html` 输出，浏览器渲染——这是用户想要的行为，不是攻击面。

**iframe 隔离**：管理页预览 iframe `sandbox="allow-same-origin"`（F6）——禁用 JS / 表单 / 弹窗 / 顶级导航；**允许同源**以便主页面注入 `<mark data-anno-id>` 高亮；批注按钮的 `<dialog>` 与 iframe 的 DOM 严格隔离（iframe 内 CSS 不污染批注 UI，反之亦然）。

**批注写接口安全（§7.3 / F19–F25）**：

- **入口形态**：管理页 header 右上角"批注(需 token)"按钮，按钮文案明示"需 token"——访客点开后**必须出示有效 Bearer token** 才能进批注模式；不存在任何"匿名写批注"路径
- **Cookie 策略**：`POST /api/auth` 校验 token 通过后签发 `anno_session=...` cookie，`HttpOnly; Secure; SameSite=Lax; Max-Age=1800`（30 分钟）。无 refresh token；关浏览器即失效
- **CSRF 双层防御**：
  1. **浏览器层**：`SameSite=Lax` cookie——`POST / PATCH / DELETE` 跨站不携带 cookie（2020+ 浏览器默认行为）
  2. **服务端兜底**：所有批注写接口校验 `Origin` 头（存在时必须等于 `https://<Host>`，否则 403）；`GET` 跨站仍允许（公开读）
- **暴力穷举防护**：
  - token 是 `secrets.token_hex(32)` = 256 bit，**算力上不可能穷举**
  - nginx `limit_req zone=auth limit=10r/s`（`/api/auth` 与批注写接口共享 zone）防单 IP 高频请求；超阈值返 503 + `Retry-After`
  - token 比较用 `hmac.compare_digest` 常量时间
- **author 身份模型**：`author = "tk_" + sha256(token)[:8]`，**不可逆**——同 token 多次提交 author 一致；PATCH/DELETE 时服务端：cookie 还原 token → 算 hash → 比对 entry.author。**不引入 alice/bob 角色概念**（N10）；两个 reviewer 用同一 token 共享 author 视图
- **agent vs 浏览器边界**：agent 走 MCP `/mcp` Bearer 写 `.html`；浏览器走 REST session cookie 写 `.meta`。**两条路径互不重叠**——agent 无写批注接口（N11），浏览器无写 HTML 接口
- **批注 vs HTML 资源独立性**：删除 `.html` 不删 `.meta`（批注是独立资源，跨文件版本可继续参考）；上传覆盖 `.html` 时 `.meta` 不动（quote 可能失效但保留，UI 标 ⚠️）

**审计**：日志含 method + path + status + tool name + 文件名 + 大小，**无** token 明文、**无** session cookie 明文、**无** HTML 内容、**无** 批注 comment 文本。

**合规**：无个人敏感信息处理（仅文件元数据 + 批注文本——owner 自托管自负）；不涉及 GDPR / 等保场景。

### 9.4 可服务性

**关键监控指标**（用户自接）：

| 指标 | 来源 | 阈值 |
| --- | --- | --- |
| daemon 进程存活 | 外部进程监控 | 消失即告警 |
| `/api/health` 200 | 外部 HTTP probe | 连续 3 次非 200 告警 |
| `:8765` 端口监听 | 外部 TCP probe | 消失即告警 |
| nginx error log 502 | nginx 日志 | 频次告警 |
| upload / delete 事件计数 | daemon stderr 日志 | 异常突增告警 |

**日志规范**：

```
2026-08-01 12:34:56 INFO  POST /mcp 200 tools/call upload_html name=design.html size=18.3KB
2026-08-01 12:35:01 WARN  GET  /api/files 401 invalid bearer token
2026-08-01 12:35:10 ERROR DELETE /api/files/missing.html 404 file not found
2026-08-01 12:40:00 INFO  daemon started pid=12345 listen=127.0.0.1:8765
2026-08-01 12:40:01 WARN  config.toml permission 0644 > 0600; consider chmod 600
```

**常见运维操作**：

- 重启 daemon：找 pid, `kill <pid>`（SIGTERM 5s 后强杀 SIGKILL），再 `agent-html-drop serve &`
- 改配置：`agent-html-drop config edit` → 重启 daemon
- 改 token：`agent-html-drop token rotate` → 重启 daemon → 通知 agent 更新 token
- 备份：`tar` 整个 docroot + config.toml（不含 token 也行）
- 扩容：docroot 换大盘；atomic rename 跨 fs 受限（V1 假设 docroot 在同一 fs）

### 9.5 可测试性

**依赖可打桩**：

- `paths.py` 的所有 XDG 解析被 monkeypatch 到 tmp
- `config.docroot` 默认指向 tmp 子目录
- daemon 启动端口用 `0`（内核 ephemeral），测试用 `sock.getsockname()` 拿真实端口

**内部状态可观测**：

- `storage.upload / delete / list` 返回显式结构，测试直接断言
- `auth.bearer_check` 返 bool，测试覆盖各种坏 token
- 不引入 `freezegun` / `responses` 等第三方 mock 库——全部 stdlib + 手写 mock

**时间与外部依赖可控制**：

- mtime 测试时直接 `os.utime(path, (atime, mtime))` 设
- 无外部网络调用（nginx 在测试里完全不参与——daemon 单测只走 daemon 自身路由）

**测试数据可构造**：

- 自包含 HTML 用最小 fixture：`<html><head><title>test</title></head><body>x</body></html>`
- 大文件用 `b"x" * (51 * 1024 * 1024)` 在测试里构造

**测试覆盖目标**：≥ 90%（G5）。

## 10. 备选方案与设计权衡

**当前选中（§6）**：远端 daemon + nginx HTTPS 反代 + Streamable HTTP MCP + 管理页 inline JS。

**否决方案 B**：单次 CLI 调用 + 远程 HTTPS API（不要 MCP）。
- 否决理由：用户明确要 MCP 协议（"MCP 服务"），CLI + HTTPS API 不满足

**否决方案 C**：agent 端 stdio MCP + SSH 推到 server。
- 否决理由：1) HTML 管理页位置尴尬（要么放 docroot 当静态文件，要么不放）；2) 每个上传走 SSH/rsync，密钥处理复杂（重复 `yzr-md-to-html --deploy` 的 SSH 老路）；3) server 端零状态意味着管理页需要另一份部署逻辑

**否决方案 E**：方案 A + agent 侧 tunnel 助手（ssh -L 自动）。
- 否决理由：V1 多一层抽象，当前 agent 自己 ssh 也不麻烦；后续真有需要再加（V2+）

**否决方案 F**：aiohttp / fastapi 框架 + 官方 MCP Python SDK。
- 否决理由：1) 违反 yzr-agent-tools stdlib-only 规约；2) 增加 Python 版本与依赖门槛；3) 当前 4 个 tool 自实现 ~150 行就够，SDK 是 overkill

**否决方案 G**：SQLite 元数据库（存 title / 描述 / 上传者）。
- 否决理由：title 从 HTML 解析；其余信息从 stat 取；用户没要求上传者字段；YAGNI

**否决方案 H**：systemd 用户单元 + 自动 reload nginx。
- 否决理由：1) daemon 不是 install.sh 必装组件，systemd 集成跨发行版差异大；2) reload nginx 是用户责任；3) V1 用户接受手动保活（README hint）

**否决方案 I**：nginx config auto-generate + write 到 /etc/nginx/sites-available + reload。
- 否决理由：需要 root / sudo；不同发行版 / macOS 路径不同；用户拷出来自己 reload 反而简单可控

**否决方案 J**：agent 写批注（浏览器只读 / agent 写）——把"review"放进 agent 工作流。
- 否决理由：1) 浏览器选区→quote 的语义在 agent 端是文本字符串，丢失选区上下文（offset / 富文本）；2) 人审稿后让 agent "替我提意见"是反模式（agent review 自己）；3) 破坏"批注由人触发"的协作直觉。**V1 浏览器写批注 + agent 读/删**

**否决方案 K**：批注多 reviewer 协作（author 字段 = 真实用户名 / 多 token / 权限分级）。
- 否决理由：1) 与单用户信任模型冲突（A3）；2) 引入 alice/bob 注册流 / token 分发 / 鉴权服务是另一条产品线；3) 同 token 多 reviewer 实际场景足够（团队共享 token 是常见自托管实践）。**V1 用 `tk_<hash8>` 同名共享；多 token 模型 V2+ 视需要**

---

—— 落地层 ——————————————————————————

## 11. 实施任务书（独立文件）

任务书文件：[`tasks.md`](./tasks.md)

任务拆分从 §3 功能点 / §7 详细设计导出。任务书是**执行期活文档**：进度 / 问题 / 设计变更在其中流转；本文档评审后保持稳定。

当前完成度：T1–T12 共 12 项，**全部未开始**（草稿评审通过后启动）。

## 12. 上线与回滚

**上线**（按动作序列，对应 S1 / S2 / S3）：

1. 在远端 server 跑 `bash scripts/install.sh`（扩展现有脚本，挂 agent-html-drop wrapper + 补全）
2. 跑 `agent-html-drop init`（创建 config + 生成 token，stdout 打印）
3. sudo 创建 docroot：`sudo mkdir -p /var/www/notes && sudo chown $USER /var/www/notes`
4. 跑 `agent-html-drop nginx-config --write`，打开 `~/.config/agent-html-drop/nginx.conf.example`，按需调整 server_name / ssl_certificate，拷到 `/etc/nginx/sites-available/notes.conf`
5. 启用 + reload nginx：`sudo ln -s /etc/nginx/sites-available/notes.conf /etc/nginx/sites-enabled/ && sudo nginx -t && sudo systemctl reload nginx`
6. 跑 `agent-html-drop serve &`（生产建议 tmux / systemd 用户单元）
7. 在 agent 配置 Claude Code MCP server：`url = https://notes.example.com/mcp`, `bearer_token = <agent-html-drop token show>`
8. 端到端验证：浏览器打开 `https://notes.example.com/`，输入 token，看到空列表；让 agent 上传一个测试 HTML，确认管理页出现 + `https://notes.example.com/<name>.html` 可公网访问

**回滚**（出线上问题怎么退；与"用户撤销操作"分开）：

| 故障 | 工程回退 |
| --- | --- |
| daemon 行为异常 | 找 pid，`kill <pid>`（SIGTERM 5s 后 SIGKILL） |
| 撤销 nginx 反代 | `sudo rm /etc/nginx/sites-enabled/notes.conf && sudo systemctl reload nginx`（docroot 仍可访问但走 default server） |
| 完全下线 | `bash scripts/uninstall.sh`（wrapper / PATH marker / 补全 symlink 全清）；手动 `rm -rf ~/.config/agent-html-drop/`（数据 + config）；手动 `rm -rf /var/www/notes/`（docroot） |
| 单文件误传 | 管理页点 ×，或 agent 调 `delete_html` |
| token 泄露 | `agent-html-drop token rotate` → 重启 daemon → 通知 agent 更新 token |
| nginx 配置写错 reload 失败 | daemon 不感知；修 server block 再 reload；docroot 仍可由 nginx 直 serve |

### 12.1 容器化部署（替代路径，2026-08-02 新增）

经典 §12 之上，容器模式上线序列（详见 §15）：

1. `docker compose up -d`（首次自动种 config + token，挂两 bind mount）
2. `docker compose exec agent-html-drop token show` 取 token，配给 agent MCP（`url = https://<host>/mcp`）
3. 把 §15.3.3 的反代片段贴进现有 nginx（`location / { proxy_pass http://127.0.0.1:8765; }` + `/mcp` 流式头），reload
4. 端到端验证：浏览器开管理页 → agent 上传 → 访问 `https://<host>/files/<name>.html`

容器模式回退：`docker compose down`（`./data/` 保留，数据不丢）；彻底清 = 额外 `rm -rf ./data/`。镜像/daemon 异常靠 compose `restart: unless-stopped` 或外部 monitor 探 `/api/health`。

## 13. 开放问题

- **Q1**：~~管理页 token 输入框行为~~ ——**已闭环**：管理页不再接触 token。`GET /api/files` 公开（docroot 文件 nginx 本来就公开 serve），管理页无 token 输入框 / 不读 localStorage；删除 / 上传一律走 agent MCP（`POST /mcp` 仍要 Bearer）。`Config.token` 字段、`token show/rotate` CLI 保留（仅给 agent / 运维使用）。**变更日期**：2026-08-01。
- **Q2**：MCP Streamable HTTP session 管理。**默认倾向**：无状态（每请求独立），符合单用户信任模型。**待谁确认**：用户 / 评审。
- **Q3**：upload_html 是否返 mtime？**默认倾向**：不返，list_html 时取；若 agent 需要 V2 加。**待谁确认**：agent 端用法反馈。
- **Q4**：管理页是否加"上传"按钮给人手动上传 HTML？**默认倾向**：不做——浏览器只写批注（不写 HTML）；上传 HTML 走 agent MCP（设计本意）。**待谁确认**：用户。
- **Q5**：token rotate 是否保留旧 token 一段 grace period？**默认倾向**：不保留，rotate 立即失效（最简单）。**待谁确认**：用户 / 评审。
- **Q6**：是否支持上传 `*.htm` / `*.xhtml`？**默认倾向**：不支持（regex 限定 `.html`）。**待谁确认**：用户。
- **Q7**：是否要给 docroot 文件加 ACL（如 public / private 标志）？**默认倾向**：不加——docroot 整体视为公开（"推送即公开" 符合 yzr-md-to-html 设计本意）。**待谁确认**：用户。
- **Q8**：批注入口按钮的文案 / 位置 / 显隐？**默认倾向**：header 右上角"批注(需 token)"，常驻显式（单用户自托管场景下"显式入口 = affordance"而非"误触面"）。**待谁确认**：用户。
- **Q9**：批注 session cookie TTL 取值？**默认倾向**：30 分钟（`Max-Age=1800`），无 refresh——访客长时间离开再回来需重新出示 token，强制频次低。**待谁确认**：用户 / 评审。
- **Q10**：nginx `limit_req` 阈值？**默认倾向**：`limit=10r/s`，单 IP 突发 10 次/秒足以挡住脚本狂点又不影响真人手点；burst 20。**待谁确认**：用户 / 评审。
- **Q11**：iframe sandbox 用 `allow-same-origin` 还是更严？**默认倾向**：`sandbox="allow-same-origin"`——必须允许同源以便主页面注入 `<mark>` 高亮；同时**显式禁止** `allow-scripts`（防 yzr-md-to-html 产物里的 Mermaid/MathJax 在批注 iframe 里执行）。**待谁确认**：用户 / 安全评审。

- **Q12**：~~容器化是否做~~ ——**已闭环（2026-08-02）**：做。方案 A——独立镜像 + 极简 compose（daemon + 两 bind mount 卷）+ 用户自有 nginx 纯反代；不做容器内 nginx / 容器内 TLS。详见 §15。否决了方案 B（compose 捆绑 nginx，与「用我自己的 nginx」相悖）与方案 C（只给 Dockerfile，丢迁移便利）。
- **Q13**：~~容器化后 `/files/*` 由谁服务~~ ——**已闭环（2026-08-02）**：daemon 自己服务（§15.3.1），容器完全自包含；否决了「nginx 共享 docroot 卷」（把宿主文件系统耦合搬回来，与「任何反代都能 front」相悖）。
- **Q14**：~~公开 URL 是否修 `/files/` 脚枪~~ ——**已闭环（2026-08-02）**：修。统一为 `<origin>/files/<name>`，带迁移注记（§15.3.2）。
- **Q15**：~~nginx 模板是否退役~~ ——**已闭环（2026-08-02）**：不退役，重写为极简反代片段、保留 `nginx-config` CLI（§15.3.3）。

## 14. 排期

内部小项目，无评审排期压力，跳过本节。任务书 [`tasks.md`](./tasks.md) 内 T1–T25 给出粒度。

## 15. 容器化部署（Docker）

> 新增于 2026-08-02。容器化是**叠加的部署模式**，不替换经典模式（§6 / §12 的 daemon + 同机 nginx + nginx 直读 docroot 仍完全可用）。本节只描述容器模式的差异与交付物；除特别注明，§1–14 的设计对两种模式都成立。

### 15.1 目标与范围

把 daemon 打成**自包含 Docker 镜像**，让用户用自己的 nginx 反代 HTTP 到容器端口即可上线；daemon 不依赖容器内 TLS（TLS 在边缘 nginx 终结）。交付物：`Dockerfile` + `docker/entrypoint.sh` + `docker-compose.yml` + 极简反代片段。

非目标（YAGNI）：容器内塞 nginx、容器内 TLS、named volume、多架构构建、每字段 env 覆盖。经典安装路径（`scripts/install.sh`）零影响——容器化是叠加，不替换。

### 15.2 拓扑

```
浏览器 ──HTTPS──▶ 用户 nginx(终结 TLS) ──HTTP──▶ 容器:8765 (daemon, bind 0.0.0.0)
                                                       │
                          ┌────────────────────────────┴──────────┐
                          │ /mcp  /api/*  /  /files/*  全由 daemon │
                          │ docroot + config 挂在 /data (bind mount)│
                          └─────────────────────────────────────────┘
```

关键转变：**容器外再无任何进程碰 docroot**——nginx 纯反代，docroot 卷只为持久化 + 备份。`Secure` cookie 与 https-only CSRF 在「边缘 HTTPS + 内部 HTTP」下照常工作（浏览器只跟 nginx 讲 HTTPS；nginx→容器那段 HTTP 对浏览器 cookie 语义不可见，CSRF 的 `Origin` 头也由浏览器按边缘 HTTPS 生成，到 daemon 天然对得上）。

### 15.3 代码改动（delta）

**15.3.1 daemon 新增 `GET /files/<name>` 路由。** 复用 `_legacy_storage.validate_name` 做路径穿越防护；命中且文件存在 → 流式输出（分块写 `wfile`，不整文件进内存），`Content-Type: text/html; charset=utf-8`；缺失 / 非法名 / 穿越 → **统一 404**（不区分，避免探测）。原子写保证不读到半写文件。需给 server 加一个「流式响应」小扩展（发完 header 后直接写 body，跳过默认的 bytes 回传路径）。无鉴权——延续「推送即公开」信任模型（§9.3），与经典模式 nginx 直读 `/files/*` 同。

**15.3.2 公开 URL 统一为 `<public_base_url>/files/<name>`（行为变更，2026-08-02）。** 既有矛盾：MCP/API 返回 `public_base_url + "/" + name`（**无 `/files/`**），但前端预览 iframe（`ui/app.js`）与 nginx 都是 `/files/<name>`——要让分享 URL 可达，`public_base_url` 得偷偷带 `/files/`（默认值却没有），是隐藏脚枪。统一改 4 处 URL 构造（`api._file_info_payload` 1 处 + `mcp_handler` 的 upload / list / get_public_url 3 处）为 `public_base_url.rstrip("/") + "/files/" + name`，`public_base_url` 语义清成「纯 origin」。经典模式（nginx 直读 `/files`）与容器模式（daemon 服务 `/files`）由此端到端一致。

> **迁移**：现有用户若把 `public_base_url` 设成了 `https://x/files`，需改成纯 origin（去掉 `/files`），否则会变双 `/files/files/`。

**15.3.3 重写 `assets/nginx.conf.template` 为极简反代片段。** 砍 SSL cert 段与 `location /files/ { alias }`（daemon 自服务了）；保留 `/` 反代、`/mcp` 的 `proxy_buffering off` + 长超时、cookie 透传、`/api/auth` 限流（可选）。`nginx-config` CLI 保留，渲染新模板（端口 + public_base_url 仍替换）。**单一真源 = 模板**：docs 指向它，避免双份漂移。

**15.3.4 监听地址。** 源码默认 `host = "127.0.0.1"` 不改（经典模式沿用）；容器内由 entrypoint 种入的 config 设 `host = "0.0.0.0"`。compose `ports: 127.0.0.1:8765:8765`——容器内 bind `0.0.0.0`，Docker 只发布到宿主 loopback，公网不可达，只用户 nginx 能访问。

### 15.4 容器化交付物

- **`Dockerfile`**：`python:3.12-slim` 基底（源码仍 3.7 兼容，但镜像跑 3.12；3.12 自带 `tomllib`，**零运行时依赖**，无需 `tomli`）；拷 `src/`；非 root 用户；`CMD` 走 entrypoint。
- **`docker/entrypoint.sh`**：首次运行若 config 缺失 → 用模板 + `secrets.token_hex(32)` 种一份容器友好 config（`host=0.0.0.0` / `port=8765` / `docroot=/data/docroot` / `public_base_url=$PUBLIC_BASE_URL`），建 docroot 目录若缺，再 `exec agent-html-drop serve`；config 已存在则直接 serve（持久 config 优先，env 不覆盖）。
- **`docker-compose.yml`**：单 `agent-html-drop` 服务 + 两 bind mount + `ports: 127.0.0.1:8765:8765` + `environment: PUBLIC_BASE_URL` + `healthcheck`（探 `/api/health`）。
- **反代片段**：15.3.3 模板的渲染产物，贴进用户现有 nginx。

### 15.5 数据与卷

| 用途 | 容器内 | 宿主（示例） | 权限 | 备份 |
| --- | --- | --- | --- | --- |
| docroot（HTML + 批注 sidecar） | `/data/docroot` | `./data/docroot` | daemon 读写 | `tar`/`rsync`，频繁 |
| config + token（凭据） | `/data/config`（`XDG_CONFIG_HOME=/data/config` → `…/agent-html-drop/config.toml`） | `./data/config` | `0600` | 按 secret 单独备份 |

两者同属一个父目录 `./data/`，compose 里一个 `volumes:` 块搞定；迁移 = `scp` 整个 `./data/` + compose 文件。首次 `docker compose up` 自动生成 token（持久化在 config 卷），后续 `docker compose exec agent-html-drop token show` 取 token 配给 agent。

> **uid 对齐（部署易踩坑）**：容器以非 root 用户跑，bind mount 的宿主 `./data/` 所有者 uid 需与容器内用户一致（或对该目录放读写权限），否则写 docroot / config 会权限拒绝。compose 用 `user:` 透传或 entrypoint 启动时 `chown` 处理；部署文档须注明——这是 bind mount 的固有限制，named volume 无此问题但失去「宿主直连备份」便利，故仍选 bind mount。

### 15.6 安全模型（沿用 §9.3）

应用层鉴权一条不改：Bearer（MCP + DELETE）、签名批注 cookie、路径穿越 regex、body 上限、cookie 属性（`Secure/HttpOnly/SameSite=Lax`）、CSRF `Origin` 校验——全仍必需，nginx 在不在前面都得有。**唯一变多余的是旧 nginx 模板**（15.3.3 重写处理）。`/files/*` 新增的 daemon 路由同样无 auth，延续「推送即公开」。

### 15.7 测试

- **单元**：`/files/<name>` 路由（存在 → 200 `text/html`、缺失 → 404、穿越 → 404、原子写进行中不泄露半文件）；URL 构造改动后（§15.3.2）相关断言更新。沿用 `tests/conftest.py` 的真实配置保护 fixture。
- **镜像冒烟**（可选，Docker 在场才跑）：build → run → `curl /api/health` 200 → 上传一个 HTML → `curl /files/x.html` 200。