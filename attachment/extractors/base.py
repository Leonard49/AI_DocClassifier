"""Base extractor with shared Feishu docx API helpers."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import config
from attachment.images import (
    MAX_UPLOAD_BYTES,
    image_mime,
    normalize_image_bytes,
)
from enrichment.markers import ATTACHMENT_HEADING_PREFIX, ATTACHMENT_SECTION_PREFIX
from feishu.http import feishu_request

IMAGE_BLOCK_TYPE = 27


class BaseExtractor:
    """Common Feishu API methods for attachment text/image extraction."""

    def __init__(self, token_manager):
        self.tm = token_manager

    @property
    def _token(self) -> str:
        return self.tm.get_token()

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def sanitize(text: str, max_len: int = 5000) -> str:
        if not text:
            return ""
        text = text.replace("\x00", "")
        cleaned = []
        for ch in text:
            cp = ord(ch)
            if cp < 32 and cp not in (9, 10, 13):
                continue
            cleaned.append(ch)
        text = "".join(cleaned)
        if len(text) > max_len:
            text = text[:max_len] + "..."
        return text.strip()

    def get_root_block_id(self, doc_token: str) -> Optional[str]:
        url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_token}/blocks"
        resp = feishu_request("GET", url, headers=self._headers)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("code") != 0:
            return None

        items = data.get("data", {}).get("items", [])
        root = next((b for b in items if b.get("parent_id") == ""), None)
        if root:
            return root["block_id"]

        has_more = data.get("data", {}).get("has_more", False)
        page_token = data.get("data", {}).get("page_token", "")
        while has_more and page_token:
            resp = feishu_request(
                "GET",
                url,
                headers=self._headers,
                params={"page_token": page_token},
            )
            data = resp.json()
            if data.get("code") != 0:
                break
            items = data.get("data", {}).get("items", [])
            root = next((b for b in items if b.get("parent_id") == ""), None)
            if root:
                return root["block_id"]
            has_more = data.get("data", {}).get("has_more", False)
            page_token = data.get("data", {}).get("page_token", "")
        return None

    @staticmethod
    def _json(resp) -> Dict[str, Any]:
        try:
            data = resp.json() if getattr(resp, "text", None) else {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def download_media_bytes(
        self, file_token: str, *, doc_token: str = ""
    ) -> Optional[bytes]:
        if not file_token:
            return None
        url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
        headers = {"Authorization": f"Bearer {self._token}"}
        params = None
        if doc_token:
            params = {
                "extra": json.dumps({"drive_route_token": doc_token}, ensure_ascii=False)
            }
        resp = feishu_request(
            "GET",
            url,
            headers=headers,
            params=params,
            stream=True,
            timeout=config.FEISHU_DOWNLOAD_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        payload = resp.content or b""
        if not payload:
            return None
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "json" in ctype or payload[:1] == b"{":
            return None
        return payload

    def _upload_image_to_block(
        self,
        doc_token: str,
        block_id: str,
        image_bytes: bytes,
        image_ext: str = "",
        quiet: bool = False,
    ) -> bool:
        try:
            payload, ext = normalize_image_bytes(image_bytes, image_ext)
        except Exception as exc:
            print(f"    图片格式无法转换: {exc}")
            return False
        if len(payload) > MAX_UPLOAD_BYTES:
            print(f"    图片过大 ({len(payload)} bytes)，跳过")
            return False
        mime = image_mime(ext)
        extra = json.dumps({"drive_route_token": doc_token}, ensure_ascii=False)
        r = feishu_request(
            "POST",
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {self._token}"},
            files={"file": (f"img.{ext}", payload, mime)},
            data={
                "file_name": f"img.{ext}",
                "parent_type": "docx_image",
                "parent_node": block_id,
                "size": str(len(payload)),
                "extra": extra,
            },
            timeout=config.FEISHU_DOWNLOAD_TIMEOUT,
        )
        ur = self._json(r)
        if ur.get("code") != 0:
            print(f"    上传失败: {ur.get('msg', '')[:80]}")
            return False
        file_token = ((ur.get("data") or {}).get("file_token") or "").strip()
        if not file_token:
            print("    上传失败: 未返回 file_token")
            return False
        r = feishu_request(
            "PATCH",
            f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_token}/blocks/{block_id}",
            headers=self._headers,
            json={"replace_image": {"token": file_token}},
        )
        jr = self._json(r)
        if jr.get("code") == 0:
            if not quiet:
                print("    图片 ✓")
            return True
        print(f"    PATCH失败: {jr.get('msg', '')[:80]}")
        return False

    def _delete_child_block(
        self, doc_token: str, parent_id: str, child_id: str
    ) -> None:
        url = (
            f"https://open.feishu.cn/open-apis/docx/v1/documents/"
            f"{doc_token}/blocks/{parent_id}/children"
        )
        items: List[Dict[str, Any]] = []
        page_token = ""
        while True:
            params: Dict[str, Any] = {"document_revision_id": -1, "page_size": 500}
            if page_token:
                params["page_token"] = page_token
            resp = feishu_request("GET", url, headers=self._headers, params=params)
            data = self._json(resp)
            if data.get("code") != 0:
                return
            items.extend((data.get("data") or {}).get("items") or [])
            if not (data.get("data") or {}).get("has_more"):
                break
            page_token = (data.get("data") or {}).get("page_token") or ""
            if not page_token:
                break
        for index, block in enumerate(items):
            if block.get("block_id") != child_id:
                continue
            feishu_request(
                "DELETE",
                f"{url}/batch_delete",
                headers=self._headers,
                params={"document_revision_id": -1},
                json={"start_index": index, "end_index": index + 1},
            )
            return

    def insert_image(
        self,
        doc_token: str,
        root_block_id: str,
        image_bytes: bytes,
        image_ext: str,
        img_size: int = 0,
    ) -> bool:
        _ = img_size
        url = (
            f"https://open.feishu.cn/open-apis/docx/v1/documents/"
            f"{doc_token}/blocks/{root_block_id}/children"
        )
        r = feishu_request(
            "POST",
            url,
            headers=self._headers,
            json={"children": [{"block_type": IMAGE_BLOCK_TYPE, "image": {}}]},
        )
        jr = self._json(r)
        if jr.get("code") != 0:
            print(f"    创建图块失败: {jr.get('msg', '')[:80]}")
            return False
        bid = ((jr.get("data") or {}).get("children") or [{}])[0].get("block_id")
        if not bid:
            print("    创建图块失败: 未返回 block_id")
            return False
        ok = self._upload_image_to_block(doc_token, bid, image_bytes, image_ext)
        if not ok:
            self._delete_child_block(doc_token, root_block_id, bid)
        return ok

    def list_root_children(self, doc_token: str) -> List[Dict[str, Any]]:
        root_id = self.get_root_block_id(doc_token) or doc_token
        url = (
            f"https://open.feishu.cn/open-apis/docx/v1/documents/"
            f"{doc_token}/blocks/{root_id}/children"
        )
        items: List[Dict[str, Any]] = []
        page_token = ""
        while True:
            params: Dict[str, Any] = {"document_revision_id": -1, "page_size": 500}
            if page_token:
                params["page_token"] = page_token
            resp = feishu_request("GET", url, headers=self._headers, params=params)
            data = self._json(resp)
            if data.get("code") != 0:
                break
            items.extend((data.get("data") or {}).get("items") or [])
            if not (data.get("data") or {}).get("has_more"):
                break
            page_token = (data.get("data") or {}).get("page_token") or ""
            if not page_token:
                break
        return items

    @staticmethod
    def _heading_text(block: Dict[str, Any]) -> str:
        for key in ("heading1", "heading2", "heading3"):
            heading = block.get(key) or {}
            parts = [
                (el.get("text_run") or {}).get("content", "")
                for el in heading.get("elements") or []
            ]
            text = "".join(parts).strip()
            if text:
                return text
        return ""

    def attachment_image_blocks(self, doc_token: str) -> List[Dict[str, Any]]:
        """Image blocks after the attachment-extract banner / first `附件：` heading."""
        children = self.list_root_children(doc_token)
        start = None
        for i, block in enumerate(children):
            text = self._heading_text(block)
            if text.startswith(ATTACHMENT_SECTION_PREFIX) or text.startswith(
                ATTACHMENT_HEADING_PREFIX
            ):
                start = i
                break
        if start is None:
            return []
        return [
            block
            for block in children[start:]
            if int(block.get("block_type") or 0) == IMAGE_BLOCK_TYPE
        ]

    def rebind_attachment_images(
        self,
        doc_token: str,
        *,
        source_doc_token: str = "",
    ) -> Dict[str, int]:
        """
        Re-upload extracted images onto this doc so wiki copies can render them.

        Wiki copy often keeps source media tokens; Feishu then shows a broken
        image on TARGET. Re-upload with extra.drive_route_token = this document.
        """
        stats = {"images": 0, "rebound": 0, "empty": 0, "failed": 0, "skipped": 0}
        blocks = self.attachment_image_blocks(doc_token)
        stats["images"] = len(blocks)
        if not blocks:
            return stats
        source_tokens: List[str] = []
        if source_doc_token and source_doc_token != doc_token:
            source_tokens = [
                ((b.get("image") or {}).get("token") or "").strip()
                for b in self.attachment_image_blocks(source_doc_token)
            ]
        for i, block in enumerate(blocks):
            block_id = block.get("block_id") or ""
            token = ((block.get("image") or {}).get("token") or "").strip()
            raw: Optional[bytes] = None
            if token:
                for extra_doc in (doc_token, source_doc_token, ""):
                    raw = self.download_media_bytes(token, doc_token=extra_doc)
                    if raw:
                        break
            if not raw and i < len(source_tokens) and source_tokens[i]:
                raw = self.download_media_bytes(
                    source_tokens[i], doc_token=source_doc_token
                )
            if not raw:
                if token:
                    stats["failed"] += 1
                else:
                    stats["empty"] += 1
                continue
            if self._upload_image_to_block(doc_token, block_id, raw, "", quiet=True):
                stats["rebound"] += 1
            else:
                stats["failed"] += 1
        return stats

    def append_blocks(self, doc_token: str, blocks: List[Dict[str, Any]]) -> None:
        if not blocks:
            return
        root_id = self.get_root_block_id(doc_token)
        if not root_id:
            raise RuntimeError("无法获取文档根块 ID")
        for i in range(0, len(blocks), 10):
            batch = blocks[i : i + 10]
            url = (
                f"https://open.feishu.cn/open-apis/docx/v1/documents/"
                f"{doc_token}/blocks/{root_id}/children"
            )
            r = feishu_request(
                "POST",
                url,
                headers=self._headers,
                json={"children": batch},
            )
            jr = r.json() if r.text else {}
            if r.status_code == 200 and jr.get("code") == 0:
                print(f"    ✓ {len(batch)}块")
            else:
                msg = jr.get("msg", "")[:120]
                raise RuntimeError(f"写入 blocks 失败: {jr.get('code', '?')} {msg}")

    def download_file(
        self, file_token: str, save_path: str, *, doc_token: str = ""
    ) -> None:
        url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
        headers = {"Authorization": f"Bearer {self._token}"}
        params = None
        if doc_token:
            params = {
                "extra": json.dumps({"drive_route_token": doc_token}, ensure_ascii=False)
            }
        resp = feishu_request(
            "GET",
            url,
            headers=headers,
            params=params,
            stream=True,
            timeout=config.FEISHU_DOWNLOAD_TIMEOUT,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"下载失败 HTTP {resp.status_code}")
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        if os.path.getsize(save_path) == 0:
            raise RuntimeError("文件大小为0")

    def extract(self, file_path: str, doc_token: str, root_block_id: str) -> None:
        raise NotImplementedError
