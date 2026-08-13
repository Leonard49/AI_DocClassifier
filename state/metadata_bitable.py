# -*- coding: utf-8 -*-
"""Ensure metadata bitable under TARGET and upsert records by obj_token."""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from classify.doc_metadata import DOC_TYPES, DocMetadata
from classify.module_product_map import PRODUCT_LINES
from feishu.bitable import FeishuBitableClient, FeishuBitableError
from feishu.create_feishu_node import FeishuNodeCreator
from feishu.title_check import FolderNameChecker
from feishu.wiki_meta import WikiMetaClient
from state.operation_ledger import (
    OP_METADATA_BITABLE,
    OperationLedger,
    bitable_scope_key,
    default_tool_ops_db_path,
)

TABLE_NAME = "文档元数据"

# Feishu field type codes
_TYPE_TEXT = 1
_TYPE_SINGLE_SELECT = 3
_TYPE_DATETIME = 5
_TYPE_URL = 15

# Canonical column names (match plan)
FIELD_TITLE = "标题"
FIELD_ORIGINAL_TITLE = "原文档名称"
FIELD_DOC_ID = "文档ID"
FIELD_PRODUCT_LINE = "产品线"
FIELD_MODULES = "模块型号"
FIELD_DOC_TYPE = "文档类型"
FIELD_THEME = "文章主题"
FIELD_AUTHOR = "作者"
FIELD_SOURCE_FOLDER = "来源文件夹"
FIELD_SOURCE_PATH = "源路径"
FIELD_SOURCE_DOC_PATH = "源文档路径"
FIELD_SOURCE_CREATED_AT = "源文档创建时间"
FIELD_WIKI_URL = "Wiki链接"
FIELD_UPDATED_AT = "更新时间"


@dataclass
class MetadataBitableRef:
    node_token: str
    app_token: str
    table_id: str
    title: str


