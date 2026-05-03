# OnlyOffice 目录说明

这个目录现在只保留当前 Docker Compose 运行路径需要的 OnlyOffice 辅助文件。

## 当前保留内容

- `docker-entrypoint.sh`
  - 被 `code/docker-compose.yml` 挂载到 OnlyOffice Document Server 容器
  - 启动时调整上传、下载、图片大小和 nginx body size 限制
- `README.md`
  - 说明本目录在当前项目里的定位

## 已清理内容

以下旧资产已经移除，不再作为当前项目的运行或联调入口：

- 本地 FastAPI demo 后端
- 独立 OnlyOffice smoke 页面
- 固定样例 `sample.docx`
- 单独拉起 OnlyOffice 的历史 compose 文件
- 旧前端 bridge 参考文档
- 本地验证依赖、运行数据、日志和临时密钥

当前正式能力已经并入主链路：

- FastAPI 负责 OnlyOffice 文档会话、回调和下载接口
- 前端 `S5 共创` 通过正式 API 获取 OnlyOffice 配置，`S6 导出` 读取同一项目文档
- `code/docker-compose.yml` 统一拉起 `onlyoffice` 服务

后续如果继续做 OnlyOffice 能力，直接修改：

- `../app`
- `../../sewpg-bid-frontend`
- `../../../docker-compose.yml`
