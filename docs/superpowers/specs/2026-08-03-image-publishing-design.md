# 镜像发布流水线设计

日期：2026-08-03
作者：brainstorm with 用户
状态：等待用户审阅

## 背景

当前 `docker-compose.yaml` 写的是 `image: agent-html-drop:latest` + `build: .`，
只支持本地 build，不支持别人 `docker compose up` 时直接 pull 一个 release 镜像。
目标是把 daemon 打成公开镜像，发布到 GitHub Container Registry（GHCR），
让任何人 clone repo 后 `docker compose up -d` 就能用，不依赖本地源码。

## 决策摘要

| 维度 | 选择 | 理由 |
|---|---|---|
| Registry | **GHCR** (`ghcr.io/<owner>/agent-html-drop`) | 与 GitHub repo 绑定，`GITHUB_TOKEN` 内置 packages:write；公开包匿名 pull 无硬限；Docker CLI 原生支持 `ghcr.io` 前缀 |
| 受众 | **公开** | README 里直接给 `docker compose up` 即可用，无登录门槛 |
| 触发 | **`v*` git tag push** | 不可变标签，发布即定型，避免 commit 噪声触发构建浪费 CI 配额 |
| Tag 矩阵 | `vX.Y.Z`、`X.Y`、`X.Y.Z`、`latest`、`sha-<short>` | 不可变具体版本 + 浮动 major.minor + 完全浮动 + debug 标签；`latest` 仅当 tag 在 default branch 上时打（防止 RC 污染 latest） |
| 架构 | **linux/amd64 + linux/arm64** | 覆盖 x86 服务器 / Apple Silicon / AWS Graviton；Python stdlib 项目多架构零额外成本 |
| CI | **GitHub Actions + `GITHUB_TOKEN`** | 零额外 secret；与 repo 同托管；cache 加速 rebuild |
| 安全/签名 | **暂不加** | Python stdlib SBOM 薄、CVE 面窄；cosign 签名留作 v2 增强 |
| Dockerfile | **不改** | 官方 `python:3.12-slim` 多架构 + `gosu` 多架构 + shell entrypoint 架构无关 |
| Compose | 改 `image:`、删 `build:`，默认走 pull | 不破坏现有部署（已跑的用户改 image 字段即可升级） |

## 流水线设计

### 触发器

监听 `push tags` 事件，tag pattern 匹配 `v*`（含 `v0.1.0`、`v0.2.1-rc.1`）。
普通 commit push / PR 不触发。

### Workflow 文件

路径：`.github/workflows/release-image.yml`

```yaml
name: release-image
on:
  push:
    tags: ['v*']

permissions:
  contents: read
  packages: write    # 推 GHCR 包

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # docker/metadata-action 需要完整 git history
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v6
        with:
          driver-opts: image=moby/buildkit:v0.13.0
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/agent-html-drop
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=semver,pattern={{major}}.{{minor}}.{{patch}}
            type=raw,value=latest,enable={{is_default_branch}}
            type=sha,format=short
      - uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          provenance: false
      - name: post-publish smoke
        run: bash scripts/docker-smoke.sh --from-registry ${{ steps.meta.outputs.version }}
        env:
          SMOKE_IMAGE: ghcr.io/${{ github.repository_owner }}/agent-html-drop:${{ steps.meta.outputs.version }}
```

要点：

- `docker/metadata-action` 的 `flavor: latest=auto` 默认行为：仅当 tag 是 default branch 的最近 tag 时打 `latest` 标签
  - 上面示例用 `enable={{is_default_branch}}` 显式启用，确保只在 default branch 上标 latest
  - 对单 repo 单分支（master）模型来说，`latest` 总是跟着最近 `v*` tag 走
- `provenance: false`：关掉 SLSA provenance attestation 生成（公开 release 不要求；开启会让 cache 命中变慢）
- **post-publish smoke** 是新增的端到端验证：pull 刚推的镜像 + 起容器 + `/api/health` 200
  - 复用现有 `scripts/docker-smoke.sh`，加 `--from-registry` 选项（见 §测试策略）
  - **smoke 在 CI runner 上跑**（ubuntu-latest / amd64），所以**只验证 amd64 manifest**——arm64 manifest 由 build 阶段验证通过，本地 M-series / Graviton 手验
  - **smoke 失败处理**：workflow 标红 ✗；镜像已留在 GHCR，需要维护者发 patch tag 覆盖或手动 `ghcr.io/<owner>/agent-html-drop` 删 tag——不自动删（避免误删正在用的）

