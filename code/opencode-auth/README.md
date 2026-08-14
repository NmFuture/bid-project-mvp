# opencode-auth（opencode 鉴权承载）

本目录是 opencode 容器鉴权文件的**运行时挂载点**，默认不放任何真实内容。

`code/docker-compose.yml` 把它以只读方式挂进容器：

```yaml
- ${OPENCODE_AUTH_HOST_DIR:-./opencode-auth}:/bootstrap/opencode-host:ro
```

entrypoint（`code/sewpg-bid-backend/opencode/docker-entrypoint.sh:7-9`）在启动时检测
`/bootstrap/opencode-host/auth.json`，存在就拷贝到 opencode home（`/root/.local/share/opencode/auth.json`）。

## auth.json 是什么

opencode 的 provider 凭证存储文件，即 `opencode auth login` 写出的那份，按 provider ID
保存登录凭证（API key 或 OAuth token）。脱敏模板：

```json
{
  "<provider-id>": {
    "type": "api",
    "key": "<your-provider-key>"
  }
}
```

OAuth 类型的条目会多 `access` / `refresh` / `expires` 字段，结构以 `opencode auth login`
实际产物为准。

## 何时需要

**大多数部署不需要 auth.json。** 本项目默认走环境变量注入：entrypoint 根据
`INTERNAL_LLM_BASE_URL` / `INTERNAL_LLM_API_KEY` 生成 runtime 配置，API key 直接写进
provider options，不依赖 auth.json。

只有使用必须 OAuth 登录、无法以环境变量传 key 的 provider 时，才需要把 auth.json 放进本目录。

## 怎么生成

1. 在能访问对应 provider 的机器上执行 `opencode auth login` 完成登录；
2. 从该机器的 `~/.local/share/opencode/auth.json` 拷贝到本目录（可用
   `OPENCODE_AUTH_HOST_DIR` 指向其他路径，不必真的放这里）；
3. 重启 opencode 容器，entrypoint 会自动拷入。

## 与 OPENCODE_SERVER_PASSWORD 的区别（不要混淆）

| | auth.json | OPENCODE_SERVER_PASSWORD |
| --- | --- | --- |
| 方向 | opencode → LLM provider（**出站**） | fastapi/worker → opencode:4096（**入站**） |
| 性质 | provider 的 OAuth / API key 凭证 | opencode serve 端口的 HTTP Basic 鉴权密码（engine-10，用户名固定 `opencode`） |
| 来源 | `opencode auth login` 生成 | 部署方在 `.env` 中自行设定 |
| 何时需要 | 仅 OAuth 型 provider | 生产 / 5090 必填，本地开发可留空 |

两者完全独立，启用哪一个都不影响另一个。

## 提交约束

真实 auth.json 是凭证，**禁止提交**；根 `.gitignore` 已排除
`code/opencode-auth/auth.json`。本目录只提交本 README 和 `.gitkeep`。
