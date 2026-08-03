# 5090 发布与部署

本文件是 5090 生产发布的唯一操作入口。普通开发和通用 OCR 部署见 [`OCR_DEPLOY.md`](OCR_DEPLOY.md)。

## 1. 发布边界

- 功能开发：开发者在各自分支工作，通过 PR 合入 `Dev`。
- 开发基线：`Dev` 负责人处理冲突并维护通用开发配置，不负责 5090 专用适配。
- 稳定发布：部署负责人选择一个明确的 `Dev` SHA，在短期工作分支完成适配、测试并向 `main` 提交 PR；合并后删除短期分支。
- 生产基线：`main` 只保存可发布版本，不作为日常开发分支，也不另设长期 `release` 或服务器专用分支。
- 现场执行：远端 Codex 只部署已由部署负责人确认的 `main` SHA；允许在 5090 在线拉取仓库声明的镜像、下载模型并现场构建，但不合并代码、不提交服务器改动，也不绕过 `main` 热改受版本控制文件。

“代码已进入 `main`”“发布包已生成”“服务已部署”“业务验收通过”是四个不同状态，不得混报。

## 2. 固定拓扑

5090 发布共运行 10 个容器：

| 容器 | 职责 | GPU |
|---|---|---|
| `web` | Nginx 前端和 API/OnlyOffice 反向代理 | 无 |
| `fastapi` | 业务 API | 无 |
| `worker` | Redis 后台任务 | 无 |
| `docling-worker` | Docling 文档解析 | 仅 GPU 0 |
| `ocr` | vLLM + `baidu/Unlimited-OCR` | 仅 GPU 0 |
| `opencode` | 大模型任务编排 | 无 |
| `onlyoffice` | Office 预览与编辑 | 无 |
| `postgres` | 结构化数据和 pgvector | 无 |
| `redis` | 队列和任务状态 | 无 |
| `minio` | 业务对象存储 | 无 |

固定要求：

- 主机为 `linux/amd64`，项目只能使用物理 GPU 0；GPU 1 不得出现本项目进程。
- Docling 使用 `Dockerfile.docling-worker.cuda`、`docling==2.108.0`、PyTorch CUDA 13.0。
- OCR 为独立容器，模型权重挂载到 `./.localdata/ocr/huggingface`。
- Docling 和 OCR 都必须同时设置 Docker 设备预留、`NVIDIA_VISIBLE_DEVICES=0` 和 `CUDA_VISIBLE_DEVICES=0`。
- 第一版 PostgreSQL、MinIO 和其他命名卷都落系统 SSD；不得自行迁移到其他磁盘。
- 生产大模型通过集团 OpenAI-compatible 网关调用，必须使用精确模型 ID。

普通开发机只用 `docker-compose.yml`。5090 默认在线构建使用：

```text
docker-compose.yml
docker-compose.ocr.yml
docker-compose.5090.yml
```

需要离线恢复时，再额外叠加 `docker-compose.airgap.yml` 和 `docker-compose.ocr.airgap.yml`，禁止 Compose 拉取或构建。

## 3. 发布前确认

部署负责人必须明确以下信息：

- 本次纳入的 `Dev` SHA 和最终 `main` SHA。
- 目标发布标签；在线脚本自动使用 `main-<main前12位SHA>`。
- 数据结构、环境变量、镜像和模型是否有兼容性变化。
- 上一稳定发布的 SHA、发布包和 `.env` 备份位置。
- 5090 变更窗口和回滚负责人。

真实密钥不得进入 Git、发布说明、聊天、截图、日志或 `bundle-manifest.json`。

## 4. 5090 在线构建与首次部署

5090 可以直接从已审核的 `main` SHA 在线构建。先同步并确认版本，不能从 `Dev` 或功能分支部署：

```bash
git fetch origin main
git switch main
git pull --ff-only origin main
test "$(git rev-parse HEAD)" = "<main-sha>"
test -z "$(git status --porcelain)"

cd code
install -m 600 .env.airgap.example .env
# 编辑 .env：写入受控凭据和精确模型 ID
./scripts/up-5090.sh ./.env --check-only
./scripts/up-5090.sh ./.env
```

在线启动脚本会：

- 拉取 Compose 中声明的 OnlyOffice、PostgreSQL、Redis、MinIO 和 OCR 镜像。
- 使用 `--pull` 基于当前 `main` 源码构建 web、FastAPI/worker、GPU Docling 和 OpenCode 镜像。
- 启动 10 个容器；OCR 缓存为空时，通过 `HF_ENDPOINT` 首次下载 `baidu/Unlimited-OCR` 权重并复用本地缓存。
- 输出当前 Git SHA；部署记录中再保存应用镜像 ID、外部镜像 digest 和验收结果。

Docker Hub 或模型源偶发失败时，可以重试失败的 pull/build；不要因此改 Compose、切换未批准镜像或删除已有卷。必要时再改走第 8 节的离线恢复路径。

## 5. 配置

`.env` 是服务器受控运行配置，权限保持为 `600`，不得提交。它可以从 `.env.airgap.example` 创建；这里复用的是完整生产配置模板，不代表必须离线部署。

`.env` 至少要改完以下项目：

