from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, VARCHAR
from sqlalchemy.orm import backref, relationship

from app.models import Base


def _size_label(size: int) -> str:
    if size <= 0:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.2f} MB"


class RawFolder(Base):
    __tablename__ = "raw_folders"

    id = Column(BigInteger, primary_key=True)
    parent_id = Column(BigInteger, ForeignKey("raw_folders.id", ondelete="CASCADE"))
    name = Column(VARCHAR(255), nullable=False)
    path = Column(Text, nullable=False)
    tier = Column(VARCHAR(20), nullable=False)
    bid_type = Column(VARCHAR(20))
    customer_name = Column(VARCHAR(200))
    project_id = Column(VARCHAR(50))
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    children = relationship("RawFolder", backref=backref("parent", remote_side=[id]))
    files = relationship("RawFile", back_populates="folder", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "tier": self.tier,
            "bidType": self.bid_type,
            "customerName": self.customer_name,
            "projectId": self.project_id,
            "sortOrder": self.sort_order,
            "children": [c.to_dict() for c in self.children] if self.children else [],
        }


class RawFile(Base):
    __tablename__ = "raw_files"

    id = Column(BigInteger, primary_key=True)
    folder_id = Column(BigInteger, ForeignKey("raw_folders.id", ondelete="CASCADE"), nullable=False)
    name = Column(VARCHAR(255), nullable=False)
    size_bytes = Column(BigInteger, default=0)
    mime_type = Column(VARCHAR(100))
    minio_key = Column(VARCHAR(500), nullable=False)
    minio_bucket = Column(VARCHAR(100), default="bid-materials")
    version = Column(Integer, default=1)
    ext_fields = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(VARCHAR(100))
    updated_by = Column(VARCHAR(100))

    folder = relationship("RawFolder", back_populates="files")
    versions = relationship("RawFileVersion", back_populates="file", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        size = self.size_bytes or 0
        ext = self.ext_fields or {}
        if size < 1024:
            size_label = f"{size} B"
        elif size < 1024 * 1024:
            size_label = f"{size / 1024:.1f} KB"
        else:
            size_label = f"{size / 1024 / 1024:.2f} MB"

        suffix = self.name.split(".")[-1].lower() if "." in self.name else "file"

        return {
            "id": f"RAW-{self.id:04d}",
            "name": self.name,
            "folderPath": self.folder.path if self.folder else "",
            "ext": suffix,
            "type": suffix,
            "size": size,
            "sizeLabel": size_label,
            "bidType": ext.get("bidType") or "",
            "projectId": ext.get("projectId") or "",
            "projectCode": ext.get("projectCode") or "",
            "projectName": ext.get("projectName") or "",
            "customerName": ext.get("customerName") or "",
            "customerId": ext.get("customerId") or "",
            "customerCanonicalName": ext.get("customerCanonicalName") or "",
            "customerAliases": ext.get("customerAliases") or [],
            "identityScope": ext.get("identityScope") or "",
            "identityDisplay": ext.get("identityDisplay") or "",
            "materialTier": ext.get("materialTier") or (self.folder.tier if self.folder else ""),
            "materialTierLabel": ext.get("materialTierLabel") or "",
            "version": self.version,
            "lastAction": ext.get("lastAction") or "upload",
            "lastOperator": ext.get("lastOperator") or "",
            "sourceRelativePath": ext.get("sourceRelativePath") or self.name,
            "sourceRootFolder": ext.get("sourceRootFolder") or "",
            "cleanStatus": ext.get("cleanStatus") or "pending",
            "cleanMessage": ext.get("cleanMessage") or "",
            "cleanResultStatus": ext.get("cleanResultStatus") or "",
            "cleanUpdatedAt": ext.get("cleanUpdatedAt") or "",
            "cleanedFileName": ext.get("cleanedFileName") or "",
            "cleanedSize": ext.get("cleanedSize") or 0,
            "cleanedSizeLabel": _size_label(int(ext.get("cleanedSize") or 0)),
            "cleanedAt": ext.get("cleanedAt") or "",
            "hasCleanedWord": bool(ext.get("cleanedMinioKey")),
            "cleanedDownloadUrl": f"/api/materials/raw/RAW-{self.id:04d}/cleaned/content" if ext.get("cleanedMinioKey") else "",
            "updatedAt": self.updated_at.isoformat() if self.updated_at else "",
        }


class RawFileVersion(Base):
    __tablename__ = "raw_file_versions"

    id = Column(BigInteger, primary_key=True)
    file_id = Column(BigInteger, ForeignKey("raw_files.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    minio_key = Column(VARCHAR(500), nullable=False)
    size_bytes = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(VARCHAR(100))

    file = relationship("RawFile", back_populates="versions")


class StructuredTable(Base):
    __tablename__ = "structured_tables"

    id = Column(BigInteger, primary_key=True)
    table_key = Column(VARCHAR(80), unique=True, nullable=False)
    table_label = Column(VARCHAR(200), nullable=False)
    schema_def = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    rows = relationship("StructuredRow", back_populates="table", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tableKey": self.table_key,
            "tableLabel": self.table_label,
            "schemaDef": self.schema_def,
        }


class StructuredRow(Base):
    __tablename__ = "structured_rows"

    id = Column(BigInteger, primary_key=True)
    table_id = Column(BigInteger, ForeignKey("structured_tables.id", ondelete="CASCADE"), nullable=False)
    row_data = Column(JSONB, nullable=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(VARCHAR(100))
    updated_by = Column(VARCHAR(100))

    table = relationship("StructuredTable", back_populates="rows")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": f"MAT-{self.id:04d}",
            "name": self.row_data.get("名称") or self.row_data.get("name") or "未命名",
            "type": "结构化表格",
            "icon": "table_chart",
            "version": str(self.version),
            "updatedAt": self.updated_at.isoformat() if self.updated_at else "",
            "tableKey": self.table.table_key if self.table else "",
            "tableLabel": self.table.table_label if self.table else "",
            "rowData": self.row_data,
        }


class WikiNode(Base):
    __tablename__ = "wiki_nodes"

    id = Column(BigInteger, primary_key=True)
    parent_id = Column(BigInteger, ForeignKey("wiki_nodes.id", ondelete="CASCADE"))
    title = Column(VARCHAR(300), nullable=False)
    tier = Column(VARCHAR(20), nullable=False)
    path = Column(Text, nullable=False)
    bid_types = Column(ARRAY(VARCHAR(20)), default=["通用"])
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    children = relationship("WikiNode", backref=backref("parent", remote_side=[id]))
    doc = relationship("WikiDoc", back_populates="node", uselist=False, cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": f"WIKI-{self.id:04d}",
            "title": self.title,
            "tier": self.tier,
            "path": self.path,
            "bidTypes": self.bid_types or ["通用"],
            "children": [c.to_dict() for c in self.children] if self.children else [],
        }


class WikiDoc(Base):
    __tablename__ = "wiki_docs"

    id = Column(BigInteger, primary_key=True)
    node_id = Column(BigInteger, ForeignKey("wiki_nodes.id", ondelete="CASCADE"), unique=True, nullable=False)
    markdown_content = Column(Text)
    ai_summary = Column(Text)
    tags = Column(ARRAY(VARCHAR(100)), default=[])
    minio_key = Column(VARCHAR(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    node = relationship("WikiNode", back_populates="doc")
    attachments = relationship("WikiAttachment", back_populates="doc", cascade="all, delete-orphan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": f"WIKI-{self.node_id:04d}",
            "title": self.node.title if self.node else "",
            "markdownContent": self.markdown_content or "",
            "aiSummary": self.ai_summary or "",
            "tags": self.tags or [],
            "applicableTypes": self.node.bid_types if self.node else ["通用"],
            "path": self.node.path if self.node else "",
            "pathText": self.node.path if self.node else "",
            "updatedAt": self.updated_at.isoformat() if self.updated_at else "",
            "attachments": [],
        }


class WikiAttachment(Base):
    __tablename__ = "wiki_attachments"

    id = Column(BigInteger, primary_key=True)
    doc_id = Column(BigInteger, ForeignKey("wiki_docs.id", ondelete="CASCADE"), nullable=False)
    file_name = Column(VARCHAR(255), nullable=False)
    size_bytes = Column(BigInteger, default=0)
    mime_type = Column(VARCHAR(100))
    minio_key = Column(VARCHAR(500))
    minio_bucket = Column(VARCHAR(100), default="bid-materials")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(VARCHAR(100))

    doc = relationship("WikiDoc", back_populates="attachments")


class TemplateAsset(Base):
    __tablename__ = "template_assets"

    id = Column(BigInteger, primary_key=True)
    asset_type = Column(VARCHAR(20), nullable=False)
    table_key = Column(VARCHAR(80))
    file_name = Column(VARCHAR(255), nullable=False)
    version = Column(VARCHAR(40), nullable=False)
    minio_key = Column(VARCHAR(500))
    minio_bucket = Column(VARCHAR(100), default="bid-templates")
    size_bytes = Column(BigInteger, default=0)
    mime_type = Column(VARCHAR(100))
    is_active = Column(Boolean, default=False)
    uploaded_by = Column(VARCHAR(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(VARCHAR(100), nullable=False)
    user_name = Column(VARCHAR(100))
    action = Column(VARCHAR(80), nullable=False)
    action_type = Column(VARCHAR(40), nullable=False)
    module_id = Column(VARCHAR(80), nullable=False)
    module_label = Column(VARCHAR(200))
    target = Column(VARCHAR(500))
    status = Column(VARCHAR(20))
    diff = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": f"AUD-{self.id:04d}",
            "time": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "",
            "user": self.user_name or self.user_id,
            "userAvatar": (self.user_name or self.user_id)[:1] or "人",
            "action": self.action,
            "actionType": self.action_type,
            "module": self.module_id,
            "moduleLabel": self.module_label or self.module_id,
            "target": self.target or "",
            "status": self.status or "成功",
            "diff": self.diff or {"before": {}, "after": {}},
        }
