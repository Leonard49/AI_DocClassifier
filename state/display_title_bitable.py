# -*- coding: utf-8 -*-
"""Ensure display-title bitable and upsert rows (never renames wiki titles)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from classify.display_title import DisplayTitleRow
from feishu.bitable import FeishuBitableClient, FeishuBitableError
from feishu.create_feishu_node import FeishuNodeCreator
from feishu.title_check import FolderNameChecker
from feishu.wiki_meta import WikiMetaClient
from state.metadata_bitable import MetadataRecordIndex

TABLE_NAME = "展示标题"

_TYPE_TEXT = 1
_TYPE_DATETIME = 5
_TYPE_URL = 15

FIELD_DISPLAY_TITLE = "展示标题"
FIELD_ORIGINAL_TITLE = "原标题"
FIELD_DOC_ID = "文档ID"
FIELD_THEME = "文章主题"
FIELD_PRODUCT_LINE = "产品线"
FIELD_AUTHOR = "作者"
# Legacy columns (still written for older tables)
FIELD_DATE = "日期"
FIELD_MODEL_OR_PATH = "型号或路径"
FIELD_PURPOSE = "文章作用"
FIELD_MODULES = "模块型号"
FIELD_PATH = "路径面包屑"
FIELD_SOURCE_FOLDER = "来源文件夹"
FIELD_WIKI_URL = "Wiki链接"
FIELD_UPDATED_AT = "更新时间"


@dataclass
class DisplayTitleBitableRef:
    node_token: str
    app_token: str
    table_id: str
    title: str


def _desired_fields() -> List[Dict[str, Any]]:
    return [
        {"field_name": FIELD_DISPLAY_TITLE, "type": _TYPE_TEXT},
        {"field_name": FIELD_ORIGINAL_TITLE, "type": _TYPE_TEXT},
        {"field_name": FIELD_DOC_ID, "type": _TYPE_TEXT},
        {"field_name": FIELD_THEME, "type": _TYPE_TEXT},
        {"field_name": FIELD_PRODUCT_LINE, "type": _TYPE_TEXT},
        {"field_name": FIELD_AUTHOR, "type": _TYPE_TEXT},
        {"field_name": FIELD_DATE, "type": _TYPE_TEXT},
        {"field_name": FIELD_MODEL_OR_PATH, "type": _TYPE_TEXT},
        {"field_name": FIELD_PURPOSE, "type": _TYPE_TEXT},
        {"field_name": FIELD_MODULES, "type": _TYPE_TEXT},
        {"field_name": FIELD_PATH, "type": _TYPE_TEXT},
        {"field_name": FIELD_SOURCE_FOLDER, "type": _TYPE_TEXT},
        {"field_name": FIELD_WIKI_URL, "type": _TYPE_URL},
        {
            "field_name": FIELD_UPDATED_AT,
            "type": _TYPE_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm"},
        },
    ]


def row_to_fields(
    row: DisplayTitleRow, *, updated_ms: Optional[int] = None
) -> Dict[str, Any]:
    ts = updated_ms if updated_ms is not None else int(time.time() * 1000)
    theme = getattr(row, "theme", None) or row.purpose
    product = getattr(row, "product_line", None) or row.model_or_path
    author = getattr(row, "author", None) or ""
    fields: Dict[str, Any] = {
        FIELD_DISPLAY_TITLE: row.display_title,
        FIELD_ORIGINAL_TITLE: row.original_title,
        FIELD_DOC_ID: row.obj_token,
        FIELD_THEME: theme,
        FIELD_PRODUCT_LINE: product,
        FIELD_AUTHOR: author,
        FIELD_DATE: row.date_part,
        FIELD_MODEL_OR_PATH: product,
        FIELD_PURPOSE: theme,
        FIELD_MODULES: row.modules,
        FIELD_PATH: row.path_breadcrumb,
        FIELD_SOURCE_FOLDER: row.source_folder,
        FIELD_UPDATED_AT: ts,
    }
    if row.wiki_url:
        fields[FIELD_WIKI_URL] = {
            "text": row.display_title or row.original_title or "打开文档",
            "link": row.wiki_url,
        }
    return fields


def ensure_display_title_bitable(
    *,
    space_id: str,
    target_parent_token: str,
    title: str,
    creator: FeishuNodeCreator,
    name_checker: FolderNameChecker,
    bitable: FeishuBitableClient,
    wiki_meta: WikiMetaClient,
    app_token_override: Optional[str] = None,
) -> DisplayTitleBitableRef:
    app_token = (app_token_override or "").strip()
    node_token = ""

    if not app_token:
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
        children = name_checker.list_children(space_id, target_parent_token)
        if title in children:
            node_token = children[title]

    table_id = _ensure_table_and_fields(bitable, app_token)
    return DisplayTitleBitableRef(
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
        created = bitable.create_table(app_token, TABLE_NAME, fields=desired)
        table_id = created.get("table_id") or (created.get("table") or {}).get(
            "table_id"
        )
        if not table_id:
            created = bitable.create_table(app_token, TABLE_NAME)
            table_id = created.get("table_id") or (created.get("table") or {}).get(
                "table_id"
            )
        if not table_id:
            raise RuntimeError(f"创建数据表失败: {created}")
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


def upsert_display_title_record(
    bitable: FeishuBitableClient,
    ref: DisplayTitleBitableRef,
    index: MetadataRecordIndex,
    row: DisplayTitleRow,
    *,
    skip_existing: bool = False,
) -> Tuple[str, str]:
    existing = index.get(
        row.obj_token, app_token=ref.app_token, table_id=ref.table_id
    )
    if existing and skip_existing:
        return "skipped", existing

    fields = row_to_fields(row)
    if existing:
        try:
            bitable.update_record(ref.app_token, ref.table_id, existing, fields)
            index.put(
                row.obj_token,
                existing,
                app_token=ref.app_token,
                table_id=ref.table_id,
            )
            return "updated", existing
        except FeishuBitableError as exc:
            print(f"⚠️ 更新失败，改为新建 ({row.obj_token}): {exc}")

    record = bitable.create_record(ref.app_token, ref.table_id, fields)
    record_id = record.get("record_id") or record.get("id")
    if not record_id:
        raise RuntimeError(f"创建记录未返回 record_id: {record}")
    index.put(
        row.obj_token,
        record_id,
        app_token=ref.app_token,
        table_id=ref.table_id,
    )
    return "created", record_id


def find_display_title_bitable(
    *,
    space_id: str,
    target_parent_token: str,
    title: str,
    name_checker: FolderNameChecker,
    bitable: FeishuBitableClient,
    wiki_meta: WikiMetaClient,
    app_token_override: Optional[str] = None,
) -> Optional[DisplayTitleBitableRef]:
    """Return existing bitable ref, or None if not found (does not create)."""
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
    return DisplayTitleBitableRef(
        node_token=node_token,
        app_token=app_token,
        table_id=table_id,
        title=title,
    )


__all__ = [
    "TABLE_NAME",
    "DisplayTitleBitableRef",
    "ensure_display_title_bitable",
    "find_display_title_bitable",
    "upsert_display_title_record",
    "row_to_fields",
]
