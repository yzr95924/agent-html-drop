---
name: mcp-upload-large-html-passthrough
description: 设计决策 — 大 HTML 上传经 PUT /files/<name> 旁路，MCP upload_html 改为 verify-only 元数据 tool；HTTP/1.1 socket read EOF 不会在 body 结束时触发，必须按 Content-Length 限读
metadata:
  type: project
---

# 2026-08-04 重构：MCP 大 HTML 上传旁路

## 问题

agent 通过 MCP `upload_html(name, content)` 上传 HTML 时，整个 HTML 文本作为 tool 参数进入 LLM context——
500 KB HTML ≈ 12.5 万 token，context 税 + tool call 拼接慢 + token 费。

## 方案

字节走 HTTP PUT 旁路，MCP 只剩元数据校验。

- 新端点 `PUT /files/{name}`（Bearer + Content-Length + 可选 Content-SHA256）→ 流式写盘
- MCP `upload_html(name, sha256)` 改为 verify-only：检查文件已落盘 + sha256 一致 → 返回 public URL

agent 流程：

```bash
SHA=$(sha256sum /tmp/x.html | cut -d' ' -f1)
curl -X PUT -H "Authorization: Bearer $TOKEN" \
     --data-binary @/tmp/x.html \
     "http://127.0.0.1:8765/files/x.html?force=true"
# 然后 MCP 调：upload_html(name="x.html", sha256=$SHA) — 只进 ~80 字节到 LLM context
```

## 关键设计点

1. **PUT handler 用 `streams_body=True` 路由**：dispatcher 跳过预读 body，handler 自己从 `req.rfile` 流式读——避免 50 MiB 全量缓冲进内存。
2. **`storage.upload_stream(docroot, name, source, *, max_size, content_length, force, expected_sha256)`** 流式写 tmpfile → atomic replace；hashlib 在每个 chunk 增量更新；mid-stream 超 `max_size` 立即 `TooLarge`；任何错误路径删 tmp。
3. **PUT 用 case-insensitive 冲突检查，但 force=true 时删 case-variant 后写 URL-cased 名**（不像 MCP `upload()` 保留 first-upload casing）——HTTP URL 是 source of truth。
4. **MCP `upload_html` 流式 sha256**：再读一遍 docroot 上的文件算 sha256，跟 agent 本地声明的比对；不再 100% 把文件加载到内存。

## 核心坑：HTTP/1.1 socket 的 read 不会在 body 结束时返回 0

**为什么**：stdlib `socket.makefile('rb', 0)`（BaseHTTPRequestHandler `rbufsize=0`）返回 unbuffered `SocketIO`。
`SocketIO.readinto` → `recv_into` 只在**对端关闭**时返回 0 字节（EOF）；HTTP/1.1 keep-alive 下，
agent 客户端送完 body 后**不会**关连接（它在等响应），所以下一次 `read(N)` 会阻塞等更多字节，
直到 client 超时（5s+）才关——server 此时才"解阻塞"，但 client 早走了 → BrokenPipeError。

**修法**：`upload_stream` 接收 `content_length` 参数，按上限读（`min(chunk_size, content_length - bytes_written)`）；
handler 读完后 break，绝不依赖 EOF 判断结束。

**后果**：以后任何"读 request body 到 EOF"的写法都是错的。任何流式 body 路径都必须按
`Content-Length` 显式限长——除非明确在用 chunked transfer encoding（暂不支持）。

## 为什么 / How to apply

- 加新写路径时优先 PUT/POST+raw body，不用 MCP tool 参数带大块数据。
- 上传流式代码复用 `storage.upload_stream`（不要重写一个 `read-until-empty` 版本）。
- 任何 `req.rfile.read(N)` 都要 N ≤ 已声明的 Content-Length；不要在循环里裸 `read(任意大)` 然后 break on empty。