class MetadataRecordIndex:
    """
    Bitable record_id lookup backed by tool_ops.db (result_ref).

    Scope key is bitable:{app_token}/{table_id} so multi-table writes
    do not collide with wiki-node skip rows for the same op.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        op: str = OP_METADATA_BITABLE,
        ledger: Optional[OperationLedger] = None,
        legacy_index_db: Optional[str] = None,
    ):
        self.op = op
        tool_ops = None
        try:
            import config

            tool_ops = getattr(config, "TOOL_OPS_DB", None)
        except Exception:
            tool_ops = None
        tool_ops = tool_ops or default_tool_ops_db_path()

        legacy = legacy_index_db
        if (
            db_path
            and os.path.abspath(db_path) != os.path.abspath(tool_ops)
            and os.path.isfile(db_path)
        ):
            legacy = legacy or db_path

        if ledger is not None:
            self._ledger = ledger
            self._owns_ledger = False
        else:
            self._ledger = OperationLedger(tool_ops)
            self._owns_ledger = True

        self.db_path = self._ledger.db_path
        self._legacy_imported: Set[str] = set()
        if legacy:
            self._import_legacy_index(legacy)

    def _import_legacy_index(self, path: str) -> None:
        abs_path = os.path.abspath(path)
        if abs_path in self._legacy_imported or not os.path.isfile(path):
            return
        self._legacy_imported.add(abs_path)
        try:
            conn = sqlite3.connect(path, timeout=30)
            try:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata_records'"
                ).fetchone()
                if not row:
                    return
                cols = {r[1] for r in conn.execute("PRAGMA table_info(metadata_records)")}
                if not {"obj_token", "record_id"}.issubset(cols):
                    return
                has_app = "app_token" in cols
                has_table = "table_id" in cols
                select = "SELECT obj_token, record_id"
                if has_app:
                    select += ", app_token"
                if has_table:
                    select += ", table_id"
                select += " FROM metadata_records"
                for r in conn.execute(select):
                    obj = r[0]
                    rid = r[1]
                    if not obj or not rid:
                        continue
                    app = (r[2] if has_app else "") or "__legacy__"
                    # column index: obj, rid, [app], [table]
                    table = "__legacy__"
                    if has_app and has_table:
                        table = (r[3] or "") or "__legacy__"
                    elif has_table and not has_app:
                        table = (r[2] or "") or "__legacy__"
                    if self.get(obj, app_token=app, table_id=table):
                        continue
                    self.put(obj, rid, app_token=app, table_id=table)
            finally:
                conn.close()
        except sqlite3.Error:
            return

    def get(
        self,
        obj_token: str,
        *,
        app_token: str,
        table_id: str,
    ) -> Optional[str]:
        if not obj_token:
            return None
        return self._ledger.get_result_ref(
            obj_token,
            self.op,
            node_token=bitable_scope_key(app_token, table_id),
        )

    def put(
        self,
        obj_token: str,
        record_id: str,
        *,
        app_token: str = "",
        table_id: str = "",
    ) -> None:
        if not obj_token or not record_id:
            return
        self._ledger.mark(
            obj_token,
            self.op,
            node_token=bitable_scope_key(app_token, table_id),
            status="done",
            result_ref=record_id,
        )

    def close(self) -> None:
        if self._owns_ledger:
            self._ledger.close()


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
        {"field_name": FIELD_ORIGINAL_TITLE, "type": _TYPE_TEXT},
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
        {"field_name": FIELD_THEME, "type": _TYPE_TEXT},
        {"field_name": FIELD_AUTHOR, "type": _TYPE_TEXT},
        {"field_name": FIELD_SOURCE_FOLDER, "type": _TYPE_TEXT},
        {"field_name": FIELD_SOURCE_PATH, "type": _TYPE_TEXT},
        {"field_name": FIELD_SOURCE_DOC_PATH, "type": _TYPE_TEXT},
        {
            "field_name": FIELD_SOURCE_CREATED_AT,
            "type": _TYPE_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm"},
        },
        {"field_name": FIELD_WIKI_URL, "type": _TYPE_URL},
        {
            "field_name": FIELD_UPDATED_AT,
            "type": _TYPE_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm"},
        },
    ]


def metadata_to_fields(meta: DocMetadata, *, updated_ms: Optional[int] = None) -> Dict[str, Any]:
    ts = updated_ms if updated_ms is not None else int(time.time() * 1000)
    original = (meta.original_title or meta.title or "").strip()
    source_path = meta.source_path or ""
    fields: Dict[str, Any] = {
        FIELD_TITLE: meta.title,
        FIELD_ORIGINAL_TITLE: original,
        FIELD_DOC_ID: meta.obj_token,
        FIELD_PRODUCT_LINE: meta.product_line,
        FIELD_MODULES: meta.modules,
        FIELD_DOC_TYPE: meta.doc_type,
        FIELD_THEME: getattr(meta, "theme", "") or "",
        FIELD_AUTHOR: meta.author,
        FIELD_SOURCE_FOLDER: meta.source_folder,
        FIELD_SOURCE_PATH: source_path,
        FIELD_SOURCE_DOC_PATH: source_path,
        FIELD_UPDATED_AT: ts,
    }
    created_ms = int(getattr(meta, "source_created_ms", 0) or 0)
    if created_ms:
        fields[FIELD_SOURCE_CREATED_AT] = created_ms
    if meta.wiki_url:
        fields[FIELD_WIKI_URL] = {
            "text": original or meta.title or "Wiki",
            "link": meta.wiki_url,
        }
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
    *,
    skip_existing: bool = False,
) -> Tuple[str, str]:
    """
    Returns (action, record_id) where action is 'created', 'updated', or 'skipped'.
    """
    existing = index.get(
        meta.obj_token, app_token=ref.app_token, table_id=ref.table_id
    )
    if existing and skip_existing:
        return "skipped", existing

    fields = metadata_to_fields(meta)
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


def find_metadata_bitable(
    *,
    space_id: str,
    target_parent_token: str,
    title: str,
    name_checker: FolderNameChecker,
    bitable: FeishuBitableClient,
    wiki_meta: WikiMetaClient,
    app_token_override: Optional[str] = None,
) -> Optional[MetadataBitableRef]:
    """Return existing metadata bitable ref, or None (does not create)."""
    app_token = (app_token_override or "").strip()
    node_token = ""
    if not app_token:
        children = name_checker.list_children(space_id, target_parent_token)
        if title not in children:
            return None
        node_token = children[title]
        node = wiki_meta.get_node(node_token)
        if node.get("obj_type") != "bitable":
            return None
        app_token = node.get("obj_token") or ""
        if not app_token:
            return None
    else:
        children = name_checker.list_children(space_id, target_parent_token)
        if title in children:
            node_token = children[title]

    tables = bitable.list_tables(app_token)
    table_id = None
    for t in tables:
        if (t.get("name") or "") == TABLE_NAME:
            table_id = t.get("table_id")
            break
    if not table_id:
        return None
    return MetadataBitableRef(
        node_token=node_token,
        app_token=app_token,
        table_id=table_id,
        title=title,
    )


__all__ = [
    "TABLE_NAME",
    "MetadataBitableRef",
    "MetadataRecordIndex",
    "ensure_metadata_bitable",
    "find_metadata_bitable",
    "upsert_metadata_record",
    "metadata_to_fields",
]
