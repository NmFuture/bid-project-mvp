# 技术标三级目录结构 JSON 索引 — 下游使用 Handoff

> 面向接手 agent：如何读取并使用技术标素材库的三级目录结构 JSON 索引。
> 生成于 2026-06-18，对应后端模块 `app/services/technical_material_index.py`。

---

## 1. 这是什么

技术标素材库的目录结构（1 级 `技术标` → 2 级档位 → 3 级动态子目录）平时只存在 Postgres `raw_folders` 表里。为方便 **Wiki 构建** 和 **项目解析** 复用，后端维护了一份**动态更新的 JSON 快照**，作为三级结构的"约定层"。

- 每次素材目录结构变化（建/删/移目录、上传、拆分、改名、项目 bootstrap）后，由后端钩子**自动重建**，无需手动触发。
- 文件字节存在 MinIO、目录结构存在 Postgres，本 JSON 只是**索引/快照**，不存原始字节。

## 2. 在哪里读（三选一）

| 方式 | 地址 | 说明 |
|------|------|------|
| **HTTP 接口（推荐）** | `GET /api/technical/materials/index` | 经 web 容器：`curl http://localhost/api/technical/materials/index`（已验证 HTTP 200）。空则即时重建再返回。 |
| **容器内文件** | `/data/documents/_runtime/materials/technical_material_index.json` | `docker exec sewpg_bid_fastapi cat <path>` |
| **宿主机 volume** | Docker volume `code_documents` → `/var/lib/docker/volumes/code_documents/_data/_runtime/materials/technical_material_index.json` | macOS 上该路径在 Docker VM 内，Finder 打不开，用 `docker cp` 取出 |

> ⚠️ **不在宿主机源码目录下**。`~/Desktop/NmFuture_dev/...` 这份源码副本里没有此文件——它在 Docker named volume `documents` 上。

拷贝到本地的命令：
```bash
docker cp sewpg_bid_fastapi:/data/documents/_runtime/materials/technical_material_index.json ./technical_material_index.json
```

## 3. JSON 结构（schemaVersion = 1）

```jsonc
{
  "bidType": "技术标",
  "schemaVersion": 1,
  "generatedAt": "2026-06-18 04:57:22",   // 重建时间，可据此判断是否需刷新
  "stats": {
    "tierCount": 3,
    "thirdLevelFolderCount": 8,
    "fileCount": 526
  },
  "tiers": [                               // 2 级档位数组，固定 3 档
    {
      "name": "标准文件",                   // 2 级目录真实名（见第 4 节）
      "tier": "standard",                  // 归一后的档位：standard|customer|project
      "path": "技术标/标准文件",
      "fileCount": 442,
      "folders": [                         // 3 级目录数组（动态）
        {
          "name": "EW5.0-220",
          "path": "技术标/标准文件/EW5.0-220",
          "tier": "standard",
          "customerName": "",              // customer 档才有值
          "customerId": "",                // 暂未回填（恒空，见第 5 节）
          "projectId": "",                 // project 档才有值
          "projectCode": "",               // 暂未回填（恒空）
          "description": "",               // 用途说明占位，恒空，待人工/AI 回填
          "fileCount": 108,
          "updatedAt": "2026-06-18 04:57:22",
          "files": [                       // 文件清单
            {
              "id": "RAW-0248",
              "name": "概述.docx",
              "path": "技术标/标准文件/EW5.0-220/.../概述.docx",  // 完整路径
              "ext": "docx",
              "cleanStatus": "cleaned"     // cleaned|pending|original_only|failed
            }
          ]
        }
      ]
    }
    // tier=customer / tier=project 同构
  ]
}
```

### 字段速查

- 顶层：`bidType` / `schemaVersion` / `generatedAt` / `stats` / `tiers[]`
- tier：`name` / `tier` / `path` / `fileCount` / `folders[]`
- folder（3 级）：`name` / `path` / `tier` / `customerName` / `customerId` / `projectId` / `projectCode` / `description` / `fileCount` / `updatedAt` / `files[]`
- file：`id`(RAW-NNNN) / `name` / `path`(完整) / `ext` / `cleanStatus`

## 4. 三个档位（tier）的语义 ⚠️ 重要

技术标 2 级目录的**真实命名**（线上库）与一般直觉不同，下游务必以 `tier` 字段（已归一）为准，不要靠目录中文名硬判：

| 2 级目录真实名 | `tier` 值 | 含义 | 3 级目录名的含义 |
|----------------|-----------|------|------------------|
| `标准文件` | `standard` | 通用/平台标准素材（如机型 EW5.0-220） | 机型号或分类 |
| `客户定制` | `customer` | 按客户区分的素材 | **客户名**（已回填到 `customerName`） |
| `项目定制` | `project`  | 按项目区分的素材 | **项目标识**（已回填到 `projectId`） |

- **判档请读 `tier` 字段**，它已由后端用 `normalize_material_tier()` 归一，覆盖了"标准文件/客户定制/项目定制"以及历史别名"通用素材/客户素材/项目素材"等多套命名。
- customer 档的 3 级目录 → `customerName` 有值；project 档的 3 级目录 → `projectId` 有值。

## 5. 当前已知约束（下游需注意）

- `description`、`customerId`、`projectCode` 三个字段**目前恒为空字符串**（占位，待后续人工或 AI 回填）。下游不要依赖它们有值；需要客户/项目身份时用 `customerName` / `projectId`。
- **深层文件归并**：4 级及更深目录里的文件，会被归并到其所属的 **3 级祖先目录** 的 `files[]` 下（符合"3 级为基准"），但每个 file 的 `path` 保留**完整原始路径**，不丢深层信息。需要还原原始层级时解析 `file.path` 即可。
- 直接挂在 2 级目录下（没有 3 级祖先）的散落文件**不会**出现在任何 folder 的 `files[]` 里，也不计入 `fileCount`。
- `stats.fileCount` = 所有 3 级目录文件数之和（即已归并的有效文件），不含上述散落文件。

## 6. 新鲜度与刷新

- 后端钩子在每次结构变更后**同步重建**，正常情况下 `generatedAt` 接近最新。
- 若怀疑过期或文件不存在，调 `GET /api/technical/materials/index` 会触发即时重建并返回最新结果（这是获取"保证最新"快照的标准做法）。

## 7. 最小读取示例

```python
import json, urllib.request

# 方式 A：经接口（保证最新）
data = json.load(urllib.request.urlopen("http://localhost/api/technical/materials/index"))

# 方式 B：直接读文件（容器内 / docker cp 出来后）
# data = json.load(open("technical_material_index.json", encoding="utf-8"))

for tier in data["tiers"]:
    print(tier["tier"], tier["name"], tier["fileCount"])
    for folder in tier["folders"]:
        ident = folder["customerName"] or folder["projectId"] or ""
        print("  ", folder["name"], ident, folder["fileCount"], "files")
        # 需要文件级信息时遍历 folder["files"]，用 f["path"] 还原完整层级
```

## 8. 相关代码（如需改动生成侧）

- 生成/读取：`sewpg-bid-backend/app/services/technical_material_index.py`
- 自动钩子：`sewpg-bid-backend/app/services/technical_material_store.py`（`_refresh_index` 包裹各改结构方法）
- 路由：`sewpg-bid-backend/app/api/routes/technical.py`（`GET /api/technical/materials/index`）
- 测试：`sewpg-bid-backend/tests/test_technical_material_index.py`

> 后端源码烧进 Docker 镜像（非 bind-mount），改动后需 `docker compose build fastapi worker && docker compose up -d fastapi worker` 才生效。
