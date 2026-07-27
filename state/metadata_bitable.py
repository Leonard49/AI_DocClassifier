# -*- coding: utf-8 -*-
"""Ensure metadata bitable under TARGET and upsert records by obj_token."""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from classify.doc_metadata import DOC_TYPES, DocMetadata
from classify.module_product_map import PRODUCT_LINES
from feishu.bitable import FeishuBitableClient, FeishuBitableError
from feishu.create_feishu_node import FeishuNodeCreator
from feishu.title_check import FolderNameChecker
from feishu.wiki_meta import WikiMetaClient

TABLE_NAME = "文档元数据"

# Feishu field type codes
_TYPE_TEXT = 1
_TYPE_SINGLE_SELECT = 3
_TYPE_DATETIME = 5
_TYPE_URL = 15

# Canonical column names (match plan)
FIELD_TITLE = "标题"
FIELD_DOC_ID = "文档ID"
FIELD_PRODUCT_LINE = "产品线"
FIELD_MODULES = "模块型号"
FIELD_DOC_TYPE = "文档类型"
FIELD_AUTHOR = "作者"
FIELD_SOURCE_FOLDER = "来源文件夹"
FIELD_SOURCE_PATH = "源路径"
FIELD_WIKI_URL = "Wiki链接"
FIELD_UPDATED_AT = "更新时间"


@dataclass
class MetadataBitableRef:
    node_token: str
    app_token: str
    table_id: str
    title: str