| 配置 | 要求 |
|---|---|
| `INTERNAL_LLM_BASE_URL`、`INTERNAL_LLM_API_KEY` | 集团网关真实地址和密钥 |
| `OPENCODE_PROVIDER_ID`、`OPENCODE_MODEL_ID` | 与集团网关匹配的 provider 和精确模型 ID |
| `DEFAULT_LLM_BASE_URL`、`DEFAULT_LLM_API_KEY`、`DEFAULT_LLM_MODEL` | 系统默认模型；模型必须是精确 ID |
| `POSTGRES_PASSWORD` | 替换示例密码 |
| `DATABASE_URL` | 与新 PostgreSQL 密码同步；密码含特殊字符时先做 URL 编码 |
| `MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD` | 替换示例凭据 |
| `AUTH_ADMIN_EMAIL`、`AUTH_ADMIN_PASSWORD`、`AUTH_ADMIN_NAME` | 初始管理员；必须替换 `123456` |
| `OCR_GPU_DEVICE_ID` | 必须为 `0` |
| `OCR_HF_CACHE_DIR` | 默认 `./.localdata/ocr/huggingface`；允许首次在线下载并持久化 |
| `HF_ENDPOINT` | 5090 当前优先使用可达的 `https://hf-mirror.com` |

在线脚本自动把四个应用镜像统一标记为 `main-<main前12位SHA>`，并基于官方 `onlyoffice/documentserver:9.3.1.2` 构建项目字体镜像 `sewpg-bid/onlyoffice:9.3.1.2-fontpack-v1`；不需要手工修改模板里的离线镜像标签。其他外部服务使用仓库 Compose 声明的 tag，拉取后记录实际 digest。

## 6. 预检和启动

先做只读预检：

```bash
./scripts/up-5090.sh ./.env --check-only
```

预检会阻断以下情况：

- 非 `x86_64` 主机，Docker/NVIDIA runtime 不可用，或 GPU 0 不可见。
- 集团网关、模型、数据库、MinIO 或管理员必填项为空/仍为示例值。
- Docling 或 OCR 没有被同时限制在 GPU 0。
- Compose 不能完整解析。

预检通过后在线拉取、构建并启动：

```bash
./scripts/up-5090.sh ./.env
```

脚本先 pull 外部镜像，再 build 四个应用镜像，最后执行 `up -d --no-build`，避免启动阶段隐式重建。OCR 首次下载权重可能较慢，不要把容器处于 `starting` 立即判为失败。

## 7. 验收

以下命令在 `code/` 目录执行。命令使用模板默认端口；如果 `.env` 改过端口，只替换对应端口号，禁止打印或 `source` 整个 `.env`：

```bash
docker compose \
  --env-file ./.env \
  -f docker-compose.yml \
  -f docker-compose.ocr.yml \
  -f docker-compose.5090.yml \
  ps

curl -fsS http://127.0.0.1:80/ >/dev/null
curl -fsS http://127.0.0.1:80/api/healthz
curl -fsS http://127.0.0.1:80/ds/healthcheck >/dev/null
curl -fsS http://127.0.0.1:4096/global/health
curl -fsS http://127.0.0.1:8000/health

docker exec sewpg_bid_docling_worker python -c \
  'import torch; print({"cuda": torch.cuda.is_available(), "device": torch.cuda.get_device_name(0)})'
nvidia-smi -i 0
nvidia-smi -i 1
```

还必须完成三项真实业务检查：

1. 上传一个获准的测试文档完成 Docling 解析，确认结果写入且 GPU 0 有活动。
2. 发起一次真实 OCR 任务，确认返回结果且 GPU 0 有活动。
3. 对集团网关发起一次获准的最小鉴权调用，确认使用指定模型成功返回。仅 DNS/TCP 可达或返回 401 都不能判定可用。

验收结论至少记录：`main` SHA、发布标签、10 个容器状态、GPU 0/1 检查、Docling/OCR/大模型结果、异常和回滚状态。记录中不得出现密钥。

## 8. 升级与回滚

升级前保留上一版应用镜像 tag、`.env`、数据库/对象存储备份和验收记录。重要版本可以在部署成功后运行 `./scripts/build-5090-bundle.sh` 生成离线回滚包；离线包是可选回滚能力，不再是首次部署前置门禁。不得执行 `docker compose down -v`。

失败回滚：

1. 停止继续验收并记录失败点。
2. 将 `.env` 中应用镜像切回上一版已验证 tag；如已有离线包，先核对 `MAIN_SHA` 和 `SHA256SUMS` 并加载镜像。
3. 在线回滚使用当前源码对应的上一版 tag 启动；离线包内执行 `./up-5090.sh ./.env --offline`，源码工作树内执行 `./scripts/up-5090.sh ./.env --offline`。
4. 复查容器、GPU、API、Docling、OCR 和大模型调用。

如果本次包含不可逆数据库或对象结构变更，未确认数据回滚方案前不得继续发布。

## 9. 禁止事项

- 5090 不跟踪 `Dev`，不从功能分支部署。
- 允许按本手册在线 pull、下载模型和 build；失败时不得临时改源码、Compose 或 Dockerfile 绕过问题，代码修复必须回到 `main`。
- 不使用 `gpus: all`，不把本项目绑定到 GPU 1。
- 不执行 `down -v` 或无范围的 `docker system prune`，不误删业务命名卷。
- 不把“脚本执行结束”直接写成“部署验收通过”。
