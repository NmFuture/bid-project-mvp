# 技术标三级目录索引 JSON —— 存储位置与调用说明

> 适用页面：`/workspace/tech/materials/raw`（素材库 RAW 树）、`/workspace/tech/materials/wiki`（Wiki 镜像树）
> 核心文件：`technical_material_index.json`（三级目录结构 + 每级 tag，schema v2）
> 最后核对：2026-06-19（与代码、compose 配置一致）

---

## 1. 这份 JSON 是什么

技术标素材库维护一份**动态更新的三级目录结构 JSON 索引**，作为 Wiki 构建 / 项目解析的"约定层"。

- **结构真值**来自数据库（目录树、文件清单）。
- **tag 真值**就是这份 JSON 本身（v2 起，不再是数据库）。你在页面上手工配的 tag，最终都落进这个文件。
- `raw` 页和 `wiki` 页读的是**同一份** JSON。

---

## 2. 存储位置（关键）

### 2.1 容器内路径

```
/data/documents/_runtime/materials/technical_material_index.json
```

代码常量（`app/services/technical_material_index.py:51`）：

```python
TECHNICAL_MATERIAL_INDEX_PATH = (
    settings.documents_dir / "_runtime" / "materials" / "technical_material_index.json"
)
# settings.documents_dir 来自环境变量 DOCUMENTS_DIR，compose 中为 /data/documents
```

### 2.2 宿主机真实落点 —— Docker named volume，不是源码目录

- compose 中 `fastapi` / `worker` 服务都设了 `DOCUMENTS_DIR=/data/documents`，
  并挂载 named volume `documents:/data/documents`
  （`docker-compose.yml` 第 34/90/113/165/321 行）。
- 卷名 `documents` 由 Docker 管理，物理路径形如：
  ```
  /var/lib/docker/volumes/<项目名>_documents/_data/_runtime/materials/technical_material_index.json
  ```
- ⚠️ **在 `~/Desktop/NmFuture_dev` 源码副本里看不到它**，它不在 bind-mount 里。要看真身必须进容器：

  ```bash
  docker compose exec fastapi cat \
    /data/documents/_runtime/materials/technical_material_index.json
  ```

### 2.3 为什么放 named volume

- 后端代码烧进 Docker 镜像（非 bind-mount），但**运行期数据**（文档、索引）放在 named volume，
  容器重建 / 重启 / rebuild 镜像都不会丢。
- 写盘走原子换名（`.tmp → os.replace`，`bid_runtime_state.write_json_file_atomic`），不会写一半损坏。

---

## 3. 如何调用

### 3.1 读索引（前端 raw / wiki 页用的就是它）

```
GET /api/technical/materials/index
```

- 行为：若索引尚未生成（首次访问或被清空），**即时 rebuild 一次再返回**。
- 返回：完整的 JSON（结构见第 4 节）。
- 前端封装：`src/api/index.js` → `materialsApi.index()`
  （目前 `TechnicalProjectWizardModal.jsx` 在用）。

```bash
# 容器外直接打（若端口映射到本机 80）
curl http://127.0.0.1/api/technical/materials/index
```

### 3.2 写 tag（v2 新增，tag 真值落 JSON 自身）

```
PUT /api/technical/materials/index/tags
Content-Type: application/json

{ "targetId": "RAW-0012" | "<folderId>" | "<目录path>", "tags": ["机型A", "..."] }
```

- `targetId` 以 `RAW-` 开头 → 按**文件** id 定位；
  否则按 **folderId**（数字主键字符串化）或**目录 path** 定位 tier / 3 级目录。
- `tags` 经 `normalize_material_tags` 规整（与文件 tag 同一套规则）。
- 返回：成功 `{ "ok": true, "node": {...} }`；定位失败 `{ "ok": false, "error": "..." }`。

```bash
curl -X PUT http://127.0.0.1/api/technical/materials/index/tags \
  -H 'Content-Type: application/json' \
  -d '{"targetId":"RAW-0012","tags":["风机","质保"]}'
```

> 注：当前前端只接了**读**（`materialsApi.index()`），写 tag 的 PUT 接口尚未在 UI 接入。
> 技术标改 tag 应走这个新 PUT 接口，**不要**走旧的 DB 写入入口
> （`material_update_metadata.py`、`material_tag_import*.py` 写的 tag 不进 JSON）。

### 3.3 后端代码内调用