class MetadataRecordIndex:
    """Local SQLite: (app_token, table_id, obj_token) -> record_id for upsert."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(db_path, timeout=30)
        self._conn.execute("PRAGMA journal_mode=DELETE")
        self._ensure_schema()
        self._conn.commit()

    def _table_exists(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def _pk_columns(self, table: str) -> List[str]:
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        ranked = sorted(
            ((int(r[5]), r[1]) for r in rows if r[5]),
            key=lambda x: x[0],
        )
        return [name for _, name in ranked]

    def _ensure_schema(self) -> None:
        new_ddl = """
            CREATE TABLE IF NOT EXISTS metadata_records (
                app_token TEXT NOT NULL,
                table_id TEXT NOT NULL,
                obj_token TEXT NOT NULL,
                record_id TEXT NOT NULL,
                updated_at REAL,
                PRIMARY KEY (app_token, table_id, obj_token)
            )
        """
        if not self._table_exists("metadata_records"):
            self._conn.execute(new_ddl)
            return

        pk = self._pk_columns("metadata_records")
        if pk == ["app_token", "table_id", "obj_token"]:
            return

        # Legacy single-bitable index: PRIMARY KEY(obj_token)
        self._conn.execute("ALTER TABLE metadata_records RENAME TO metadata_records_legacy")
        self._conn.execute(new_ddl)
        legacy_cols = {
            r[1]
            for r in self._conn.execute(
                "PRAGMA table_info(metadata_records_legacy)"
            ).fetchall()
        }
        has_app = "app_token" in legacy_cols
        has_table = "table_id" in legacy_cols
        self._conn.execute(
            f"""
            INSERT OR IGNORE INTO metadata_records
                (app_token, table_id, obj_token, record_id, updated_at)
            SELECT
                {"COALESCE(NULLIF(app_token, ''), '__legacy__')" if has_app else "'__legacy__'"},
                {"COALESCE(NULLIF(table_id, ''), '__legacy__')" if has_table else "'__legacy__'"},
                obj_token,
                record_id,
                {"updated_at" if "updated_at" in legacy_cols else "NULL"}
            FROM metadata_records_legacy
            """
        )
        self._conn.execute("DROP TABLE metadata_records_legacy")

    def get(
        self,
        obj_token: str,
        *,
        app_token: str,
        table_id: str,
    ) -> Optional[str]:
        row = self._conn.execute(
            """
            SELECT record_id FROM metadata_records
            WHERE app_token = ? AND table_id = ? AND obj_token = ?
            """,
            (app_token, table_id, obj_token),
        ).fetchone()
        return row[0] if row else None

    def put(
        self,
        obj_token: str,
        record_id: str,
        *,
        app_token: str = "",
        table_id: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO metadata_records
                (app_token, table_id, obj_token, record_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(app_token, table_id, obj_token) DO UPDATE SET
                record_id = excluded.record_id,
                updated_at = excluded.updated_at
            """,
            (app_token or "", table_id or "", obj_token, record_id, time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _select_options(names: Sequence[str]) -> Dict[str, Any]:
    return {"options": [{"name": n} for n in names]}


def _desired_fields() -> List[Dict[str, Any]]:
    product_lines = list(PRODUCT_LINES) + ["Others"]
    seen = set()
    pl_opts = []
    for x in product_lines:
        if x not in seen:
            seen.add(x)
            pl_opts.append(x)
    return [
        {"field_name": FIELD_TITLE, "type": _TYPE_TEXT},
        {"field_name": FIELD_DOC_ID, "type": _TYPE_TEXT},
        {
            "field_name": FIELD_PRODUCT_LINE,
            "type": _TYPE_SINGLE_SELECT,
            "property": _select_options(pl_opts),
        },
        {"field_name": FIELD_MODULES, "type": _TYPE_TEXT},
        {
            "field_name": FIELD_DOC_TYPE,
            "type": _TYPE_SINGLE_SELECT,
            "property": _select_options(list(DOC_TYPES)),
        },
        {"field_name": FIELD_AUTHOR, "type": _TYPE_TEXT},
        {"field_name": FIELD_SOURCE_FOLDER, "type": _TYPE_TEXT},
        {"field_name": FIELD_SOURCE_PATH, "type": _TYPE_TEXT},
        {"field_name": FIELD_WIKI_URL, "type": _TYPE_URL},
        {
            "field_name": FIELD_UPDATED_AT,
            "type": _TYPE_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm"},
        },
    ]


def metadata_to_fields(meta: DocMetadata, *, updated_ms: Optional[int] = None) -> Dict[str, Any]:
    ts = updated_ms if updated_ms is not None else int(time.time() * 1000)
    fields: Dict[str, Any] = {
        FIELD_TITLE: meta.title,
        FIELD_DOC_ID: meta.obj_token,
        FIELD_PRODUCT_LINE: meta.product_line,
        FIELD_MODULES: meta.modules,
        FIELD_DOC_TYPE: meta.doc_type,
        FIELD_AUTHOR: meta.author,
        FIELD_SOURCE_FOLDER: meta.source_folder,
        FIELD_SOURCE_PATH: meta.source_path,
        FIELD_UPDATED_AT: ts,
    }
    if meta.wiki_url:
        fields[FIELD_WIKI_URL] = {"text": meta.title or "Wiki", "link": meta.wiki_url}
    return fields


def ensure_metadata_bitable(
    *,
    space_id: str,
    target_parent_token: str,
    title: str,
    creator: FeishuNodeCreator,
    name_checker: FolderNameChecker,
    bitable: FeishuBitableClient,
    wiki_meta: WikiMetaClient,
    app_token_override: Optional[str] = None,
) -> MetadataBitableRef:
    """
    Find or create wiki bitable under TARGET, ensure data table + columns.
    """
    app_token = (app_token_override or "").strip()
    node_token = ""

    if not app_token:
        # Prefer exact title match among children
        children = name_checker.list_children(space_id, target_parent_token)
        if title in children:
            node_token = children[title]
            node = wiki_meta.get_node(node_token)
            if node.get("obj_type") != "bitable":
                raise RuntimeError(
                    f"目标下已存在同名节点但不是 bitable: {title} ({node.get('obj_type')})"
                )
            app_token = node.get("obj_token") or ""
        else:
            resp, new_token, new_title = creator.create_lark_node(
                target_parent_token,
                title,
                obj_type="bitable",
            )
            if not new_token:
                raise RuntimeError(f"创建多维表格失败: {resp}")
            node_token = new_token
            name_checker.invalidate_children(space_id, target_parent_token)
            node = wiki_meta.get_node(node_token)
            app_token = node.get("obj_token") or ""
            title = new_title or title

        if not app_token:
            raise RuntimeError("无法取得 bitable app_token (obj_token)")
    else:
        # Still try to resolve node_token for logging (optional)
        children = name_checker.list_children(space_id, target_parent_token)
        if title in children:
            node_token = children[title]

    table_id = _ensure_table_and_fields(bitable, app_token)
    return MetadataBitableRef(
        node_token=node_token,
        app_token=app_token,
        table_id=table_id,
        title=title,
    )


def _ensure_table_and_fields(bitable: FeishuBitableClient, app_token: str) -> str:
    tables = bitable.list_tables(app_token)
    table_id = None
    for t in tables:
        if (t.get("name") or "") == TABLE_NAME:
            table_id = t.get("table_id")
            break

    desired = _desired_fields()
    if not table_id:
        # Create with all fields up front when possible
        created = bitable.create_table(app_token, TABLE_NAME, fields=desired)
        table_id = created.get("table_id")
        if not table_id:
            # Some responses nest differently
            table_id = (created.get("table") or {}).get("table_id")
        if not table_id:
            # Fallback: create empty then add fields
            created = bitable.create_table(app_token, TABLE_NAME)
            table_id = created.get("table_id") or (created.get("table") or {}).get(
                "table_id"
            )
        if not table_id:
            raise RuntimeError(f"创建数据表失败: {created}")
        # If created without fields, add them
        existing = {f.get("field_name") for f in bitable.list_fields(app_token, table_id)}
        for field in desired:
            if field["field_name"] in existing:
                continue
            try:
                bitable.create_field(
                    app_token,
                    table_id,
                    field["field_name"],
                    field["type"],
                    property=field.get("property"),
                )
            except FeishuBitableError as exc:
                print(f"⚠️ 创建字段跳过 {field['field_name']}: {exc}")
        return table_id

    existing_names = {f.get("field_name") for f in bitable.list_fields(app_token, table_id)}
    for field in desired:
        if field["field_name"] in existing_names:
            continue
        try:
            bitable.create_field(
                app_token,
                table_id,
                field["field_name"],
                field["type"],
                property=field.get("property"),
            )
            print(f"✅ 补齐字段: {field['field_name']}")
        except FeishuBitableError as exc:
            print(f"⚠️ 创建字段失败 {field['field_name']}: {exc}")
    return table_id


def upsert_metadata_record(
    bitable: FeishuBitableClient,
    ref: MetadataBitableRef,
    index: MetadataRecordIndex,
    meta: DocMetadata,
) -> Tuple[str, str]:
    """
    Returns (action, record_id) where action is 'created' or 'updated'.
    """
    fields = metadata_to_fields(meta)
    existing = index.get(
        meta.obj_token, app_token=ref.app_token, table_id=ref.table_id
    )
    if existing:
        try:
            bitable.update_record(ref.app_token, ref.table_id, existing, fields)
            index.put(
                meta.obj_token,
                existing,
                app_token=ref.app_token,
                table_id=ref.table_id,
            )
            return "updated", existing
        except FeishuBitableError as exc:
            # Stale record id — create new
            print(f"⚠️ 更新失败，改为新建 ({meta.obj_token}): {exc}")

    record = bitable.create_record(ref.app_token, ref.table_id, fields)
    record_id = record.get("record_id") or record.get("id")
    if not record_id:
        raise RuntimeError(f"创建记录未返回 record_id: {record}")
    index.put(
        meta.obj_token,
        record_id,
        app_token=ref.app_token,
        table_id=ref.table_id,
    )
    return "created", record_id


__all__ = [
    "TABLE_NAME",
    "MetadataBitableRef",
    "MetadataRecordIndex",
    "ensure_metadata_bitable",
    "upsert_metadata_record",
    "metadata_to_fields",
]
