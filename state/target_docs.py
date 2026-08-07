# -*- coding: utf-8 -*-
"""List leaf docx under TARGET (classified corpus) for side tools."""

from __future__ import annotations

from typing import Dict, List, Optional

from feishu.token_manager import TokenManager
from feishu.wiki_scanner import SimpleWikiScanner


def list_target_leaf_docs(
    tm: TokenManager,
    *,
    space_id: str,
    target_root_token: str,
    max_documents: int = 0,
) -> List[Dict]:
    """
    Scan TARGET_PARENT_TOKEN (or override) for leaf docx.

    Tools should use this as the default document universe so uncopied
    source docs are never processed.
    """
    root = (target_root_token or "").strip()
    if not root:
        raise ValueError("target_root_token is required (TARGET_PARENT_TOKEN)")
    scanner = SimpleWikiScanner(tm, enable_db_cache=False)
    docs = scanner.scan_space(
        space_id=space_id,
        root_token=root,
        use_cache=False,
        max_documents=max_documents if max_documents > 0 else 0,
    )
    out: List[Dict] = []
    for d in docs:
        item = dict(d)
        item["target_root_token"] = root
        # Path under TARGET (classified folder breadcrumb)
        item["target_path"] = item.get("source_path") or ""
        out.append(item)
    return out


def dedupe_by_obj_token(docs: List[Dict]) -> List[Dict]:
    by_obj: Dict[str, Dict] = {}
    for d in docs:
        obj = d.get("obj_token") or d.get("node_token") or ""
        if not obj:
            continue
        by_obj.setdefault(obj, d)
    return list(by_obj.values())


__all__ = ["list_target_leaf_docs", "dedupe_by_obj_token"]