```python
from app.services.technical_material_index import (
    load_technical_material_index,      # 只读，返回 dict（空则 {}）
    rebuild_technical_material_index,   # async，从 DB 重建并写盘
    set_tags_for_node,                  # async，人工打 tag，真值落 JSON
)
```

---

## 4. JSON 结构（schema v2）

```jsonc
{
  "bidType": "technical",
  "schemaVersion": 2,
  "tagsSourceOfTruth": "index",        // ← tag 真值在本文件，不在 DB
  "generatedAt": "2026-06-18T...",
  "stats": { "tierCount": 3, "thirdLevelFolderCount": 12, "fileCount": 240 },
  "tiers": [
    {
      "name": "标准文件",               // 2 级真名：标准文件 / 客户定制 / 项目定制
      "tier": "standard",              // normalize 后的枚举值
      "path": "标准文件",
      "folderId": 1,                   // 数字主键，tag 按它认领
      "fileCount": 120,
      "tags": [],                      // ← tier 级 tag
      "folders": [
        {
          "name": "...", "path": "...", "tier": "standard",
          "folderId": 7,
          "customerName": "", "customerId": "",
          "projectId": "", "projectCode": "", "description": "",
          "fileCount": 30, "updatedAt": "...",
          "tags": [],                  // ← 3 级目录 tag
          "files": [
            { "id": "RAW-0012", "name": "...", "path": "...",
              "ext": "pdf", "cleanStatus": "...", "tags": [] }  // ← 文件 tag
          ]
        }
      ]
    }
  ]
}
```

每一级（tier / 3 级 folder / file）都有自己的 `tags[]`。

---

## 5. tag 不丢的保障（v2 merge-preserve）

rebuild 时结构真值从 DB 重建，但 tag **按 id 认领**回填：

- 文件按 `RAW-xxxx` 认领；
- 目录 / tier 按 `folderId` 认领。

因此**改名、跨目录移动文件，tag 会跟着走、不丢**（已验证 RAW-0182 跨目录移动 tag 跟随）。
只有文件被**真删**，其 tag 才自然消失。

并发安全：rebuild 与 set_tags 都持模块级 `_INDEX_WRITE_LOCK`（asyncio.Lock）。

自动重建钩子：`TechnicalMaterialStore._refresh_index` 包裹了建 / 删 / 移目录、移 / 删文件、上传、拆分、改名、bootstrap 等 10 个改结构方法，改完即同步重建索引。

---

## 6. 安全性与风险

| 维度 | 结论 |
|------|------|
| 持久性 | ✅ named volume 独立于容器，`docker compose down`（不带 `-v`）、rebuild、重启都不丢 |
| 写入完整性 | ✅ 原子换名，不会写一半损坏 |
| 手工 tag 被覆盖 | ✅ merge-preserve 按 id 认领，rebuild 不丢 tag |
| **误删卷** | 🔴 `docker compose down -v` 的 `-v` 会删 named volume，tag 全没。**严禁带 `-v`** |
| **唯一副本** | 🔴 只存一份，git 仓库无副本。换机器 / 重装 Docker / 误删卷即丢失 |

### 备份（建议定期执行）

```bash
docker compose exec fastapi cat \
  /data/documents/_runtime/materials/technical_material_index.json \
  > ~/Desktop/technical_material_index.backup.$(date +%Y%m%d).json
```

### 从备份恢复

```bash
docker compose cp ~/Desktop/technical_material_index.backup.YYYYMMDD.json \
  fastapi:/data/documents/_runtime/materials/technical_material_index.json
```

---

## 7. 相关代码索引

| 用途 | 位置 |
|------|------|
| 路径常量 / 读写 / rebuild / set_tags | `app/services/technical_material_index.py` |
| GET 读索引接口 | `app/api/routes/technical.py:536` |
| PUT 写 tag 接口 | `app/api/routes/technical.py:553` |
| 原子写盘 | `app/services/bid_runtime_state.py`（`write_json_file_atomic`） |
| compose 卷与环境变量 | `docker-compose.yml`（DOCUMENTS_DIR、documents 卷） |
| 前端读封装 | `sewpg-bid-frontend/src/api/index.js`（`materialsApi.index`） |

> ⚠️ 改后端这些模块后需 `docker compose build fastapi worker && docker compose up -d fastapi worker` 才生效（源码烧进镜像，非 bind-mount）。