### Tag 矩阵示例

`v0.1.0` push 后的镜像列表：

| Tag | 类型 | 用途 |
|---|---|---|
| `v0.1.0` | 不可变 | 完整 git tag——`compose.yaml` 默认推荐这个 |
| `0.1` | 不可变 | 浮动 major.minor——给"我希望跟着 0.1.x 走最新"的人 |
| `0.1.0` | 不可变 | 完整 semver（与 `v0.1.0` 内容相同，命名风格不同） |
| `latest` | 可变 | 最近一次 default branch 的 `v*` tag |
| `sha-abc1234` | 不可变 | 精确 commit，调试用 |

> 实际 GitHub GHCR 里 `v0.1.0` 和 `0.1.0` 指向相同 digest——只是同一个 manifest list 的两个 alias。

### 首次启用 GHCR 包

1. Repo owner 去 `https://github.com/<owner>/agent-html-drop/settings/packages` 或第一次 push 触发自动创建
2. 默认 private —— 第一次 push 后手动改为 public（GitHub 不会自动公开新包）
3. 后续 push 默认走 public（设置继承 repo 可见性）

## docker-compose.yaml 改动

**diff**：

```diff
 services:
   agent-html-drop:
-    image: agent-html-drop:latest
+    # 默认从 GHCR 拉镜像(发布版本,见 README)。
+    # 想要本地重建:在下面加 `build: .` 覆盖 image 字段。
+    image: ghcr.io/<owner>/agent-html-drop:v0.1.0
-    build: .
+    # build: .
     restart: unless-stopped
```

要点：

- **保留 `image:` 字段**指向带版本 tag（不写 `:latest`），避免被悄悄换
- **删 `build:`** 让 compose 默认走 pull（Docker Compose 行为：`image` + `build` 同时存在时 `build` 优先——所以保留 `build:` 会让 pull 失效）
- 容器内行为 / 端口 / 卷定义完全不变——这是**对现有部署不破坏**的兼容性改动
- **`<owner>` 占位符**：第一次发版后维护者手动把 `<owner>` 替换为真实 GitHub username 并随 v0.1.0 tag 一同提交。后续 tag 不需要再改（除非 repo 换 owner）

## README 更新

### `## Docker 部署` 段（已有，新增一行）

在 "把 daemon 打成自包含镜像" 之前加：

> 镜像发布在 `ghcr.io/<owner>/agent-html-drop`。`docker compose up -d`
> 会自动拉取已发布镜像，不需要本地 build。首次使用把 image 字段里的
> tag 替换成你要的版本（默认 `:v0.1.0`）。

### `## 发布新版本（维护者）` 段（新增）

```bash
# 1. 准备 release commit
# 2. 打 tag（语义化版本）
git tag v0.1.0
git push --tags

# GitHub Actions 自动触发：
#   buildx build --platform linux/amd64,linux/arm64
#   → push 到 ghcr.io/<owner>/agent-html-drop
#     :v0.1.0, :0.1, :0.1.0, :latest, :sha-<short>
#   → post-publish smoke (pull + 起容器 + /api/health)

# 3. 把镜像从 GHCR 设为 public（首次 release 才需要）
```

### `## docker-compose.yaml`（已有）

把示例中的 `image: agent-html-drop:latest` → `image: ghcr.io/<owner>/agent-html-drop:v0.1.0`。

## docs/design.md 新章节 §16

简要记录：

- Registry: GHCR
- Tag 矩阵规则
- Workflow 文件路径
- 为什么不用 Docker Hub（free tier pull 限额严）
- 为什么不做签名（YAGNI for now）

## docs/tasks.md 新条目

- 加 "Image release pipeline (GHCR)" 任务条目，列出上面的设计点作为完成判定

## 测试策略

### 能在 CI 测的

