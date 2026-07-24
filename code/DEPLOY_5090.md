# 5090 发布与部署

本文件是 5090 生产发布的唯一操作入口。普通开发和通用 OCR 部署见 [`OCR_DEPLOY.md`](OCR_DEPLOY.md)。

## 1. 发布边界

- 功能开发：开发者在各自分支工作，通过 PR 合入 `Dev`。
- 开发基线：`Dev` 负责人处理冲突并维护通用开发配置，不负责 5090 专用适配。
- 稳定发布：部署负责人选择一个明确的 `Dev` SHA，在短期工作分支完成适配、测试并向 `main` 提交 PR；合并后删除短期分支。
- 生产基线：`main` 只保存可发布版本，不作为日常开发分支，也不另设长期 `release` 或服务器专用分支。
- 现场执行：远端 Codex 只部署已由部署负责人确认的 `main` SHA 对应发布包，不合并代码、不改受版本控制文件、不现场构建镜像。

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

普通开发机只用 `docker-compose.yml`。5090 实际叠加顺序固定为：

```text
docker-compose.yml
docker-compose.airgap.yml
docker-compose.ocr.yml
docker-compose.ocr.airgap.yml
docker-compose.5090.yml
```

## 3. 发布前确认

部署负责人必须明确以下信息：

- 本次纳入的 `Dev` SHA 和最终 `main` SHA。
- 目标发布标签，建议使用 `main-YYYYMMDD-<main短SHA>`。
- 数据结构、环境变量、镜像和模型是否有兼容性变化。
- 上一稳定发布的 SHA、发布包和 `.env` 备份位置。
- 5090 变更窗口和回滚负责人。

真实密钥不得进入 Git、发布说明、聊天、截图、日志或 `bundle-manifest.json`。

## 4. 构建 5090 离线包

只能在联网、干净的 `linux/amd64` 构建环境，从已审核的 `main` SHA 构建：

```bash
git fetch origin main
git switch --detach <main-sha>
test "$(git rev-parse HEAD)" = "<main-sha>"
test -z "$(git status --porcelain)"

cd code
./scripts/build-5090-bundle.sh ./offline-dist/5090 <release-tag>
cat ./offline-dist/5090/MAIN_SHA
(cd ./offline-dist/5090 && sha256sum -c SHA256SUMS)
```

发布包包含：

- 9 个镜像：web、FastAPI/worker、Docling、OpenCode、OnlyOffice、Redis、PostgreSQL、MinIO、OCR。
- 5 个 Compose 文件和已写入本次镜像标签的 `.env.airgap.example`。
- PostgreSQL `initdb/`、OnlyOffice 入口脚本、字体和 fontconfig。
- 启动脚本、`bundle-manifest.json`、`MAIN_SHA` 和 `SHA256SUMS`。

`bundle-manifest.json` 记录源 Git SHA、镜像名称和 OCR 源镜像 digest。`SHA256SUMS` 用于介质完整性校验。

OCR 模型权重不在镜像 tar 内。完全离线部署前，必须把已验证的权重缓存单独预热到 `.localdata/ocr/huggingface`，随介质传输并单独生成 SHA-256 清单；空缓存只能视为预检警告，不能判定离线 OCR 就绪。

## 5. 现场目录和配置

每个发布包使用独立目录，不覆盖上一稳定版本。例如：

```text
/opt/sewpg-bid/releases/<release-tag>/
├── MAIN_SHA
├── SHA256SUMS
├── bundle-manifest.json
├── .env.airgap.example
├── images/
├── initdb/
└── sewpg-bid-backend/onlyoffice/
```

进入发布目录后先校验，再创建受控配置：

```bash
sha256sum -c SHA256SUMS
test "$(cat MAIN_SHA)" = "<approved-main-sha>"
install -m 600 .env.airgap.example .env
```

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
| `OCR_HF_CACHE_DIR` | 指向已预热并校验的模型缓存 |

不要改发布脚本生成的镜像标签，除非该标签与发布包 manifest 不一致且已经停止部署排查。

## 6. 预检和启动

先加载镜像，再做只读预检：

```bash
./load-airgap-images.sh ./images/sewpg-bid-images-<release-tag>.tar
./up-5090.sh ./.env --check-only
```

预检会阻断以下情况：

- 非 `x86_64` 主机，Docker/NVIDIA runtime 不可用，或 GPU 0 不可见。
- 集团网关、模型、数据库、MinIO 或管理员必填项为空/仍为示例值。
- Docling 或 OCR 没有被同时限制在 GPU 0。
- Compose 不能完整解析。

预检通过后才能启动：

```bash
./up-5090.sh ./.env
```

该脚本固定执行 `docker compose ... up -d --no-build`，不会现场拉镜像或构建镜像。

## 7. 验收

以下命令在发布目录执行。命令使用模板默认端口；如果 `.env` 改过端口，只替换对应端口号，禁止打印或 `source` 整个 `.env`：

```bash
docker compose \
  --env-file ./.env \
  -f docker-compose.yml \
  -f docker-compose.airgap.yml \
  -f docker-compose.ocr.yml \
  -f docker-compose.ocr.airgap.yml \
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

升级前保留上一版本的完整发布目录、镜像 tar、`.env`、数据库/对象存储备份和验收记录。不得执行 `docker compose down -v`。

失败回滚：

1. 停止继续验收并记录失败点。
2. 回到上一版本发布目录，核对其 `MAIN_SHA` 和 `SHA256SUMS`。
3. 重新加载上一版本镜像 tar，使用上一版 `.env` 执行 `./up-5090.sh ./.env`。
4. 复查容器、GPU、API、Docling、OCR 和大模型调用。

如果本次包含不可逆数据库或对象结构变更，未确认数据回滚方案前不得继续发布。

## 9. 禁止事项

- 5090 不跟踪 `Dev`，不从功能分支部署。
- 不在 5090 上执行 `docker pull`、`docker compose build` 或热修改代码/Compose。
- 不使用 `gpus: all`，不把本项目绑定到 GPU 1。
- 不删除命名卷，不用新环境覆盖上一版受控 `.env`。
- 不把“脚本执行结束”直接写成“部署验收通过”。
