# 本地 OCR 服务技术方案

## 结论

本地 OCR 能力应作为产品内置的可选 Docker 扩展提供：项目交付 OCR 的 compose 文件、启动脚本、默认配置和后端适配，但 OCR 推理进程独立运行在 `ocr` 容器中。

这个思路合理。它对用户表现为“一键启动本地 OCR 服务，产品内可直接使用”，同时避免把 GPU/vLLM/模型权重打进 FastAPI 主镜像，降低普通部署、开发调试和 CI 的成本。

默认策略：

- 当前 Mac 启动产品本体，不启动 OCR：`./start-local.sh`
- NVIDIA GPU 主机带 OCR 启动：`./start-ocr.sh`
- 离线带 OCR 启动：`ENABLE_OCR=true ./up-airgap.sh ./.env`

以上是通用环境入口。5090 生产环境必须使用 [`DEPLOY_5090.md`](DEPLOY_5090.md) 和 `up-5090.sh`：默认允许在线拉取 OCR 镜像并在首次启动时下载权重；`build-5090-bundle.sh` 只用于额外制作离线回滚包。不得用通用 `start-ocr.sh` 代替 5090 流程。

## 当前 Mac 设备怎么启动

当前 Apple Silicon Mac 可以一键启动产品本体，但不能本机启动 `vLLM + baidu/Unlimited-OCR` 真推理服务，因为 Docker Desktop for Mac 没有 NVIDIA CUDA runtime。

在当前设备上启动产品：

```bash
cd /path/to/code
./start-local.sh
```

脚本会先校验 `.env` 中的 OnlyOffice 镜像策略并构建当前 `dev-fontpack-v1`。保留官方/旧固定镜像标签的 `.env` 会被阻断，需先按当前 `.env.example` 迁移。

macOS 也可以在 Finder 中双击 `start-local.command`。

如果需要 OCR 功能，有两个可行方式：

- 把 OCR 服务部署到 NVIDIA GPU 服务器，在系统设置中填远程 OCR 地址。
- 到 NVIDIA GPU 主机上运行 `./start-ocr.sh`，让产品和 OCR 一起用 Docker Compose 启动。

## 目标

- 在本地或内网部署 `baidu/Unlimited-OCR`，提供扫描件、图片型 PDF、图片 OCR 能力。
- 服务通过 Docker 编排，不依赖宿主机 Python 包、CUDA Python 环境或手工启动命令。
- 后端继续使用现有 OCR API、任务、候选字段、确认写入和审计流程。
- 无 GPU 或不需要 OCR 的环境仍能正常启动主业务系统。

## 非目标

- 不把 vLLM 和模型权重合并进 FastAPI 镜像。
- 不让 OCR 成为所有环境的强制依赖。
- 不在前端引入另一套 OCR 上传流程；继续复用项目内现有 OCR 入口。

## 架构

```text
浏览器
  |
  v
web/nginx
  |
  v
fastapi  ----->  ocr(vLLM + baidu/Unlimited-OCR)
  |                    |
  |                    v
  |        ./.localdata/ocr/huggingface
  |
  +---- postgres / minio / redis / onlyoffice / opencode

worker  ----->  ocr(vLLM + baidu/Unlimited-OCR)
```

服务边界：

| 模块 | 职责 |
|---|---|
| `fastapi` | 现有 OCR API、文件接收、PDF 转图片、请求 OCR、保存 task/candidate、审计 |
| `worker` | 后台任务中复用同一 OCR 默认配置 |
| `ocr` | vLLM OpenAI-compatible 服务，加载 `baidu/Unlimited-OCR` |
| `./.localdata/ocr/huggingface` | 当前项目目录下的模型权重缓存，避免每次重启重新下载 |

## 关键设计

### 1. OCR 是产品内置能力，但不是主栈默认依赖

OCR 服务占用 GPU 显存，首次启动可能拉取大模型权重，健康检查等待时间长。默认启动会让无 GPU 开发机、CI、普通演示环境失败或变慢。

