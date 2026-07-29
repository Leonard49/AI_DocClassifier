# -*- coding: utf-8 -*-
"""Feishu Bitable (多维表格) API helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .http import feishu_request
from .token_manager import TokenManager

logger = logging.getLogger(__name__)


class FeishuBitableError(Exception):
    def __init__(self, code: Any, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"bitable error code={code} msg={msg}")


class FeishuBitableClient:
    """Thin wrapper around bitable/v1 endpoints."""

    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token_manager.get_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _json(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict] = None,
        body: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        resp = feishu_request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=body,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuBitableError(data.get("code"), data.get("msg", "unknown"))
        return data.get("data") or {}

    def list_tables(self, app_token: str) -> List[Dict[str, Any]]:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables"
        items: List[Dict[str, Any]] = []
        page_token = None
        while True:
            params: Dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self._json("GET", url, params=params)
            items.extend(data.get("items") or [])
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        return items

    def create_table(
        self,
        app_token: str,
        name: str,
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables"
        body: Dict[str, Any] = {"table": {"name": name}}
        if fields:
            body["table"]["fields"] = fields
        data = self._json("POST", url, body=body)
        return data.get("table") or data

    def list_fields(self, app_token: str, table_id: str) -> List[Dict[str, Any]]:
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
            f"/tables/{table_id}/fields"
        )
        items: List[Dict[str, Any]] = []
        page_token = None
        while True:
            params: Dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = self._json("GET", url, params=params)
            items.extend(data.get("items") or [])
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
        return items

    def create_field(
        self,
        app_token: str,
        table_id: str,
        field_name: str,
        field_type: int,
        property: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        field_type: 1=Text, 2=Number, 3=SingleSelect, 4=MultiSelect,
                    5=DateTime, 7=Checkbox, 15=Url, ...
        """
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
            f"/tables/{table_id}/fields"
        )
        body: Dict[str, Any] = {"field_name": field_name, "type": field_type}
        if property:
            body["property"] = property
        return self._json("POST", url, body=body)

    def create_record(
        self,
        app_token: str,
        table_id: str,
        fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
            f"/tables/{table_id}/records"
        )
        data = self._json("POST", url, body={"fields": fields})
        return data.get("record") or data

    def update_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
            f"/tables/{table_id}/records/{record_id}"
        )
        data = self._json("PUT", url, body={"fields": fields})
        return data.get("record") or data

    def batch_create_records(
        self,
        app_token: str,
        table_id: str,
        records: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """records: [{'fields': {...}}, ...] — max 500 per call."""
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
            f"/tables/{table_id}/records/batch_create"
        )
        data = self._json("POST", url, body={"records": records})
        return data.get("records") or []


__all__ = ["FeishuBitableClient", "FeishuBitableError"]
