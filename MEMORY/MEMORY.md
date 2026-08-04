# MEMORY/

跨会话"为什么 + 边界规则"的纯索引（L2 SSOT）；新条目追加到本文件末尾即可。
记忆跟 repo 走——只活这一份，不写 agent 私有 memory（如 `~/.claude/...`）。

- [MCP 大 HTML 上传旁路 (PUT + 元数据 tool)](mcp-upload-large-html-passthrough.md) — 字节流到 `PUT /files/<name>`，MCP `upload_html` 改为 verify-only；socket read 不会在 body 结束时 EOF，必须按 Content-Length 限读。