因此采用可选 compose 扩展：

```bash
docker compose -f docker-compose.yml -f docker-compose.ocr.yml up -d --build
```

产品角度仍然是一键能力，因为用户不需要手工安装 vLLM 或配置 Python，只需要使用产品提供的脚本：

```bash
./scripts/up-ocr.sh
```

该脚本会与其他应用镜像一起构建 `onlyoffice`，再用 `--no-build` 启动，避免干净 GPU 主机缺少项目字体镜像。

### 2. vLLM 独立容器

OCR 容器使用官方支持的镜像和启动参数：

```yaml
image: vllm/vllm-openai:unlimited-ocr
command:
  - baidu/Unlimited-OCR
  - --trust-remote-code
  - --logits_processors
  - vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor
  - --no-enable-prefix-caching
  - --mm-processor-cache-gb
  - "0"
environment:
  NVIDIA_VISIBLE_DEVICES: "0"
  CUDA_VISIBLE_DEVICES: "0"
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          device_ids: ["0"]
          capabilities: [gpu]
```

这样可以把 GPU runtime、模型服务、业务服务的升级风险隔离开。

### 3. 后端复用现有 OCR 抽象

现有接口继续有效：

```text
POST /api/technical/projects/{project_id}/ocr/tasks
GET  /api/technical/projects/{project_id}/ocr/tasks
POST /api/technical/projects/{project_id}/ocr/candidates/{candidate_id}/confirm

POST /api/business/projects/{project_id}/ocr/tasks
GET  /api/business/projects/{project_id}/ocr/tasks
POST /api/business/projects/{project_id}/ocr/candidates/{candidate_id}/confirm
```

当模型名包含 `Unlimited-OCR` 时，后端自动使用 Unlimited-OCR 的请求 recipe：

- prompt：`<image>document parsing.` 或 `<image>Multi page parsing.`
- `skip_special_tokens=false`
- `vllm_xargs.ngram_size=35`
- 单图 `window_size=128`，多页/PDF `window_size=1024`
- 清理返回中的 `<|ref|>` 和 `<|det|>` 标记

## 文件落点

| 文件 | 用途 |
|---|---|
| `docker-compose.ocr.yml` | 在线 OCR compose 扩展 |
| `docker-compose.ocr.airgap.yml` | 离线 OCR compose 覆盖 |
| `scripts/up-ocr.sh` | 一键启动带 OCR 的本地服务 |
| `.env.example` | 在线 OCR 变量模板 |
| `.env.airgap.example` | 离线 OCR 变量模板 |
| `scripts/build-airgap-bundle.sh` | Linux/macOS 离线包，可选包含 OCR 镜像 |
| `scripts/build-airgap-bundle.ps1` | Windows 离线包，可选包含 OCR 镜像 |
| `scripts/up-airgap.sh` | 离线部署，可选启用 OCR |
| `sewpg-bid-backend/app/services/ocr_service.py` | Unlimited-OCR 请求兼容层 |

## 在线部署

部署机要求：

- NVIDIA GPU
- NVIDIA 驱动
- Docker
- NVIDIA Container Toolkit

在 macOS Docker Desktop 或没有 NVIDIA runtime 的机器上，`./scripts/up-ocr.sh` 会提前退出并提示环境缺失；这种环境可以正常启动主产品，但不能本地运行 `vLLM + baidu/Unlimited-OCR` 真推理服务。

启动：

```bash
cd /path/to/code
cp .env.example .env
./start-ocr.sh
```

macOS 也可以在 Finder 中双击 `start-ocr.command`。

常用变量：

```dotenv
OCR_IMAGE=vllm/vllm-openai:unlimited-ocr
OCR_HOST_PORT=8000
OCR_MODEL=baidu/Unlimited-OCR
OCR_GPU_DEVICE_ID=0
OCR_HF_CACHE_DIR=./.localdata/ocr/huggingface
OCR_SHM_SIZE=8g
OCR_HEALTHCHECK_START_PERIOD=20m
HUGGING_FACE_HUB_TOKEN=
HF_ENDPOINT=https://huggingface.co
VLLM_USE_MODELSCOPE=false
```

