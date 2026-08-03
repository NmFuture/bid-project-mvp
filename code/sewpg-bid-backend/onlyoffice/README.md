# OnlyOffice 目录说明

这个目录维护项目统一的 OnlyOffice 字体镜像。字体安装在镜像内，不依赖研发成员的宿主机字体。

## 当前保留内容

- `Dockerfile`
  - 基于 `onlyoffice/documentserver:9.3.1.2` 构建单一项目镜像
  - 从 Debian 官方包复制 Noto CJK 与 Liberation 的 Regular、Bold 和许可证
- `font-contract.json`
  - 记录界面代表名称、实际字体族、字重和历史别名
- `verify-fonts.sh`
  - 启动与健康检查时验证字体族、字重和别名；缺失时容器直接失败
- `docker-entrypoint.sh`
  - 调整上传限制，刷新字体缓存，验证字体契约并生成 OnlyOffice 字体清单
- `fontconfig/99-sewpg-cjk-font-aliases.conf`
  - 将旧文档中的等线、宋体、Times New Roman、Arial 等名称映射到项目开源字体
- `README.md`
  - 说明本目录在当前项目里的定位

## 字体包 v1

| 界面代表名称 | DOCX 实际字体族 | 字重 |
| --- | --- | --- |
| 等线风格（开源） | `Noto Sans CJK SC` | Regular、Bold |
| 宋体风格（开源） | `Noto Serif CJK SC` | Regular、Bold |
| Times 风格（开源） | `Liberation Serif` | Regular、Bold |
| Arial 风格（开源） | `Liberation Sans` | Regular、Bold |

本地执行 `docker compose build onlyoffice` 即可重建字体镜像。字体来源、许可证和版本由 Docker 构建过程统一，不提交第三方字体二进制。

已有工作副本如果在忽略文件 `.env` 中保留了旧的 `ONLYOFFICE_IMAGE=onlyoffice/documentserver:9.3.1.2`，需按 `.env.example` 更新为字体镜像名后再重建；新拉取的环境直接使用模板默认值。

## 已清理内容

以下旧资产已经移除，不再作为当前项目的运行或联调入口：

- 未附许可证的历史 `Songti.ttc`、`ArialUnicode.ttf`
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
