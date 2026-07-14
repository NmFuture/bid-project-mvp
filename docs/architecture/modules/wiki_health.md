# wiki_health

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/wiki_health.py` |
| 层级 | 服务层 |
| 领域 | Wiki通用 |
| 行数 | 53 |

**职责**: Wiki 目录体检纯函数：统计 md 文件数/卡片数/总字节，估算 token（字节/2），超过 token 预算（默认 12 万）或目录缺失时给 warnings——防止装配时 Wiki 输入超预算。

## 调用链
- **上游**: 未在 app/ 内被 import（由装配/Skill 侧按需调用，运行期挂载点未在代码中确认）。
- **下游**: 文件系统。

## 中间数据与状态
- 无。