首次启动会下载模型到当前项目目录下的 `./.localdata/ocr/huggingface`。后续重启复用缓存。该目录已被 `.gitignore` 排除，适合本地缓存、离线预热和部署迁移。

## 系统设置

叠加 `docker-compose.ocr.yml` 后，新环境默认 OCR 配置为：

```dotenv
DEFAULT_OCR_BASE_URL=http://ocr:8000/v1
DEFAULT_OCR_MODEL=baidu/Unlimited-OCR
```

如果数据库中已经保存过 OCR 配置，系统设置页面里的保存值优先。需要切换到本地 OCR 时，在“系统设置 -> PDF/图片识别”中设置：

- Base URL：`http://ocr:8000/v1`
- 模型：`baidu/Unlimited-OCR`
- API Key：留空
- Timeout：建议 `600000` ms 起
- Max Tokens：建议 `8192` 起

## 离线部署

构建包含 OCR 镜像的离线包：

```bash
INCLUDE_OCR=true ./scripts/build-airgap-bundle.sh
```

RTX 5090 默认在线部署入口：

```bash
./scripts/up-5090.sh ./.env
```

需要额外制作离线回滚包时再运行：

```bash
./scripts/build-5090-bundle.sh ./offline-dist/5090 <release-tag>
```

5090 的 Docling 也使用 GPU 0，具体版本、分支职责和现场启动流程见 [`DEPLOY_5090.md`](DEPLOY_5090.md)。

Windows：

```powershell
.\scripts\build-airgap-bundle.ps1 -IncludeOcr
```

离线环境启动：

```bash
./load-airgap-images.sh
ENABLE_OCR=true ./up-airgap.sh ./.env
```

如果模型权重也要求完全离线，需要提前准备以下任一方案：

- 预热 `./.localdata/ocr/huggingface`，并随部署介质迁移。
- 使用内网 Hugging Face mirror，通过 `HF_ENDPOINT` 指向内网地址。
- 制作包含模型权重的自定义 OCR 镜像。

## 运维与风险

| 风险 | 处理 |
|---|---|
| 无 NVIDIA runtime 时 OCR 容器无法启动 | 主服务默认不依赖 OCR；只有 `up-ocr.sh` 或叠加 OCR compose 才启用 |
| 首次拉模型慢 | 使用 `./.localdata/ocr/huggingface` 持久化；离线部署提前预热 |
| OCR 服务启动慢 | 健康检查 `start_period` 默认 20 分钟，可通过 `OCR_HEALTHCHECK_START_PERIOD` 调整 |
| 显存不足 | 调整部署 GPU 或 OCR 并发；必要时独立部署 OCR 节点 |
| 已有数据库 OCR 配置覆盖默认值 | 在系统设置中手动切换到 `http://ocr:8000/v1` |

## 验证命令

静态检查 compose：

```bash
docker compose -f docker-compose.yml -f docker-compose.ocr.yml config
```

检查 OCR 容器健康：

```bash
docker compose -f docker-compose.yml -f docker-compose.ocr.yml ps ocr
curl http://127.0.0.1:8000/health
```

这里的 `8000/health` 是 OCR 服务，不是 FastAPI。主系统 API 通过 web 代理验证：

```bash
curl --fail http://127.0.0.1:80/api/healthz
```

后端单测：

```bash
cd sewpg-bid-backend
PYTHONPATH=. ./.venv/bin/python -m unittest tests.test_ocr_service_unlimited -v
```

## 后续可选增强

- 在前端系统设置中增加“使用内置本地 OCR”按钮，自动填充 `http://ocr:8000/v1` 和 `baidu/Unlimited-OCR`。
- 增加后端 `/api/settings/ocr/local-health`，展示本地 OCR 容器连通性。
- 制作包含模型权重的企业内部分发镜像，减少首次启动等待。
