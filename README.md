# AI 数智化投标平台

本仓库包含数智化投标平台的前端、后端、文档解析、OCR、对象存储和大模型接入服务。应用代码位于 `code/`。

## 文档入口

- [5090 发布与部署](code/DEPLOY_5090.md)：`main` 发布、5090 在线构建、可选离线回滚、GPU 0、验收和回滚的唯一入口。
- [本地 OCR 技术方案](code/OCR_DEPLOY.md)：普通 NVIDIA 主机及通用离线环境的 OCR 说明。
- [后端说明](code/sewpg-bid-backend/README.md)
- [前端说明](code/sewpg-bid-frontend/README.md)

`docs/` 保存当前专项交接材料。历史 `doc/` 目录已不在本分支，旧链接不得继续作为部署依据。

## 分支职责

- 开发者在功能分支工作，通过 PR 合入 `Dev`。
- `Dev` 负责人处理冲突并维护通用开发基线，不承担 5090 生产适配。
- 部署负责人从指定 `Dev` SHA 完成 5090 适配、验证并通过 PR 更新 `main`。
- `main` 是唯一稳定发布分支；不设长期 `release` 或服务器专用分支。
- 5090 远端 Codex 只接收部署负责人确认的 `main` SHA，允许在线拉固定镜像、下载模型并现场构建，执行部署与检查但不反向修改仓库。

## 本地开发

普通开发机默认使用 CPU Docling，OCR 为可选扩展：

```bash
cd code
docker compose up -d --build
```

5090 可以现场构建，但必须使用 [5090 发布与部署](code/DEPLOY_5090.md) 的专用 Compose 覆盖和脚本，不能直接套用普通开发命令。