1. **workflow YAML 语法** —— GitHub Actions 自带 schema 校验（push 到分支 → 不触发但有"Expected workflow"提示）
2. **多架构 build 本身** —— workflow 跑完 = 验证 build 通过
3. **post-publish smoke** —— pull 刚推的镜像 + 起容器 + `/api/health` 200 + 文件读写

### 不能在 CI 测的（留给本地手验）

1. **别人真的能 pull** —— 需要别人的账号登 GHCR 拉。但 GHCR 公开包匿名 pull 是平台能力，不需测
2. **多架构在 arm64 机器上跑起来** —— QEMU emulation 与真 arm64 有细微差别（极少见）；本地 M-series 笔记本可手验

### scripts/docker-smoke.sh 改造

加 `--from-registry TAG` 选项，跳过 `--build`，直接用指定镜像起容器：

```bash
bash scripts/docker-smoke.sh --from-registry v0.1.0
# 等价于：
#   IMAGE=ghcr.io/<owner>/agent-html-drop:v0.1.0 docker compose up -d
#   + /api/health check + /files check
```

默认行为不变（仍是 `docker compose up -d --build`，用于本地开发自测）。

## 范围外（v1 不做）

- cosign 镜像签名（keyless via Sigstore Fulcio）
- SBOM 生成（anchore/sbom-action）
- Trivy CVE 扫描
- Docker Hub mirror
- `:edge` 标签（main 分支每次 push 自动 build）
- `:rc` 系列预发布标签（已支持语义：`v0.2.0-rc.1` tag 会自动创建 `:v0.2.0-rc.1`、`:0.2.0-rc.1` 标签）

任何一项后续单独设计实施，不阻塞 v1 发布。

## 验收标准

| 标准 | 测法 |
|---|---|
| workflow 文件存在且 YAML 合法 | git push 触发 GitHub Actions schema 校验通过 |
| `v0.1.0` tag push 后 GHCR 上有镜像 | push 后访问 `https://github.com/<owner>/agent-html-drop/pkgs/container/agent-html-drop`，看到 v0.1.0 / 0.1 / 0.1.0 / latest / sha-* 五个标签 |
| 镜像 manifest list 同时支持 amd64 + arm64 | `docker buildx imagetools inspect ghcr.io/<owner>/agent-html-drop:v0.1.0` 输出含 `linux/amd64` 和 `linux/arm64` |
| post-publish smoke 通过 | workflow 日志显示 `/api/health` 返回 200，文件读写测试通过 |
| 别人 clone repo + `docker compose up -d` 起得来 | 在干净容器 / 干净机器上手测（不需要 build） |
| 现有 pytest 全过（写 spec 时 258 个） | `pytest` 不变 |
| README 把安装步骤更新到 "clone + 编辑 compose + up" | 文档审阅 |

## 替代方案（已否决）

| 方案 | 否决理由 |
|---|---|
| Docker Hub 替代 GHCR | free tier 匿名 pull 限额严（100/6h/IP），CI 推送需独立 secret |
| 本地手动 `scripts/release.sh` | 无 CI cache，每次全量；维护负担高；不适合公开项目 |
| 加 cosign 签名 v1 | Python stdlib 项目 SBOM 薄、CVE 面窄；先做最小可用发布；签名留作 v2 增强 |
| 加 Trivy CVE 扫描 v1 | 同上；首次发布不需要这层；v2 加 |
| 主干 push 自动 build `:edge` | 当前项目主干频率低，`:edge` 标签用户面窄；YAGNI |
| Docker Compose `build:` 仍保留 | 与 `image:` 同时存在时 `build` 优先，会让 pull 失效——必须删 |

## 实施分解（给 writing-plans 阶段）

- 创建 `.github/workflows/release-image.yml`
- 改 `docker-compose.yaml`（image 字段 + 注释）
- 改 `README.md`（Docker 部署段补一句 + 新增发布新版本段）
- 改 `docs/design.md`（新增 §16）
- 改 `docs/tasks.md`（新增条目）
- 改 `scripts/docker-smoke.sh`（新增 `--from-registry` 选项）
- 测试：本地手验 + GitHub 上第一次 tag push 看 workflow 跑通

文件改动预估 ~150 行（workflow ~50 行、compose ~5 行注释、README ~50 行、docs ~30 行、smoke script ~20 行）。