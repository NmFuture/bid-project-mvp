# OnlyOffice 前端桥接参考

这份说明只保留对当前项目还有价值的部分，来自旧的 `sewpg-bid-frontend` 副本接入经验。

## 还能复用的思路

### 1. S9 页面不要让 healthcheck 决定是否渲染编辑器
- 更稳的条件是：后端已经返回可用的 OnlyOffice 会话，就直接尝试挂载。
- 只有脚本加载失败、`DocEditor` 初始化失败、运行时异常时，才回退到 textarea 兜底。

### 2. 编辑器高度要由外层容器保留
- 不要把高度只写在 `DocEditor` 的挂载节点上。
- 应该是外层固定高度，内层挂载点只做 `w-full h-full`。
- 否则 `DocsAPI.DocEditor(...)` 替换节点后，iframe 容易塌缩。

### 3. 后端要把文档会话信息聚合成前端能直接消费的 payload
- 旧方案在 mock-server 里做过桥接：
  - `GET /api/projects/:id/document`
  - `POST /api/projects/:id/document/force-save`
- 当前正式实现应放到真实 FastAPI 中，而不是继续保留旧 mock bridge。

### 4. 材料库内嵌编辑器是可选参考，不是当前 MVP 主链路
- 旧副本曾做过 `GET /api/materials/raw/:fileId/edit-session`
- 但底层仍然复用固定 `sample.docx`
- 这只能证明“页面内嵌编辑器”能做，不代表材料库已经具备真实文件映射能力

## 当前项目里真正该落的文件

- 前端：`/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend`
- 后端：`/Users/wlb/Agent/bid-project/code/backend`

如果要把 OnlyOffice 正式并入当前 MVP，应该做的是：

1. 在真实 FastAPI 中提供：
   - `/api/documents/{id}/config`
   - `/api/documents/{id}/download`
   - `/api/documents/{id}/meta`
   - `/api/onlyoffice/callback/{id}`
2. 前端 S9 页面调用真实 FastAPI，不再依赖旧的 mock bridge
3. 非 MVP 页面继续走 FastAPI mock，不在 OnlyOffice 目录里再维护一份前端副本
