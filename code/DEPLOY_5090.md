# 5090 发布与部署

## 分支职责

- 开发者继续从各自功能分支向 `Dev` 提交 PR；`Dev` 保持通用开发基线，默认使用 CPU Docling，OCR 仍是可选扩展。
- `main` 只保存已通过部署负责人验证的可发布版本，不作为日常功能开发起点。
- 每次发布从当前 `main` 建立临时 `release/5090-*` 分支，合并指定的 `Dev` SHA，完成 5090 适配和验证后再向 `main` 提交 PR。第一次重建 `main` 时可直接从指定 `Dev` SHA 建发布分支。
- 服务器只跟踪 `main`；禁止直接跟踪 `Dev`，也禁止在服务器上修改受版本控制的文件。

## 5090 固定配置

- 主机：`linux/amd64`、两张 RTX 5090；项目只使用物理 GPU 0，GPU 1 不得占用。
- Docling：`docling==2.108.0`、`torch==2.12.1+cu130`、`torchvision==0.27.1+cu130`，使用 `Dockerfile.docling-worker.cuda`。
- OCR：独立 `ocr` 容器，使用 `vllm/vllm-openai:unlimited-ocr` 和 `baidu/Unlimited-OCR`。
- `docling-worker` 与 `ocr` 都同时设置设备预留、`NVIDIA_VISIBLE_DEVICES=0` 和 `CUDA_VISIBLE_DEVICES=0`。
- 5090 的 Hugging Face 直连不可用；构建和首次模型准备使用 `HF_ENDPOINT=https://hf-mirror.com`。

普通开发机只使用 `docker-compose.yml`。5090 发布配置额外叠加：

```bash
docker compose \
  --env-file .env \
  -f docker-compose.yml \
  -f docker-compose.ocr.yml \
  -f docker-compose.5090.yml \
  config --quiet
```

## 构建发布包

在联网、干净的 `linux/amd64` 构建环境，从已审核的 `main` SHA 执行：

```bash
cd code
./scripts/build-5090-bundle.sh ./offline-dist/5090 <release-tag>
```

脚本构建 CUDA Docling 镜像、纳入 OCR 镜像，并在 manifest 中记录实际 OCR 源 digest 后生成镜像 tar。OCR 模型权重必须另外预热到 `.localdata/ocr/huggingface` 后随发布介质传输，或制作已包含权重的内部冻结镜像；不能只打包 vLLM 镜像就宣称离线 OCR 可用。

## 服务器启动

服务器收到发布包后，先校验 SHA-256 并加载镜像，再从模板创建权限为 `600` 的 `.env`。真实密钥只进入该文件，不提交到 Git。

```bash
./load-airgap-images.sh ./images/sewpg-bid-images-<release-tag>.tar
install -m 600 .env.airgap.example .env
# 注入集团网关、数据库、MinIO 和管理员等真实配置
./up-5090.sh ./.env --check-only
./up-5090.sh ./.env
```

`up-5090.sh` 只执行 `docker compose ... up --no-build`，并在启动前阻断默认密码、空集团网关配置以及任何非 GPU 0 的 Docling/OCR 设备声明。

## 验收

```bash
docker compose <冻结参数> ps
nvidia-smi
curl --fail http://127.0.0.1:8000/health
```

必须完成真实 Docling 解析和真实 OCR 请求，确认两者在 GPU 0 上产生显存或利用率变化，同时 GPU 1 没有本项目进程。集团大模型网关必须完成带鉴权的最小真实请求；仅返回 401 只能证明网络可达，不能判定业务可用。
