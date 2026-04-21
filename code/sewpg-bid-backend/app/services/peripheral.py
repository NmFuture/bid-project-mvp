from __future__ import annotations

import copy
import itertools
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any


class PeripheralError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.extra = extra or {}

    def to_payload(self) -> dict[str, Any]:
        payload = {"detail": self.detail, "code": self.code}
        payload.update(self.extra)
        return payload


def now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_day() -> str:
    return datetime.now().strftime("%Y%m%d")


def size_label(size: Any) -> str:
    value = int(size or 0)
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    if value < 1024 * 1024 * 1024:
        return f"{value / 1024 / 1024:.2f} MB"
    return f"{value / 1024 / 1024 / 1024:.2f} GB"


def ext_of(name: str) -> str:
    suffix = PurePosixPath(name).suffix.lower().lstrip(".")
    return suffix or "file"


def safe_segment(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


class PeripheralStore:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._id_counter = itertools.count(1)
        self._raw_base_paths = {
            "标准模板/技术标",
            "标准模板/商务标",
            "客户定制/华能集团/通用材料",
            "客户定制/大唐集团/通用材料",
            "项目定制/PRJ-0001/技术标",
            "项目定制/PRJ-0001/商务标",
        }
        self._raw_custom_folders: set[str] = set()
        self._raw_files = [
            self._make_raw_file(
                name="技术标模板.docx",
                folder_path="标准模板/技术标",
                size=156_000,
                bid_type="技术标",
                project_id="",
                customer_name="平台标准",
                version=1,
                last_action="upload",
                last_operator="系统初始化",
            ),
            self._make_raw_file(
                name="风机参数表.xlsx",
                folder_path="客户定制/华能集团/通用材料",
                size=86_000,
                bid_type="通用",
                project_id="",
                customer_name="华能集团",
                version=2,
                last_action="version",
                last_operator="王磊",
            ),
            self._make_raw_file(
                name="测风塔原始数据.zip",
                folder_path="项目定制/PRJ-0001/技术标",
                size=8_600_000,
                bid_type="技术标",
                project_id="PRJ-0001",
                customer_name="测试业主",
                version=1,
                last_action="upload",
                last_operator="李工",
            ),
        ]

        self._structured_items = [
            {
                "id": "MAT-001",
                "name": "风机性能保证值",
                "type": "结构化表格",
                "icon": "table_chart",
                "version": "2026.04",
                "updatedAt": now_display(),
                "tableKey": "performance_guarantee",
                "tableLabel": "性能保证",
            },
            {
                "id": "MAT-002",
                "name": "项目业绩清单",
                "type": "结构化表格",
                "icon": "dataset",
                "version": "2026.04",
                "updatedAt": now_display(),
                "tableKey": "project_reference",
                "tableLabel": "项目业绩",
            },
        ]
        self._structured_table_options = [
            {"key": "performance_guarantee", "label": "性能保证"},
            {"key": "project_reference", "label": "项目业绩"},
        ]
        self._structured_import_history: list[dict[str, Any]] = []
        self._structured_latest_receipt: dict[str, Any] | None = None

        self._wiki_tag_options = ["风资源", "技术标", "商务标", "通用材料"]
        self._wiki_type_options = ["技术标", "商务标", "通用"]
        self._wiki_tree = [
            {
                "id": "wiki-root-1",
                "title": "风资源",
                "icon": "folder",
                "expanded": True,
                "children": [
                    {
                        "id": "wiki-node-1",
                        "title": "测风塔布设说明",
                        "icon": "article",
                    }
                ],
            },
            {
                "id": "wiki-root-2",
                "title": "机组选型",
                "icon": "folder",
                "expanded": True,
                "children": [],
            },
        ]
        self._wiki_nodes = {
            "wiki-node-1": {
                "id": "wiki-node-1",
                "title": "测风塔布设说明",
                "markdownContent": "# 测风塔布设说明\n\n用于支撑风资源章节的测风布点说明。",
                "aiSummary": "包含测风塔布设原则、数量与位置说明。",
                "tags": ["风资源", "技术标"],
                "applicableTypes": ["技术标"],
                "attachments": [],
            }
        }
        self._wiki_selected_id = "wiki-node-1"

        self._users = [
            {
                "id": "U-001",
                "name": "当前用户",
                "email": "current.user@example.com",
                "dept": "解决方案部",
                "roles": ["管理员", "标书经理"],
                "status": "active",
            },
            {
                "id": "U-002",
                "name": "李工",
                "email": "li.gong@example.com",
                "dept": "技术中心",
                "roles": ["技术标编辑"],
                "status": "active",
            },
        ]
        self._gateway = {
            "enabled": True,
            "endpoint": "https://gateway.example.com/v1/chat/completions",
            "model": "gpt-5.4",
            "timeoutMs": 30000,
            "maxTokens": 4096,
            "apiKeyMasked": "sk-****demo",
            "updatedAt": now_display(),
            "updatedBy": "系统初始化",
        }
        self._dotx_templates = [
            {
                "id": "DOTX-001",
                "name": "标准技术标模板.dotx",
                "version": "2026.04",
                "uploadedBy": "系统初始化",
                "uploadedAt": now_display(),
                "size": size_label(180_000),
                "isActive": True,
            }
        ]
        self._excel_templates = [
            {
                "id": "XLSX-001",
                "tableKey": "performance_guarantee",
                "tableLabel": "性能保证",
                "version": "2026.04",
                "uploadedBy": "系统初始化",
                "uploadedAt": now_display(),
                "fileName": "性能保证模板.xlsx",
                "isActive": True,
            }
        ]
        self._backups = [
            {
                "id": "BKP-001",
                "type": "manual",
                "status": "success",
                "size": "2.6 GB",
                "createdAt": now_display(),
                "createdBy": "系统初始化",
                "note": "初始联调快照",
                "restoredAt": "",
            }
        ]
        self._health = [
            {
                "id": "svc-fastapi",
                "name": "FastAPI 业务后端",
                "status": "online",
                "uptime": "99.9%",
                "latency": "32ms",
                "detail": "当前使用正式后端承接主链路与外围模块。",
            },
            {
                "id": "svc-opencode",
                "name": "opencode 服务",
                "status": "online",
                "uptime": "99.5%",
                "latency": "138ms",
                "detail": "目录生成与初稿生成接口可用。",
            },
            {
                "id": "svc-onlyoffice",
                "name": "OnlyOffice 文档服务",
                "status": "online",
                "uptime": "99.2%",
                "latency": "74ms",
                "detail": "在线编辑与回写链路已接通。",
            },
        ]
        self._audit_logs = [
            self._make_audit_log(
                action="生成目录",
                action_type="generate",
                module_id="outline",
                module_label="目录生成",
                target="PRJ-0001 / S2",
                status="成功",
                user="系统初始化",
                diff={"before": {"status": "pending"}, "after": {"status": "completed"}},
            )
        ]

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._id_counter):04d}"

    def _make_raw_file(
        self,
        *,
        name: str,
        folder_path: str,
        size: int,
        bid_type: str,
        project_id: str,
        customer_name: str,
        version: int,
        last_action: str,
        last_operator: str,
    ) -> dict[str, Any]:
        return {
            "id": self._next_id("RAW"),
            "name": name,
            "folderPath": folder_path,
            "ext": ext_of(name),
            "type": ext_of(name),
            "size": size,
            "sizeLabel": size_label(size),
            "bidType": bid_type,
            "projectId": project_id,
            "customerName": customer_name,
            "version": version,
            "lastAction": last_action,
            "lastOperator": last_operator,
            "updatedAt": now_display(),
        }

    def _make_audit_log(
        self,
        *,
        action: str,
        action_type: str,
        module_id: str,
        module_label: str,
        target: str,
        status: str,
        user: str,
        diff: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": self._next_id("AUD"),
            "time": now_display(),
            "user": user,
            "userAvatar": user[:1] or "人",
            "action": action,
            "actionType": action_type,
            "module": module_id,
            "moduleLabel": module_label,
            "target": target,
            "status": status,
            "diff": diff or {"before": {}, "after": {}},
        }

    def _push_audit(
        self,
        *,
        action: str,
        action_type: str,
        module_id: str,
        module_label: str,
        target: str,
        status: str = "成功",
        user: str = "当前用户",
        diff: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = self._make_audit_log(
            action=action,
            action_type=action_type,
            module_id=module_id,
            module_label=module_label,
            target=target,
            status=status,
            user=user,
            diff=diff,
        )
        self._audit_logs.insert(0, item)
        return item

    def _all_folder_paths(self) -> set[str]:
        paths = set(self._raw_base_paths) | set(self._raw_custom_folders)
        for item in self._raw_files:
            path = str(item.get("folderPath") or "").strip("/")
            if path:
                paths.add(path)
        return paths

    def _ensure_folder(self, path: str) -> str:
        normalized = str(path or "").strip().strip("/")
        if not normalized:
            raise PeripheralError(400, "目标目录不能为空。", "RAW_TARGET_PATH_REQUIRED")
        all_paths = self._all_folder_paths()
        if normalized not in all_paths:
            self._raw_custom_folders.add(normalized)
        return normalized

    def _folder_tree(self) -> list[dict[str, Any]]:
        tree: dict[str, Any] = {}

        def ensure_node(parts: list[str]) -> dict[str, Any]:
            cursor = tree
            current_path_parts: list[str] = []
            node_ref = {}
            for part in parts:
                current_path_parts.append(part)
                cursor.setdefault(part, {"name": part, "path": "/".join(current_path_parts), "children": {}})
                node_ref = cursor[part]
                cursor = node_ref["children"]
            return node_ref

        for folder_path in sorted(self._all_folder_paths()):
            ensure_node(folder_path.split("/"))

        direct_counts: dict[str, int] = {}
        for item in self._raw_files:
            folder_path = str(item.get("folderPath") or "")
            direct_counts[folder_path] = direct_counts.get(folder_path, 0) + 1

        def build(children: dict[str, Any]) -> list[dict[str, Any]]:
            result = []
            for key in sorted(children.keys()):
                node = children[key]
                child_nodes = build(node["children"])
                nested_count = sum(int(child.get("fileCount") or 0) for child in child_nodes)
                current_count = direct_counts.get(node["path"], 0)
                result.append(
                    {
                        "id": node["path"],
                        "name": node["name"],
                        "path": node["path"],
                        "fileCount": current_count + nested_count,
                        "children": child_nodes,
                    }
                )
            return result

        return build(tree)

    def raw_permissions(self, role: str = "member") -> dict[str, Any]:
        normalized = "admin" if role == "admin" else "member"
        editable_actions = {"upload": True, "rename": True, "move": True, "delete": True}
        return {
            "role": normalized,
            "rules": [
                {"pathPrefix": "标准模板", "actions": editable_actions},
                {"pathPrefix": "客户定制/*/通用材料", "actions": editable_actions},
                {"pathPrefix": "项目定制", "actions": editable_actions},
            ],
        }

    def raw_tree(self) -> dict[str, Any]:
        return {"tree": self._folder_tree(), "updatedAt": now_display()}

    def raw_files(
        self,
        *,
        folder_path: str = "",
        project_id: str = "",
        customer_name: str = "",
        bid_type: str = "",
        keyword: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        items = list(self._raw_files)
        if folder_path:
            items = [item for item in items if item["folderPath"] == folder_path]
        if project_id:
            items = [item for item in items if item.get("projectId") == project_id]
        if customer_name:
            items = [item for item in items if customer_name in str(item.get("customerName") or "")]
        if bid_type:
            items = [item for item in items if item.get("bidType") == bid_type]
        if keyword:
            items = [item for item in items if keyword in item["name"] or keyword in item["folderPath"]]

        items.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        return {
            "items": copy.deepcopy(items[start:end]),
            "total": len(items),
            "page": page,
            "pageSize": page_size,
        }

    def raw_bootstrap_folders(self, project_id: str, bid_type: str = "技术标") -> dict[str, Any]:
        clean_id = safe_segment(project_id, "")
        if not clean_id:
            raise PeripheralError(400, "projectId 不能为空。", "PROJECT_ID_REQUIRED")
        root_path = f"项目定制/{clean_id}/{bid_type or '技术标'}"
        self._raw_custom_folders.add(root_path)
        return {
            "message": "项目目录骨架初始化完成。",
            "payload": {
                "projectId": clean_id,
                "path": root_path,
            },
        }

    def raw_create_folder(self, parent_path: str, folder_name: str) -> dict[str, Any]:
        name = safe_segment(folder_name, "")
        if not name:
            raise PeripheralError(400, "文件夹名称不能为空。", "RAW_FOLDER_NAME_REQUIRED")
        full_path = "/".join([part for part in [parent_path.strip("/"), name] if part])
        if full_path in self._all_folder_paths():
            raise PeripheralError(409, "目录已存在。", "RAW_FOLDER_EXISTS")
        self._raw_custom_folders.add(full_path)
        self._push_audit(
            action="创建目录",
            action_type="update",
            module_id="materials_raw",
            module_label="原始材料库",
            target=full_path,
        )
        return {
            "message": "文件夹创建成功。",
            "folderPath": full_path,
            "tree": self._folder_tree(),
        }

    def raw_delete_folder(self, path: str) -> dict[str, Any]:
        folder_path = str(path or "").strip().strip("/")
        if not folder_path:
            raise PeripheralError(400, "path 不能为空。", "RAW_FOLDER_PATH_REQUIRED")
        if folder_path not in self._all_folder_paths():
            raise PeripheralError(404, "目录不存在。", "RAW_FOLDER_NOT_FOUND")
        if any(item["folderPath"] == folder_path or item["folderPath"].startswith(f"{folder_path}/") for item in self._raw_files):
            raise PeripheralError(400, "目录下仍有文件，请先移除或迁移文件后再删除。", "RAW_FOLDER_NOT_EMPTY")
        self._raw_custom_folders.discard(folder_path)
        self._push_audit(
            action="删除目录",
            action_type="delete",
            module_id="materials_raw",
            module_label="原始材料库",
            target=folder_path,
        )
        return {"message": "文件夹删除成功。", "folderPath": folder_path, "tree": self._folder_tree()}

    def _resolve_file_conflict(self, folder_path: str, file_name: str, on_conflict: str) -> tuple[str, dict[str, Any] | None]:
        existing = next(
            (item for item in self._raw_files if item["folderPath"] == folder_path and item["name"] == file_name),
            None,
        )
        if not existing:
            return "create", None
        if on_conflict == "overwrite":
            return "overwrite", existing
        if on_conflict == "version":
            return "version", existing
        raise PeripheralError(
            409,
            "目标路径存在同名文件",
            "MATERIAL_CONFLICT",
            {
                "conflict": {
                    "path": folder_path,
                    "existingFileId": existing["id"],
                    "existingFileName": existing["name"],
                    "allowedActions": ["overwrite", "version"],
                }
            },
        )

    def raw_upload(
        self,
        *,
        target_path: str = "",
        project_id: str = "",
        bid_type: str = "技术标",
        on_conflict: str = "",
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        file_inputs = list(files or [])
        if not file_inputs:
            raise PeripheralError(400, "请至少上传一个文件。", "RAW_UPLOAD_FILES_REQUIRED")
        if not target_path:
            if not project_id:
                raise PeripheralError(400, "请提供目标目录或项目 ID。", "RAW_TARGET_PATH_REQUIRED")
            target_path = f"项目定制/{safe_segment(project_id, 'PRJ-UNSET')}/{bid_type or '技术标'}"
        folder_path = self._ensure_folder(target_path)

        uploaded_items: list[dict[str, Any]] = []
        for item in file_inputs:
            file_name = str(item.get("name") or "").strip()
            if not file_name:
                raise PeripheralError(400, "文件名不能为空。", "RAW_FILE_NAME_REQUIRED")
            action, existing = self._resolve_file_conflict(folder_path, file_name, on_conflict)
            if action == "overwrite" and existing is not None:
                existing["size"] = int(item.get("size") or existing["size"])
                existing["sizeLabel"] = size_label(existing["size"])
                existing["updatedAt"] = now_display()
                existing["lastAction"] = "overwrite"
                existing["lastOperator"] = "当前用户"
                uploaded_items.append(copy.deepcopy(existing))
                continue

            next_name = file_name
            next_version = 1
            if action == "version" and existing is not None:
                next_version = int(existing.get("version") or 1) + 1
                stem = PurePosixPath(file_name).stem
                suffix = PurePosixPath(file_name).suffix
                next_name = f"{stem}_v{next_version}{suffix}"

            record = self._make_raw_file(
                name=next_name,
                folder_path=folder_path,
                size=int(item.get("size") or 0),
                bid_type=bid_type or "技术标",
                project_id=project_id,
                customer_name="测试业主" if project_id else "通用",
                version=next_version,
                last_action="upload" if action == "create" else "version",
                last_operator="当前用户",
            )
            self._raw_files.insert(0, record)
            uploaded_items.append(copy.deepcopy(record))

        self._push_audit(
            action="上传材料",
            action_type="import",
            module_id="materials_raw",
            module_label="原始材料库",
            target=folder_path,
            diff={"before": {"count": len(self._raw_files) - len(uploaded_items)}, "after": {"count": len(self._raw_files)}},
        )
        return {
            "message": f"上传完成，共处理 {len(uploaded_items)} 个文件。",
            "items": uploaded_items,
        }

    def raw_update_file(self, file_id: str, name: str) -> dict[str, Any]:
        item = next((entry for entry in self._raw_files if entry["id"] == file_id), None)
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        next_name = str(name or "").strip()
        if not next_name:
            raise PeripheralError(400, "文件名不能为空。", "RAW_FILE_NAME_REQUIRED")
        conflict = next(
            (entry for entry in self._raw_files if entry["id"] != file_id and entry["folderPath"] == item["folderPath"] and entry["name"] == next_name),
            None,
        )
        if conflict is not None:
            raise PeripheralError(
                409,
                "目标路径存在同名文件",
                "MATERIAL_CONFLICT",
                {
                    "conflict": {
                        "path": item["folderPath"],
                        "existingFileId": conflict["id"],
                        "existingFileName": conflict["name"],
                        "allowedActions": ["overwrite", "version"],
                    }
                },
            )
        before = {"name": item["name"]}
        item["name"] = next_name
        item["ext"] = ext_of(next_name)
        item["type"] = ext_of(next_name)
        item["updatedAt"] = now_display()
        item["lastAction"] = "rename"
        self._push_audit(
            action="重命名材料",
            action_type="update",
            module_id="materials_raw",
            module_label="原始材料库",
            target=next_name,
            diff={"before": before, "after": {"name": next_name}},
        )
        return {"message": "重命名成功", "item": copy.deepcopy(item)}

    def raw_move_file(self, file_id: str, target_path: str, on_conflict: str = "") -> dict[str, Any]:
        item = next((entry for entry in self._raw_files if entry["id"] == file_id), None)
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        destination = self._ensure_folder(target_path)
        action, existing = self._resolve_file_conflict(destination, item["name"], on_conflict)
        if action == "overwrite" and existing is not None:
            self._raw_files = [entry for entry in self._raw_files if entry["id"] != file_id]
            existing["size"] = item["size"]
            existing["sizeLabel"] = item["sizeLabel"]
            existing["updatedAt"] = now_display()
            existing["lastAction"] = "overwrite"
            result = existing
        else:
            before = {"folderPath": item["folderPath"], "name": item["name"]}
            item["folderPath"] = destination
            item["updatedAt"] = now_display()
            item["lastAction"] = "move"
            if action == "version" and existing is not None:
                version = int(existing.get("version") or 1) + 1
                stem = PurePosixPath(item["name"]).stem
                suffix = PurePosixPath(item["name"]).suffix
                item["name"] = f"{stem}_v{version}{suffix}"
                item["version"] = version
                item["lastAction"] = "version"
            self._push_audit(
                action="移动材料",
                action_type="update",
                module_id="materials_raw",
                module_label="原始材料库",
                target=item["name"],
                diff={"before": before, "after": {"folderPath": item["folderPath"], "name": item["name"]}},
            )
            result = item
        return {"message": "移动成功", "item": copy.deepcopy(result)}

    def raw_delete_file(self, file_id: str) -> dict[str, Any]:
        for index, item in enumerate(self._raw_files):
            if item["id"] == file_id:
                removed = self._raw_files.pop(index)
                self._push_audit(
                    action="删除材料",
                    action_type="delete",
                    module_id="materials_raw",
                    module_label="原始材料库",
                    target=removed["name"],
                )
                return {"message": "删除成功", "item": copy.deepcopy(removed)}
        raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")

    def raw_download_file(self, file_id: str) -> dict[str, Any]:
        item = next((entry for entry in self._raw_files if entry["id"] == file_id), None)
        if item is None:
            raise PeripheralError(404, "文件不存在。", "RAW_FILE_NOT_FOUND")
        return {
            "fileId": item["id"],
            "fileName": item["name"],
            "downloadUrl": f"/downloads/{item['name']}",
            "message": "已生成下载地址",
        }

    def structured_list(self, table: str = "all") -> dict[str, Any]:
        items = list(self._structured_items)
        if table and table != "all":
            items = [item for item in items if item.get("tableKey") == table]
        return {
            "items": copy.deepcopy(items),
            "total": len(items),
            "tableOptions": copy.deepcopy(self._structured_table_options),
            "importHistory": copy.deepcopy(self._structured_import_history),
            "latestReceipt": copy.deepcopy(self._structured_latest_receipt),
        }

    def structured_template(self, table: str = "") -> dict[str, Any]:
        matched = next((item for item in self._structured_table_options if item["key"] == table), self._structured_table_options[0])
        return {
            "table": matched,
            "fileName": f"{matched['label']}_导入模板.xlsx",
            "templateVersion": "2026.04",
            "requiredFields": ["名称", "值"],
            "optionalFields": ["备注"],
            "templateColumns": ["名称", "值", "备注"],
            "sampleRows": [{"名称": "样例", "值": "示例", "备注": "可选"}],
            "notes": ["请勿修改首行字段名。", "可保留可选字段为空。"],
        }

    def structured_preview_import(self, table: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        template = self.structured_template(table)
        return {
            "table": template["table"],
            "file": {"name": str((payload or {}).get("fileName") or "待导入模板.xlsx")},
            "summary": {"totalRows": 2, "successCount": 2, "failCount": 0},
            "mapping": {"名称": "name", "值": "value", "备注": "remark"},
            "previewRows": [{"name": "样例A", "value": "值A", "remark": ""}, {"name": "样例B", "value": "值B", "remark": "备注"}],
            "errors": [],
            "canImport": True,
        }

    def structured_confirm_import(self, table: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        preview = self.structured_preview_import(table, payload)
        receipt = {
            "importId": self._next_id("IMP"),
            "snapshotId": self._next_id("SNAP"),
            "table": preview["table"],
            "fileName": preview["file"]["name"],
            "totalRows": preview["summary"]["totalRows"],
            "successCount": preview["summary"]["successCount"],
            "failCount": preview["summary"]["failCount"],
            "version": "2026.04",
            "operator": "当前用户",
            "importedAt": now_display(),
            "errors": [],
        }
        history = {
            "id": receipt["importId"],
            "status": "success",
            "desc": f"当前用户 导入{receipt['table']['label']} {receipt['successCount']} 行",
            "time": now_display(),
            "tableKey": receipt["table"]["key"],
            "tableLabel": receipt["table"]["label"],
            "successCount": receipt["successCount"],
            "failCount": receipt["failCount"],
            "errors": [],
        }
        self._structured_import_history.insert(0, history)
        self._structured_latest_receipt = receipt
        self._push_audit(
            action="导入结构化素材",
            action_type="import",
            module_id="materials_structured",
            module_label="结构化素材库",
            target=receipt["fileName"],
        )
        return {"message": "Imported", "receipt": copy.deepcopy(receipt), "historyItem": copy.deepcopy(history)}

    def structured_create(self, data: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": self._next_id("MAT"),
            "name": str(data.get("name") or "新建素材"),
            "type": str(data.get("type") or "结构化表格"),
            "icon": str(data.get("icon") or "table_chart"),
            "version": str(data.get("version") or "2026.04"),
            "updatedAt": now_display(),
            "tableKey": str(data.get("tableKey") or "performance_guarantee"),
            "tableLabel": str(data.get("tableLabel") or "性能保证"),
        }
        self._structured_items.insert(0, item)
        return copy.deepcopy(item)

    def structured_update(self, item_id: str, data: dict[str, Any]) -> dict[str, Any]:
        item = next((entry for entry in self._structured_items if entry["id"] == item_id), None)
        if item is None:
            raise PeripheralError(404, "素材不存在。", "STRUCTURED_MATERIAL_NOT_FOUND")
        item.update({k: v for k, v in data.items() if k in {"name", "type", "icon", "version"}})
        item["updatedAt"] = now_display()
        return {"message": "Updated", "item": copy.deepcopy(item)}

    def structured_delete(self, item_id: str) -> dict[str, Any]:
        before = len(self._structured_items)
        self._structured_items = [entry for entry in self._structured_items if entry["id"] != item_id]
        if len(self._structured_items) == before:
            raise PeripheralError(404, "素材不存在。", "STRUCTURED_MATERIAL_NOT_FOUND")
        return {"message": "Deleted"}

    def structured_import_excel(self) -> dict[str, Any]:
        return {"imported": 12, "failed": 0}

    def _find_wiki_tree_node(
        self,
        nodes: list[dict[str, Any]],
        node_id: str,
        parent: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, int] | None:
        for index, node in enumerate(nodes):
            if node["id"] == node_id:
                return node, parent, index
            children = node.get("children") or []
            if children:
                found = self._find_wiki_tree_node(children, node_id, node)
                if found is not None:
                    return found
        return None

    def _wiki_path(self, node_id: str) -> list[str]:
        path: list[str] = []

        def walk(nodes: list[dict[str, Any]], trail: list[str]) -> bool:
            for node in nodes:
                current = [*trail, node["title"]]
                if node["id"] == node_id:
                    path[:] = current
                    return True
                children = node.get("children") or []
                if children and walk(children, current):
                    return True
            return False

        walk(self._wiki_tree, [])
        return path

    def _wiki_payload(self, node_id: str = "") -> dict[str, Any]:
        selected_id = node_id or self._wiki_selected_id
        selected = copy.deepcopy(self._wiki_nodes.get(selected_id))
        if selected is not None:
            path = self._wiki_path(selected_id)
            selected["path"] = path
            selected["pathText"] = " / ".join(path)
        return {
            "tree": copy.deepcopy(self._wiki_tree),
            "selectedNode": selected,
            "tagOptions": copy.deepcopy(self._wiki_tag_options),
            "applicableTypeOptions": copy.deepcopy(self._wiki_type_options),
        }

    def wiki_list(self, node_id: str = "") -> dict[str, Any]:
        return self._wiki_payload(node_id)

    def wiki_create(self, parent_id: str, title: str, is_folder: bool) -> dict[str, Any]:
        new_id = self._next_id("WIKI")
        tree_node = {
            "id": new_id,
            "title": title.strip() or ("新建目录" if is_folder else "新建节点"),
            "icon": "folder" if is_folder else "article",
            "expanded": True if is_folder else None,
            "children": [] if is_folder else None,
        }
        if parent_id:
            found = self._find_wiki_tree_node(self._wiki_tree, parent_id)
            if found is not None:
                parent_node = found[0]
                parent_node.setdefault("children", [])
                parent_node["icon"] = "folder"
                parent_node["expanded"] = True
                parent_node["children"].append(tree_node)
            else:
                self._wiki_tree.append(tree_node)
        else:
            self._wiki_tree.append(tree_node)
        self._wiki_nodes[new_id] = {
            "id": new_id,
            "title": tree_node["title"],
            "markdownContent": f"# {tree_node['title']}\n\n请在此补充节点内容。",
            "aiSummary": "新建节点，尚未生成摘要。",
            "tags": [],
            "applicableTypes": ["通用"],
            "attachments": [],
        }
        self._wiki_selected_id = new_id
        self._push_audit(
            action="创建 Wiki 节点",
            action_type="update",
            module_id="materials_wiki",
            module_label="Wiki 素材库",
            target=tree_node["title"],
        )
        return {"message": "Created", **self._wiki_payload(new_id)}

    def wiki_update(self, node_id: str, data: dict[str, Any]) -> dict[str, Any]:
        node = self._wiki_nodes.get(node_id)
        if node is None:
            raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")
        before = copy.deepcopy(node)
        node["title"] = str(data.get("title") or node["title"]).strip() or node["title"]
        node["markdownContent"] = str(data.get("markdownContent") or node["markdownContent"])
        node["tags"] = list(data.get("tags") or node.get("tags") or [])
        node["applicableTypes"] = list(data.get("applicableTypes") or node.get("applicableTypes") or [])
        found = self._find_wiki_tree_node(self._wiki_tree, node_id)
        if found is not None:
            found[0]["title"] = node["title"]
        self._wiki_selected_id = node_id
        self._push_audit(
            action="更新 Wiki 节点",
            action_type="update",
            module_id="materials_wiki",
            module_label="Wiki 素材库",
            target=node["title"],
            diff={"before": {"title": before["title"]}, "after": {"title": node["title"]}},
        )
        return {"message": "Updated", **self._wiki_payload(node_id)}

    def wiki_move(self, node_id: str, target_id: str, mode: str) -> dict[str, Any]:
        source = self._find_wiki_tree_node(self._wiki_tree, node_id)
        target = self._find_wiki_tree_node(self._wiki_tree, target_id)
        if source is None or target is None:
            raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")
        source_node, source_parent, source_index = source
        target_node, target_parent, target_index = target
        source_list = source_parent["children"] if source_parent else self._wiki_tree
        moved = source_list.pop(source_index)
        if mode == "inside":
            target_node.setdefault("children", [])
            target_node["children"].append(moved)
            target_node["icon"] = "folder"
            target_node["expanded"] = True
        else:
            target_list = target_parent["children"] if target_parent else self._wiki_tree
            target_list.insert(target_index, moved)
        self._wiki_selected_id = node_id
        self._push_audit(
            action="移动 Wiki 节点",
            action_type="update",
            module_id="materials_wiki",
            module_label="Wiki 素材库",
            target=self._wiki_nodes[node_id]["title"],
        )
        return {"message": "Moved", **self._wiki_payload(node_id)}

    def wiki_upload_attachment(self, node_id: str, file_name: str, file_size: Any) -> dict[str, Any]:
        node = self._wiki_nodes.get(node_id)
        if node is None:
            raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")
        if not str(file_name or "").strip():
            raise PeripheralError(400, "附件名称不能为空。", "WIKI_ATTACHMENT_NAME_REQUIRED")
        attachment = {
            "id": self._next_id("ATT"),
            "name": str(file_name).strip(),
            "size": size_label(file_size),
            "time": now_display(),
            "downloadUrl": f"/wiki/attachments/{file_name}",
        }
        node.setdefault("attachments", [])
        node["attachments"].insert(0, attachment)
        self._wiki_selected_id = node_id
        return {"message": "Uploaded", "attachment": copy.deepcopy(attachment), **self._wiki_payload(node_id)}

    def wiki_refresh_summary(self, node_id: str) -> dict[str, Any]:
        node = self._wiki_nodes.get(node_id)
        if node is None:
            raise PeripheralError(404, "Wiki 节点不存在。", "WIKI_NODE_NOT_FOUND")
        text = node.get("markdownContent") or ""
        summary = re.sub(r"\s+", " ", text.replace("#", "")).strip()
        node["aiSummary"] = summary[:80] or "暂无摘要。"
        self._wiki_selected_id = node_id
        return {"summary": node["aiSummary"], **self._wiki_payload(node_id)}

    def audit_list(self, filters: dict[str, Any]) -> dict[str, Any]:
        items = list(self._audit_logs)
        keyword = str(filters.get("keyword") or "").strip()
        user = str(filters.get("user") or "").strip()
        module = str(filters.get("module") or "").strip()
        action = str(filters.get("action") or "").strip()
        status = str(filters.get("status") or "").strip()
        start_date = str(filters.get("startDate") or "").strip()
        end_date = str(filters.get("endDate") or "").strip()

        def matched(item: dict[str, Any]) -> bool:
            if keyword and keyword not in f"{item['user']} {item['action']} {item['target']}":
                return False
            if user and item["user"] != user:
                return False
            if module and item["module"] != module:
                return False
            if action and item["actionType"] != action:
                return False
            if status and item["status"] != status:
                return False
            if start_date and str(item["time"])[:10] < start_date:
                return False
            if end_date and str(item["time"])[:10] > end_date:
                return False
            return True

        filtered = [copy.deepcopy(item) for item in items if matched(item)]
        return {
            "items": filtered,
            "total": len(filtered),
            "page": 1,
            "pageSize": 20,
            "filterOptions": {
                "users": sorted({item["user"] for item in items}),
                "modules": sorted(
                    [{"id": item["module"], "label": item["moduleLabel"]} for item in items],
                    key=lambda item: item["label"],
                ),
                "actions": sorted(
                    [{"id": item["actionType"], "label": item["action"]} for item in items],
                    key=lambda item: item["label"],
                ),
                "statuses": sorted({item["status"] for item in items}),
            },
        }

    def audit_export(self, filters: dict[str, Any]) -> dict[str, Any]:
        data = self.audit_list(filters)
        return {
            "fileName": f"audit_{now_day()}.csv",
            "items": data["items"],
        }

    def audit_detail(self, audit_id: str) -> dict[str, Any]:
        item = next((entry for entry in self._audit_logs if entry["id"] == audit_id), None)
        if item is None:
            raise PeripheralError(404, "审计日志不存在。", "AUDIT_NOT_FOUND")
        payload = copy.deepcopy(item)
        payload["summary"] = f"{payload['action']} - {payload['target']}"
        return payload

    def settings_users(self) -> dict[str, Any]:
        return {"items": copy.deepcopy(self._users), "total": len(self._users)}

    def settings_create_user(self, data: dict[str, Any]) -> dict[str, Any]:
        user = {
            "id": self._next_id("U"),
            "name": str(data.get("name") or "新用户"),
            "email": str(data.get("email") or ""),
            "dept": str(data.get("dept") or "未分配"),
            "roles": list(data.get("roles") or []),
            "status": str(data.get("status") or "active"),
        }
        self._users.append(user)
        return copy.deepcopy(user)

    def settings_update_user(self, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
        user = next((entry for entry in self._users if entry["id"] == user_id), None)
        if user is None:
            raise PeripheralError(404, "用户不存在。", "USER_NOT_FOUND")
        user.update({k: v for k, v in data.items() if k in {"name", "email", "dept", "roles", "status"}})
        return {"message": "Updated", "item": copy.deepcopy(user)}

    def settings_gateway_get(self) -> dict[str, Any]:
        return copy.deepcopy(self._gateway)

    def settings_gateway_update(self, data: dict[str, Any]) -> dict[str, Any]:
        self._gateway.update(
            {
                "enabled": bool(data.get("enabled", self._gateway["enabled"])),
                "endpoint": str(data.get("endpoint") or self._gateway["endpoint"]),
                "model": str(data.get("model") or self._gateway["model"]),
                "timeoutMs": int(data.get("timeoutMs") or self._gateway["timeoutMs"]),
                "maxTokens": int(data.get("maxTokens") or self._gateway["maxTokens"]),
                "updatedAt": now_display(),
                "updatedBy": "当前用户",
            }
        )
        self._push_audit(
            action="更新网关配置",
            action_type="config",
            module_id="settings",
            module_label="系统设置",
            target=self._gateway["endpoint"],
        )
        return {"message": "Gateway config updated", "config": copy.deepcopy(self._gateway)}

    def settings_gateway_test(self, endpoint: str, model: str) -> dict[str, Any]:
        if not endpoint or not model:
            raise PeripheralError(400, "网关地址与模型不能为空", "GATEWAY_TEST_INVALID")
        return {"success": True, "latencyMs": 138, "message": "连接测试成功，鉴权与模型调用正常。"}

    def settings_dotx_list(self) -> dict[str, Any]:
        return {"items": copy.deepcopy(self._dotx_templates)}

    def settings_dotx_upload(self, file_name: str, file_size: Any, version: str) -> dict[str, Any]:
        if not file_name:
            raise PeripheralError(400, "模板文件名不能为空", "DOTX_NAME_REQUIRED")
        item = {
            "id": self._next_id("DOTX"),
            "name": file_name,
            "version": version or "2026.04",
            "uploadedBy": "当前用户",
            "uploadedAt": now_display(),
            "size": size_label(file_size),
            "isActive": False,
        }
        self._dotx_templates.insert(0, item)
        return {"message": "Uploaded", "item": copy.deepcopy(item), "items": copy.deepcopy(self._dotx_templates)}

    def settings_dotx_activate(self, template_id: str) -> dict[str, Any]:
        matched = False
        for item in self._dotx_templates:
            item["isActive"] = item["id"] == template_id
            matched = matched or item["id"] == template_id
        if not matched:
            raise PeripheralError(404, "Template not found", "DOTX_NOT_FOUND")
        item = next(entry for entry in self._dotx_templates if entry["id"] == template_id)
        return {"message": "Activated", "item": copy.deepcopy(item), "items": copy.deepcopy(self._dotx_templates)}

    def settings_excel_list(self) -> dict[str, Any]:
        return {
            "items": copy.deepcopy(self._excel_templates),
            "tableOptions": copy.deepcopy(self._structured_table_options),
        }

    def settings_excel_upload(self, table_key: str, file_name: str, version: str) -> dict[str, Any]:
        matched = next((item for item in self._structured_table_options if item["key"] == table_key), None)
        if matched is None:
            raise PeripheralError(400, "无效的数据表类型", "XLSX_TABLE_INVALID")
        if not file_name:
            raise PeripheralError(400, "模板文件名不能为空", "XLSX_NAME_REQUIRED")
        item = {
            "id": self._next_id("XLSX"),
            "tableKey": matched["key"],
            "tableLabel": matched["label"],
            "version": version or "2026.04",
            "uploadedBy": "当前用户",
            "uploadedAt": now_display(),
            "fileName": file_name,
            "isActive": False,
        }
        self._excel_templates.insert(0, item)
        return {"message": "Uploaded", "item": copy.deepcopy(item), "items": copy.deepcopy(self._excel_templates)}

    def settings_excel_activate(self, template_id: str) -> dict[str, Any]:
        target = next((item for item in self._excel_templates if item["id"] == template_id), None)
        if target is None:
            raise PeripheralError(404, "Template not found", "XLSX_TEMPLATE_NOT_FOUND")
        for item in self._excel_templates:
            if item["tableKey"] == target["tableKey"]:
                item["isActive"] = item["id"] == template_id
        return {"message": "Activated", "item": copy.deepcopy(target), "items": copy.deepcopy(self._excel_templates)}

    def settings_backups_list(self) -> dict[str, Any]:
        latest_restore = next((item.get("restoredAt") for item in self._backups if item.get("restoredAt")), "")
        return {"items": copy.deepcopy(self._backups), "latestRestoreAt": latest_restore}

    def settings_backups_create(self, note: str) -> dict[str, Any]:
        item = {
            "id": self._next_id("BKP"),
            "type": "manual",
            "status": "success",
            "size": "2.8 GB",
            "createdAt": now_display(),
            "createdBy": "当前用户",
            "note": note or "手动备份",
            "restoredAt": "",
        }
        self._backups.insert(0, item)
        return {"message": "Backup created", "item": copy.deepcopy(item), "items": copy.deepcopy(self._backups)}

    def settings_backups_restore(self, backup_id: str) -> dict[str, Any]:
        item = next((entry for entry in self._backups if entry["id"] == backup_id), None)
        if item is None:
            raise PeripheralError(404, "Backup not found", "BACKUP_NOT_FOUND")
        item["restoredAt"] = now_display()
        item["restoredBy"] = "当前用户"
        return {"message": "Backup restored", "item": copy.deepcopy(item), "items": copy.deepcopy(self._backups)}

    def settings_health(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._health)


peripheral_store = PeripheralStore()
